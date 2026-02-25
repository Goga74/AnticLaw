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
        self._intercepted_urls: list[str] = []

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
            except Exception:
                # Keep browser open so user can inspect state
                log.error("Scraper error — keeping browser open for 30s for inspection.")
                print("[scraper] Error occurred. Browser stays open for 30s...")
                print(f"[scraper] Current URL: {page.url}")
                time.sleep(30)
                page.context.browser.close()
                raise
            else:
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
        self._install_response_interceptor(page)

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
            self._post_login_debug(page)
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
        self._install_response_interceptor(page)

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

        self._post_login_debug(page)

        return page

    def _save_session(self, context) -> None:
        """Persist browser session state to disk."""
        self._session_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(self._session_path))
        log.info("Session saved to %s", self._session_path)

    def _install_response_interceptor(self, page) -> None:
        """Install a response handler that records all API URLs."""

        def _on_response(response):
            url = response.url
            if "/api/" in url:
                self._intercepted_urls.append(url)

        page.on("response", _on_response)

    def _post_login_debug(self, page) -> None:
        """Wait for network idle after login and print debug info."""
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            print("[scraper] Warning: networkidle timeout (page may still be loading)")

        print(f"[scraper] Current URL: {page.url}")
        if self._intercepted_urls:
            print(f"[scraper] Intercepted {len(self._intercepted_urls)} API responses:")
            for url in self._intercepted_urls:
                print(f"  {url}")
        else:
            print("[scraper] No API responses intercepted yet.")

    def _discover_org_id(self, page) -> None:
        """Discover organization ID using multiple methods.

        Tries three approaches in order:
        1. Scan intercepted response URLs for /api/organizations/{uuid}/
        2. Direct fetch of /api/auth/current_user
        3. Extract from page JS context (__NEXT_DATA__ or body text)
        """
        if self._org_id:
            return

        # Method 1: scan intercepted URLs
        print("[scraper] Method 1: scanning intercepted URLs for org ID...")
        for url in self._intercepted_urls:
            match = _ORG_PATTERN.search(url)
            if match:
                self._org_id = match.group(1)
                print(f"[scraper] Found org ID in intercepted URL: {self._org_id}")
                log.info("Organization ID (from intercepted URL): %s", self._org_id)
                return

        print(f"[scraper] No org ID in {len(self._intercepted_urls)} intercepted URLs.")

        # Method 2: direct API fetch
        print("[scraper] Method 2: fetching /api/auth/current_user...")
        try:
            response = page.request.get("https://claude.ai/api/auth/current_user")
            print(f"[scraper] Response status: {response.status}")

            if response.ok:
                try:
                    data = response.json()
                except Exception as exc:
                    body_text = response.text()
                    print(f"[scraper] Response is not JSON: {body_text[:500]}")
                    log.warning("current_user response not JSON: %s", exc)
                    data = {}

                print(f"[scraper] Response keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")

                memberships = data.get("memberships", []) if isinstance(data, dict) else []
                if memberships:
                    print(f"[scraper] Found {len(memberships)} membership(s)")
                    org = memberships[0].get("organization", {})
                    self._org_id = org.get("uuid", "")
                    if self._org_id:
                        print(f"[scraper] Found org ID: {self._org_id}")
                        log.info("Organization ID (from API): %s", self._org_id)
                        return
                    print(f"[scraper] Organization object: {org}")
                else:
                    # Print account_uuid or other identifiers if present
                    for key in ("uuid", "id", "account", "account_uuid"):
                        if key in data:
                            print(f"[scraper] data['{key}'] = {data[key]}")
            else:
                body_text = response.text()
                print(f"[scraper] HTTP {response.status}: {body_text[:500]}")
        except Exception as exc:
            print(f"[scraper] API fetch failed: {exc}")

        # Method 3: page JS context
        print("[scraper] Method 3: checking page JS context...")
        try:
            js_data = page.evaluate(
                "() => { try { return JSON.stringify(window.__NEXT_DATA__); } catch(e) { return null; } }"
            )
            if js_data:
                print(f"[scraper] __NEXT_DATA__ (first 500 chars): {js_data[:500]}")
                match = _ORG_PATTERN.search(js_data)
                if match:
                    self._org_id = match.group(1)
                    print(f"[scraper] Found org ID in __NEXT_DATA__: {self._org_id}")
                    log.info("Organization ID (from JS): %s", self._org_id)
                    return
            else:
                print("[scraper] __NEXT_DATA__ is empty/null")
        except Exception as exc:
            print(f"[scraper] JS evaluation failed: {exc}")

        # Try body text as last resort
        try:
            body_snippet = page.evaluate(
                "() => document.body ? document.body.innerText.substring(0, 1000) : ''"
            )
            if body_snippet:
                print(f"[scraper] Page body (first 500 chars): {body_snippet[:500]}")
                match = _ORG_PATTERN.search(body_snippet)
                if match:
                    self._org_id = match.group(1)
                    print(f"[scraper] Found org ID in page body: {self._org_id}")
                    log.info("Organization ID (from page body): %s", self._org_id)
                    return
        except Exception as exc:
            print(f"[scraper] Body text extraction failed: {exc}")

        # All methods exhausted
        print("[scraper] All 3 methods failed to discover org ID.")
        raise RuntimeError(
            "Could not discover organization ID. "
            "Make sure you are logged into claude.ai."
        )

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
