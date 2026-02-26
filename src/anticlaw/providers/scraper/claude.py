"""Claude.ai HTTP scraper — direct API calls via httpx.

Uses session cookie authentication to fetch chat→project mapping
from the Claude.ai API without needing a browser.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from anticlaw.core.fileutil import safe_filename

from .base import ScrapedMapping, ScraperInfo

if TYPE_CHECKING:
    import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://claude.ai"
_HEADERS = {
    "User-Agent": "AnticLaw/1.0",
    "Accept": "application/json",
}


class ClaudeScraper:
    """Scrape chat→project mapping from Claude.ai via HTTP API."""

    def __init__(self, session_key: str) -> None:
        self._session_key = session_key
        self._org_id: str = ""

    @property
    def name(self) -> str:
        return "claude-scraper"

    @property
    def info(self) -> ScraperInfo:
        return ScraperInfo(
            display_name="Claude.ai HTTP Scraper",
            base_url=BASE_URL,
            capabilities={"projects", "chat_mapping", "instructions"},
        )

    def _make_client(self) -> httpx.Client:
        """Create an httpx client with session cookie auth."""
        try:
            import httpx
        except ImportError as exc:
            raise ImportError(
                "httpx is required for the Claude scraper. "
                "Install it with: pip install anticlaw[scraper]"
            ) from exc
        return httpx.Client(
            base_url=BASE_URL,
            cookies={"sessionKey": self._session_key},
            headers=_HEADERS,
            timeout=30.0,
            follow_redirects=True,
        )

    def _get_org_id(self, client: httpx.Client) -> str:
        """GET /api/auth/current_user → extract org_id."""
        resp = client.get("/api/auth/current_user")
        resp.raise_for_status()
        data = resp.json()

        orgs = data.get("account", {}).get("memberships", [])
        if not orgs:
            raise ValueError(
                "No organizations found. Is the session key valid? "
                "Make sure you copied the full sessionKey value from browser cookies."
            )

        org_id = orgs[0].get("organization", {}).get("uuid", "")
        if not org_id:
            raise ValueError("Could not extract organization UUID from user data.")

        log.info("Found org_id: %s", org_id)
        return org_id

    def _get_projects(self, client: httpx.Client) -> list[dict]:
        """GET /api/organizations/{org_id}/projects → list of projects.

        Skips starter projects (is_starter_project=true).
        """
        resp = client.get(f"/api/organizations/{self._org_id}/projects")
        resp.raise_for_status()
        projects = resp.json()

        if not isinstance(projects, list):
            raise ValueError(f"Expected list of projects, got {type(projects).__name__}")

        # Filter out starter projects
        result = [p for p in projects if not p.get("is_starter_project", False)]
        log.info("Found %d projects (excluding starter projects)", len(result))
        return result

    def _get_project_chats(self, client: httpx.Client, project_uuid: str) -> list[dict]:
        """GET /api/organizations/{org_id}/chat_conversations?project_uuid=...

        Handles pagination via next_page_token.
        """
        all_chats: list[dict] = []
        url = (
            f"/api/organizations/{self._org_id}/chat_conversations"
            f"?project_uuid={project_uuid}&limit=100"
        )

        while url:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

            # Response may be a list directly or a dict with pagination
            if isinstance(data, list):
                all_chats.extend(data)
                break
            elif isinstance(data, dict):
                chats = data.get("chats", data.get("data", []))
                if isinstance(chats, list):
                    all_chats.extend(chats)

                # Check for pagination
                next_token = data.get("next_page_token")
                if next_token:
                    url = (
                        f"/api/organizations/{self._org_id}/chat_conversations"
                        f"?project_uuid={project_uuid}&limit=100"
                        f"&next_page_token={next_token}"
                    )
                else:
                    break
            else:
                break

        return all_chats

    def scrape(self, output: Path) -> ScrapedMapping:
        """Run the full scrape and save mapping.json to output path."""
        client = self._make_client()

        try:
            # Step 1: Get org ID
            self._org_id = self._get_org_id(client)

            # Step 2: Get all projects
            projects = self._get_projects(client)

            # Step 3: For each project, get chats and build mapping
            chat_mapping: dict[str, str] = {}
            project_metadata: dict[str, dict] = {}

            for proj in projects:
                proj_uuid = proj.get("uuid", "")
                proj_name = proj.get("name", "Untitled")
                folder_name = safe_filename(proj_name)
                instructions = proj.get("prompt_template", "") or ""

                if not proj_uuid:
                    continue

                project_metadata[proj_uuid] = {
                    "name": proj_name,
                    "instructions": instructions,
                }

                # Fetch chats for this project
                chats = self._get_project_chats(client, proj_uuid)
                log.info("Project %r: %d chats", proj_name, len(chats))

                for chat in chats:
                    chat_uuid = chat.get("uuid", "")
                    if chat_uuid:
                        chat_mapping[chat_uuid] = folder_name

            # Build result
            mapping = ScrapedMapping(
                chats=chat_mapping,
                projects=project_metadata,
                scraped_at=datetime.now(timezone.utc).isoformat(),
            )

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
                len(chat_mapping),
                len(project_metadata),
                output,
            )
            return mapping

        finally:
            client.close()
