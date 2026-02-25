"""Claude.ai scraper — collect chat→project mapping via Playwright."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from anticlaw.core.config import resolve_home
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

# URL pattern indicating an authenticated page (post-login)
_AUTHENTICATED_URL = re.compile(r"claude\.ai/(new|chats|chat/|project/)")

# URL pattern indicating login page (session expired)
_LOGIN_URL = re.compile(r"claude\.ai/login")

_SESSION_FILENAME = "claude_session.json"


def _default_session_path(home: Path | None = None) -> Path:
    """Return default session file path: ACL_HOME/.acl/claude_session.json."""
    home_path = home or resolve_home()
    return home_path / ".acl" / _SESSION_FILENAME


class ClaudeScraper:
    """Scrape chat→project mapping from claude.ai using Playwright.

    Persists browser session to avoid repeated logins:
    - First run: opens visible browser, waits for manual login, saves session.
    - Subsequent runs: reuses saved session (headless). Falls back to
      manual login if the session has expired.
    """

    def __init__(self, home: Path | None = None) -> None:
        self._org_id: str = ""
        self._projects: list[ScrapedProject] = []
        self._mapping: dict[str, str] = {}
        self._session_path = _default_session_path(home)

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

    @property
    def session_path(self) -> Path:
        """Path to the persisted session file."""
        return self._session_path

    def scrape(self, output: Path | None = None) -> dict[str, str]:
        """Launch browser, authenticate, scrape mapping.

        Uses saved session if available. Falls back to manual login
        if the session is missing or expired.

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
            page = self._launch_authenticated(pw)
            try:
                self._discover_org_id(page)
                self._fetch_projects(page)
                self._fetch_all_chats(page)
            finally:
                page.context.browser.close()

        if output:
            self._save_mapping(output)

        return dict(self._mapping)

    def _launch_authenticated(self, pw) -> "Page":
        """Launch browser with session persistence.

        1. If session file exists → try headless with saved state.
           If session expired → delete file, fall back to manual login.
        2. If no session file → launch headed, wait for manual login,
           save session.
        """
        if self._session_path.exists():
            page = self._try_saved_session(pw)
            if page is not None:
                return page
            # Session expired — file already deleted, fall through

        return self._manual_login(pw)

    def _try_saved_session(self, pw) -> "Page | None":
        """Attempt to reuse a saved session. Returns page or None."""
        log.info("Trying saved session from %s", self._session_path)

        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=str(self._session_path),
        )
        page = context.new_page()

        page.goto("https://claude.ai")

        # Give the page a moment to redirect
        try:
            page.wait_for_url(
                _AUTHENTICATED_URL,
                timeout=15_000,
            )
        except Exception:
            # Not on an authenticated page — check if on login page
            pass

        current_url = page.url

        if _AUTHENTICATED_URL.search(current_url):
            log.info("Using saved session.")
            return page

        # Session expired
        log.info("Saved session expired, deleting %s", self._session_path)
        browser.close()
        self._session_path.unlink(missing_ok=True)
        return None

    def _manual_login(self, pw) -> "Page":
        """Launch headed browser, wait for user to log in, save session."""
        log.info("Launching browser for manual login...")

        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto("https://claude.ai/login")
        log.info("Waiting for user to log in at claude.ai...")

        # Wait for the user to reach an authenticated page
        page.wait_for_url(
            _AUTHENTICATED_URL,
            timeout=600_000,  # 10 minutes to log in
        )
        log.info("Login detected.")

        # Save session for future runs
        self._save_session(context)

        return page

    def _save_session(self, context) -> None:
        """Persist browser session state to disk."""
        self._session_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(self._session_path))
        log.info("Session saved to %s", self._session_path)

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
