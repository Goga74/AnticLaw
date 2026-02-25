# Phase 17 — Playwright Scraper for Chat→Project Mapping

**Status:** Design
**Branch:** `feature/phase-17-playwright-scraper`
**Prerequisite:** Phase 2 (Claude import)
**Spec reference:** SPEC.md §27 (Scraper Providers), PLAN.md Phase 17

---

## Problem

Claude.ai's official data export (`conversations.json`) does not contain a
`project_uuid` field that reliably links chats to projects. The result:

- **305+ chats land in `_inbox/`** with no project assignment.
- `projects.json` contains project metadata (name, UUID, description, system
  prompt) but **no list of chats** belonging to each project.
- The `project_uuid` field in `conversations.json` entries is almost always
  empty — Claude's export format simply does not populate it.
- The **only** source of truth for chat→project membership is the claude.ai
  web interface, where each project's sidebar shows its conversations.

### What we already have

The import pipeline (`aw import claude`) already supports a `--mapping` flag:

```bash
aw import claude export.zip --mapping mapping.json
```

If `mapping.json` is provided, chats are routed to the correct project folders
instead of `_inbox/`. The file format is `{"chat_uuid": "project-name", ...}`.

**The missing piece is how to generate `mapping.json`.**

---

## What the Scraper Collects

### Primary: chat→project mapping

For each project visible in the claude.ai sidebar:

| Field | Source | Example |
|-------|--------|---------|
| Project UUID | URL path `/project/{uuid}` | `01234567-abcd-...` |
| Project name | Sidebar label / API response | `"Auth System"` |
| Chat UUIDs | Conversations listed under project | `["aaa-...", "bbb-..."]` |

**Output format** — `mapping.json`:

```json
{
  "aaa11111-2222-3333-4444-555555555555": "Auth System",
  "bbb22222-3333-4444-5555-666666666666": "Auth System",
  "ccc33333-4444-5555-6666-777777777777": "CLI Design",
  "ddd44444-5555-6666-7777-888888888888": "CLI Design"
}
```

Keys are chat UUIDs (matching `remote_id` in frontmatter), values are
human-readable project names (matching what `safe_filename()` produces for
folder names).

### Bonus: project Instructions (system prompt)

If a project has custom Instructions, the scraper saves them. These become
`prompt_template` in `_project.yaml`. The official export includes these in
`projects.json`, but the scraper confirms the data matches.

### Bonus: Knowledge file verification

The export includes Knowledge file contents. The scraper can list Knowledge
file names per project so users can verify nothing was missed.

---

## Technical Approach

### Network interception over DOM parsing

The scraper intercepts network responses (`page.on("response")`) instead of
parsing DOM elements. This is significantly more stable because:

1. **DOM changes frequently** — class names, structure, and selectors change
   with every frontend deploy.
2. **API responses are structured JSON** — predictable schema, versioned
   endpoints.
3. **Less code** — no CSS selectors to maintain.

### Target API endpoints

The claude.ai frontend calls these internal API endpoints (observed via
browser DevTools):

| Endpoint | Method | Returns |
|----------|--------|---------|
| `/api/organizations/{org}/projects` | GET | List of all projects (UUID, name, description) |
| `/api/organizations/{org}/projects/{proj}/docs` | GET | Knowledge files for a project |
| `/api/organizations/{org}/chat_conversations?project_uuid={proj}` | GET | Chats belonging to a project |

The scraper navigates to claude.ai, waits for login, then either:

1. **Passive interception:** Navigates to each project page and captures the
   API responses the frontend naturally makes.
2. **Direct fetch:** Uses the authenticated session to call endpoints directly
   via `page.evaluate()` or `page.request`.

Option 2 is preferred — fewer page loads, faster, less likely to trigger
rate limiting.

### Authentication flow

```
1. Launch Playwright browser (headless=False — visible window)
2. Navigate to https://claude.ai
3. Print "Please log in. Press Enter when ready..."
4. Wait for user to complete login (manual — no credential storage)
5. Verify session by checking for authenticated page elements or API response
6. Proceed with scraping
```

No credentials are ever stored or handled by the scraper. The user logs in
using their normal browser flow (email, Google SSO, etc.).

### Organization ID discovery

Claude.ai scopes everything under an organization. The scraper discovers the
org ID by:

1. Intercepting any API call that contains `/organizations/{uuid}/` in the URL
2. Or calling `/api/auth/current_user` and reading `memberships[0].organization.uuid`

---

## Implementation Plan

### File structure

```
src/anticlaw/providers/scraper/
├── __init__.py
├── base.py              # ScraperProvider Protocol + ScraperInfo
└── claude.py            # ClaudeScraperProvider (Playwright)

src/anticlaw/cli/
└── scrape_cmd.py        # aw scrape claude [--output] [--knowledge]
```

### ScraperProvider Protocol

```python
@runtime_checkable
class ScraperProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def info(self) -> ScraperInfo: ...

    def login(self, browser: Browser) -> bool:
        """Navigate to login, wait for user auth. Returns True on success."""
        ...

    def scrape_projects(self, browser: Browser) -> list[RemoteProject]:
        """List all projects with metadata."""
        ...

    def scrape_chat_mapping(self, browser: Browser) -> dict[str, str]:
        """Return {chat_uuid: project_name} for all projects."""
        ...

    def scrape_knowledge(self, browser: Browser, project_id: str) -> list[Path]:
        """Download Knowledge files for a project."""
        ...
```

### ClaudeScraperProvider — core logic

```python
async def scrape_chat_mapping(self, page: Page) -> dict[str, str]:
    org_id = await self._discover_org_id(page)
    projects = await self._fetch_projects(page, org_id)

    mapping: dict[str, str] = {}
    for project in projects:
        chats = await self._fetch_project_chats(page, org_id, project["uuid"])
        for chat in chats:
            mapping[chat["uuid"]] = project["name"]

        # Rate limiting: small delay between project fetches
        await asyncio.sleep(1.0)

    return mapping
```

### Dependencies

```toml
# pyproject.toml
[project.optional-dependencies]
scraper = ["playwright>=1.40"]
```

After install: `playwright install chromium`

---

## CLI

### `aw scrape claude`

```bash
aw scrape claude [--output mapping.json] [--knowledge] [--home PATH]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--output` | `./mapping.json` | Where to save the mapping file |
| `--knowledge` | off | Also download Knowledge files |
| `--home` | `ACL_HOME` | Override data home |

### Full workflow

```bash
# Step 1: Get your data export from Claude.ai
# Settings > Privacy > Export Data → downloads ZIP

# Step 2: Run the scraper to get project mapping
aw scrape claude --output mapping.json
# → Browser opens, user logs in, scraper collects mapping
# → mapping.json saved (e.g. 305 chats mapped to 12 projects)

# Step 3: Import with mapping
aw import claude claude-export.zip --mapping mapping.json
# → Chats land in correct project folders instead of _inbox/
```

### Re-import scenario

If chats were already imported to `_inbox/`, the user can re-import with the
mapping. The import command skips chats that already exist (by `remote_id`),
so users should either:

1. `aw clear` first, then re-import with mapping, or
2. Use a future `aw reorganize --mapping mapping.json` command (not in scope
   for Phase 17).

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Anthropic changes API endpoints | Medium | Scraper breaks | Version-pin endpoint paths, document how to update |
| Bot detection / Cloudflare challenge | Low | Login blocked | Headed mode (real browser), manual login, no automation of auth |
| Rate limiting | Low | Slow/incomplete | 1-2s delays between requests, respect 429 responses |
| Large number of projects | Low | Slow | Progress bar, allow partial scrape + resume |
| Session expires mid-scrape | Low | Partial data | Save progress incrementally, allow resume |
| Playwright install size (~50 MB) | N/A | User friction | Optional extra (`pip install anticlaw[scraper]`), graceful error if not installed |

### What we will NOT do

- **No credential storage** — user logs in manually every time
- **No headless mode by default** — user must see what's happening
- **No write operations** — scraper is strictly read-only
- **No ongoing sync** — one-time collection, not a persistent connection
- **No DOM parsing** — API interception only

---

## Testing Strategy

- **Unit tests:** Mock Playwright page/response objects, verify mapping JSON
  output format, test org ID extraction from various API responses.
- **Integration test (manual):** Run against real claude.ai account, verify
  mapping matches actual project structure.
- **Edge cases:** Empty projects, projects with 100+ chats, special characters
  in project names, org with single project.

---

## Open Questions

1. **Pagination:** Do the claude.ai API endpoints paginate project chat lists?
   Need to verify with a large project. If yes, the scraper must follow
   `next_page` tokens.
2. **Multiple organizations:** Some users belong to multiple orgs. Should the
   scraper handle org selection or default to the first?
3. **Archived projects:** Does the API return archived projects? Should we
   scrape them?
