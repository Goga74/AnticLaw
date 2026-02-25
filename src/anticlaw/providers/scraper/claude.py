"""Claude.ai scraper — collect chat→project mapping via Playwright."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from anticlaw.providers.scraper.base import ScrapedProject, ScraperInfo

log = logging.getLogger(__name__)

# Pattern to extract org UUID from API paths like /api/organizations/{uuid}/...
_ORG_PATTERN = re.compile(r"/api/organizations/([0-9a-f-]{36})/")

# API path patterns we intercept
_PROJECTS_PATTERN = re.compile(
    r"/api/organizations/[0-9a-f-]{36}/projects(?:\?|$)"
)
_CHATS_PATTERN = re.compile(
    r"/api/organizations/[0-9a-f-]{36}/chat_conversations\?project_uuid="
)


class ClaudeScraper:
    """Scrape chat→project mapping from claude.ai using Playwright.

    Opens a visible browser window, waits for the user to log in,
    then intercepts network responses to collect project and chat data.
    """

    def __init__(self) -> None:
        self._org_id: str = ""
        self._projects: list[ScrapedProject] = []
        self._mapping: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "claude-scraper"

    @property
    def info(self) -> ScraperInfo:
        return ScraperInfo(
            display_name="Claude.ai Scraper",
            version="0.1.0",
            requires_auth=True,
            requires_browser=True,
        )

    def scrape(self, output: Path | None = None) -> dict[str, str]:
        """Launch browser, wait for login, scrape mapping.

        Args:
            output: Optional path to save mapping.json.

        Returns:
            Dict mapping chat UUIDs to project names.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as err:
            raise ImportError(
                "Playwright is not installed.\n"
                "Run: pip install anticlaw[scraper] && playwright install chromium"
            ) from err

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            try:
                page = browser.new_page()
                self._wait_for_login(page)
                self._discover_org_id(page)
                self._fetch_projects(page)
                self._fetch_all_chats(page)
            finally:
                browser.close()

        if output:
            self._save_mapping(output)

        return dict(self._mapping)

    def _wait_for_login(self, page) -> None:
        """Navigate to claude.ai and wait for user to log in."""
        page.goto("https://claude.ai")
        log.info("Waiting for user to log in at claude.ai...")
        # Wait for the user to reach an authenticated page
        # After login, URL will contain /new, /chats, /chat/, or /project/
        page.wait_for_url(
            re.compile(r"claude\.ai/(new|chats|chat/|project/)"),
            timeout=300_000,  # 5 minutes to log in
        )
        log.info("Login detected.")

    def _discover_org_id(self, page) -> None:
        """Discover organization ID from API calls."""
        if self._org_id:
            return

        # Try to get org ID from the bootstrap API call
        response = page.request.get("https://claude.ai/api/auth/current_user")
        if response.ok:
            data = response.json()
            memberships = data.get("memberships", [])
            if memberships:
                org = memberships[0].get("organization", {})
                self._org_id = org.get("uuid", "")

        if not self._org_id:
            raise RuntimeError(
                "Could not discover organization ID. "
                "Make sure you are logged into claude.ai."
            )

        log.info("Organization ID: %s", self._org_id)

    def _fetch_projects(self, page) -> None:
        """Fetch all projects from the API."""
        url = f"https://claude.ai/api/organizations/{self._org_id}/projects"
        response = page.request.get(url)

        if not response.ok:
            log.warning("Failed to fetch projects: HTTP %s", response.status)
            return

        data = response.json()
        # Response can be a list directly or wrapped in a key
        projects_list = data if isinstance(data, list) else data.get("projects", data.get("results", []))

        for proj in projects_list:
            if not isinstance(proj, dict):
                continue
            uuid = proj.get("uuid", "")
            name = proj.get("name", "")
            if not uuid or not name:
                continue

            # Skip starter/default projects
            if proj.get("is_starter_project", False):
                continue

            scraped = ScrapedProject(
                uuid=uuid,
                name=name,
                description=proj.get("description", ""),
                prompt_template=proj.get("prompt_template", ""),
            )
            self._projects.append(scraped)

        log.info("Found %d projects.", len(self._projects))

    def _fetch_all_chats(self, page) -> None:
        """Fetch chats for every project and build the mapping."""
        for project in self._projects:
            self._fetch_project_chats(page, project)
            # Rate limiting: small delay between requests
            time.sleep(1.0)

    def _fetch_project_chats(self, page, project: ScrapedProject) -> None:
        """Fetch chats belonging to a single project."""
        url = (
            f"https://claude.ai/api/organizations/{self._org_id}"
            f"/chat_conversations?project_uuid={project.uuid}"
        )
        response = page.request.get(url)

        if not response.ok:
            log.warning(
                "Failed to fetch chats for project '%s': HTTP %s",
                project.name,
                response.status,
            )
            return

        data = response.json()
        chats = data if isinstance(data, list) else data.get("conversations", data.get("results", []))

        for chat in chats:
            if not isinstance(chat, dict):
                continue
            chat_uuid = chat.get("uuid", "")
            if chat_uuid:
                project.chat_uuids.append(chat_uuid)
                self._mapping[chat_uuid] = project.name

        log.info(
            "Project '%s': %d chats.",
            project.name,
            len(project.chat_uuids),
        )

    def _save_mapping(self, output: Path) -> None:
        """Write mapping.json to disk."""
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self._mapping, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("Mapping saved to %s", output)

    # -- Utility methods for external access --

    @property
    def projects(self) -> list[ScrapedProject]:
        """Return scraped projects (available after scrape())."""
        return list(self._projects)

    @property
    def mapping(self) -> dict[str, str]:
        """Return chat→project mapping (available after scrape())."""
        return dict(self._mapping)

    def summary(self) -> dict[str, int]:
        """Return scrape statistics."""
        return {
            "projects": len(self._projects),
            "mapped_chats": len(self._mapping),
        }
