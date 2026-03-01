"""Claude.ai Playwright scraper — paginated chat_conversations fetch.

Connects to Chrome via CDP, navigates to claude.ai, discovers org_id
from intercepted API responses, then uses page.evaluate() with
offset-based pagination to fetch ALL chats (starred + unstarred).
Each chat object contains a project field with uuid and name, so a
single session captures the full chat→project mapping.
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

_RE_ORG_ID = re.compile(r"/api/organizations/([a-f0-9-]{36})/")

# JavaScript for offset-based pagination of chat_conversations.
# Accepts [orgId, starred] array. Returns all chats across pages.
_JS_FETCH_CHATS = """
async (args) => {
    const [orgId, starred] = args;
    const chats = [];
    let offset = 0;
    const limit = 50;
    while (true) {
        const url = `/api/organizations/${orgId}`
            + `/chat_conversations`
            + `?limit=${limit}&offset=${offset}`
            + `&starred=${starred}`
            + `&consistency=eventual`;
        const r = await fetch(url);
        const data = await r.json();
        if (!Array.isArray(data) || data.length === 0) break;
        chats.push(...data);
        if (data.length < limit) break;
        offset += limit;
    }
    return chats;
}
"""


class ClaudeScraper:
    """Scrape chat→project mapping from Claude.ai via CDP."""

    def __init__(
        self, cdp_url: str = "http://localhost:9222"
    ) -> None:
        self._cdp_url = cdp_url
        self._org_id: str | None = None
        self._chats: dict[str, dict] = {}
        self._projects: dict[str, dict] = {}

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
        """Intercept org_id from any API response."""
        url = response.url  # type: ignore[attr-defined]

        if not self._org_id:
            m = _RE_ORG_ID.search(url)
            if m:
                self._org_id = m.group(1)
                log.info("Discovered org_id: %s", self._org_id)

    def _process_chats(self, chats: list[dict]) -> int:
        """Store chat objects and extract project info.

        Returns count of chats added.
        """
        count = 0
        for chat in chats:
            chat_uuid = chat.get("uuid", "")
            if not chat_uuid:
                continue
            self._chats[chat_uuid] = chat
            count += 1

            project = chat.get("project")
            if not isinstance(project, dict):
                continue
            proj_uuid = project.get("uuid", "")
            if proj_uuid and proj_uuid not in self._projects:
                self._projects[proj_uuid] = {
                    "name": project.get("name", "Untitled"),
                }

        log.info(
            "Processed %d chats (total %d)",
            count,
            len(self._chats),
        )
        return count

    def _fetch_all_chats(self, page: object) -> None:
        """Fetch all chats via paginated evaluate calls."""
        for starred in (True, False):
            label = "starred" if starred else "unstarred"
            log.info("Fetching %s chats...", label)
            result = page.evaluate(  # type: ignore[attr-defined]
                _JS_FETCH_CHATS, [self._org_id, starred]
            )
            if not isinstance(result, list):
                result = []
            added = self._process_chats(result)
            log.info(
                "Fetched %d %s chats (total %d)",
                added,
                label,
                len(self._chats),
            )

    def _build_mapping(self) -> ScrapedMapping:
        """Build mapping from captured chats."""
        chat_mapping: dict[str, str] = {}

        for chat_uuid, chat in self._chats.items():
            project = chat.get("project")
            if not isinstance(project, dict):
                continue
            proj_uuid = project.get("uuid", "")
            if not proj_uuid:
                continue
            proj_name = project.get("name", "Untitled")
            chat_mapping[chat_uuid] = safe_filename(proj_name)

        project_metadata: dict[str, dict] = {}
        for proj_uuid, info in self._projects.items():
            project_metadata[proj_uuid] = {
                "name": info["name"],
                "instructions": "",
            }

        return ScrapedMapping(
            chats=chat_mapping,
            projects=project_metadata,
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )

    def _start_playwright(self) -> object:
        """Import and start Playwright."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ImportError(
                "playwright is required for the Claude "
                "scraper. Install it with: "
                "pip install anticlaw[scraper] "
                "&& playwright install chromium"
            ) from exc
        return sync_playwright().start()

    def scrape(self, output: Path) -> ScrapedMapping:
        """Load claude.ai, fetch all chats via pagination."""
        pw = self._start_playwright()
        try:
            browser = pw.chromium.connect_over_cdp(
                self._cdp_url
            )
            contexts = browser.contexts
            if not contexts:
                raise RuntimeError(
                    "No browser contexts found. Is Chrome "
                    "running with "
                    "--remote-debugging-port=9222?"
                )

            context = contexts[0]
            pages = context.pages

            page = None
            for p in pages:
                if "claude.ai" in p.url:
                    page = p
                    break
            if page is None:
                page = (
                    pages[0] if pages else context.new_page()
                )

            page.on("response", self._handle_response)

            page.goto("https://claude.ai")
            page.wait_for_load_state("networkidle")

            if not self._org_id:
                raise RuntimeError(
                    "Could not discover org ID. "
                    "Is Chrome logged in to claude.ai?"
                )

            # Fetch ALL chats with offset-based pagination
            self._fetch_all_chats(page)

            if not self._chats:
                raise RuntimeError(
                    "No chats fetched from "
                    "chat_conversations API."
                )

            mapping = self._build_mapping()

            print(
                f"Captured {len(self._chats)} chats, "
                f"{len(self._projects)} projects."
            )
            print(
                f"Mapped {len(mapping.chats)} chats to "
                f"{len(mapping.projects)} projects."
            )

            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(
                    {
                        "chats": mapping.chats,
                        "projects": mapping.projects,
                        "scraped_at": mapping.scraped_at,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            log.info(
                "Saved mapping: %d chats, %d projects",
                len(mapping.chats),
                len(mapping.projects),
            )
            return mapping

        finally:
            pw.stop()
