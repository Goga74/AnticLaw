"""Claude.ai Playwright scraper — automated response interception via CDP.

Connects to an already-running Chrome instance via CDP, registers a response
interceptor, navigates to claude.ai to discover org_id and project list from
intercepted API responses, then navigates to each project page to capture
conversations_v2 responses and build a chat→project mapping.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from anticlaw.core.fileutil import safe_filename

from .base import ScrapedMapping, ScraperInfo

log = logging.getLogger(__name__)

BASE_URL = "https://claude.ai"

# Regex patterns for intercepted API URLs
_RE_ORG_ID = re.compile(r"/api/organizations/([a-f0-9-]{36})/")
_RE_PROJECTS = re.compile(r"/api/organizations/[^/]+/projects")
_RE_CONVERSATIONS = re.compile(
    r"/projects/([^/]+)/conversations_v2"
)


class ClaudeScraper:
    """Scrape chat→project mapping from Claude.ai via Playwright CDP interception."""

    def __init__(self, cdp_url: str = "http://localhost:9222") -> None:
        self._cdp_url = cdp_url
        self._org_id: str | None = None
        self._projects: dict[str, dict] = {}  # {uuid: {name, instructions, is_starter}}
        self._chat_to_project: dict[str, str] = {}  # {chat_uuid: project_uuid}

    @property
    def name(self) -> str:
        return "claude-scraper"

    @property
    def info(self) -> ScraperInfo:
        return ScraperInfo(
            display_name="Claude.ai Playwright Scraper",
            base_url=BASE_URL,
            capabilities={"projects", "chat_mapping"},
        )

    def _handle_response(self, response: object) -> None:
        """Response interceptor — captures org_id, projects, and conversations."""
        url = response.url  # type: ignore[attr-defined]

        # Debug: log all conversation-related URLs
        if "conversation" in url.lower():
            print(f"DEBUG captured: {url}")

        # Try to discover org_id from any API URL
        if not self._org_id:
            m = _RE_ORG_ID.search(url)
            if m:
                self._org_id = m.group(1)
                log.info("Discovered org_id: %s", self._org_id)

        # Match conversation responses FIRST — conversations_v2 URLs
        # also match _RE_PROJECTS (both contain "/projects/") so we
        # must check the more specific pattern before the general one.
        m = _RE_CONVERSATIONS.search(url)
        if m:
            project_uuid = m.group(1)
            self._handle_conversations_response(response, project_uuid)
            return

        # Match project list responses
        if _RE_PROJECTS.search(url):
            self._handle_projects_response(response)
            return

    def _handle_projects_response(self, response: object) -> None:
        """Extract project list from intercepted response."""
        try:
            body = response.json()  # type: ignore[attr-defined]
        except Exception:
            log.debug("Could not parse projects response as JSON")
            return

        if not isinstance(body, list):
            return

        for proj in body:
            uuid = proj.get("uuid", "")
            if not uuid:
                continue
            is_starter = proj.get("is_starter_project", False)
            self._projects[uuid] = {
                "name": proj.get("name", "Untitled"),
                "instructions": proj.get("prompt_template", "") or "",
                "is_starter": is_starter,
            }

        log.info(
            "Intercepted %d projects (total %d tracked)",
            len(body),
            len(self._projects),
        )

    def _handle_conversations_response(
        self, response: object, project_uuid: str
    ) -> None:
        """Extract chat UUIDs from intercepted conversation response."""
        try:
            body = response.json()  # type: ignore[attr-defined]
        except Exception:
            log.debug("Could not parse conversations response as JSON")
            return

        chats: list[dict] = []
        if isinstance(body, list):
            chats = body
        elif isinstance(body, dict):
            chats = body.get("data", body.get("chats", []))
            if not isinstance(chats, list):
                chats = []

        count = 0
        for chat in chats:
            chat_uuid = chat.get("uuid", "")
            if chat_uuid:
                self._chat_to_project[chat_uuid] = project_uuid
                count += 1

        log.info(
            "Intercepted %d chats for project %s",
            count,
            project_uuid,
        )

    def _build_mapping(self) -> ScrapedMapping:
        """Build ScrapedMapping from captured data, skipping starter projects."""
        chat_mapping: dict[str, str] = {}
        project_metadata: dict[str, dict] = {}

        # Filter out starter projects
        real_projects = {
            uuid: info
            for uuid, info in self._projects.items()
            if not info.get("is_starter", False)
        }

        for proj_uuid, info in real_projects.items():
            folder_name = safe_filename(info["name"])
            project_metadata[proj_uuid] = {
                "name": info["name"],
                "instructions": info["instructions"],
            }

            # Map chats that belong to this project
            for chat_uuid, mapped_proj in self._chat_to_project.items():
                if mapped_proj == proj_uuid:
                    chat_mapping[chat_uuid] = folder_name

        return ScrapedMapping(
            chats=chat_mapping,
            projects=project_metadata,
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )

    def _start_playwright(self) -> object:
        """Import and start Playwright. Returns the Playwright instance."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ImportError(
                "playwright is required for the Claude scraper. "
                "Install it with: pip install anticlaw[scraper] "
                "&& playwright install chromium"
            ) from exc
        return sync_playwright().start()

    def scrape(self, output: Path) -> ScrapedMapping:
        """Connect to Chrome, auto-navigate projects, save mapping.

        Requires Chrome to be running with --remote-debugging-port=9222
        and logged in to claude.ai.
        """
        pw = self._start_playwright()
        try:
            browser = pw.chromium.connect_over_cdp(self._cdp_url)
            contexts = browser.contexts
            if not contexts:
                raise RuntimeError(
                    "No browser contexts found. Is Chrome running with "
                    "--remote-debugging-port=9222 and a claude.ai tab open?"
                )

            context = contexts[0]
            pages = context.pages

            # Find an existing claude.ai tab or use the first page
            page = None
            for p in pages:
                if "claude.ai" in p.url:
                    page = p
                    break
            if page is None:
                page = pages[0] if pages else context.new_page()

            # Register response interceptor BEFORE any navigation
            page.on("response", self._handle_response)

            # Navigate to claude.ai — triggers API requests that the
            # interceptor captures for org_id and project list discovery
            page.goto("https://claude.ai")
            page.wait_for_load_state("networkidle")

            # Verify org_id was discovered from intercepted URLs
            if not self._org_id:
                raise RuntimeError(
                    "Could not discover org ID from intercepted "
                    "responses. Is the Chrome session logged in to "
                    "claude.ai?"
                )

            # Projects should have been captured by the interceptor
            if not self._projects:
                raise RuntimeError(
                    "No projects found in intercepted responses."
                )

            # Navigate to each non-starter project to trigger
            # conversations_v2 responses
            real_projects = [
                (uuid, info)
                for uuid, info in self._projects.items()
                if not info.get("is_starter", False)
            ]

            total = len(real_projects)
            for i, (proj_uuid, info) in enumerate(real_projects, 1):
                print(
                    f"Loading project {i}/{total}: {info['name']}..."
                )
                page.goto(f"https://claude.ai/project/{proj_uuid}")
                try:
                    page.wait_for_response(
                        lambda r, pid=proj_uuid: (
                            f"projects/{pid}" in r.url
                        ),
                        timeout=10000,
                    )
                except Exception:
                    print(
                        f"  Warning: no conversations response "
                        f"for {info['name']}"
                    )

            # Build mapping from intercepted conversation responses
            mapping = self._build_mapping()

            # Save to file
            output.parent.mkdir(parents=True, exist_ok=True)
            mapping_dict = {
                "chats": mapping.chats,
                "projects": mapping.projects,
                "scraped_at": mapping.scraped_at,
            }
            output.write_text(
                json.dumps(mapping_dict, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            log.info(
                "Saved mapping: %d chats across %d projects → %s",
                len(mapping.chats),
                len(mapping.projects),
                output,
            )
            return mapping

        finally:
            pw.stop()
