# Scraper: HTTP API Approach

## Overview

Phase 17 implements chat→project mapping by calling Claude.ai's internal HTTP API
directly with `httpx`, instead of automating a browser with Playwright.

**Advantages over Playwright:**
- No ~50 MB browser binary download
- Faster execution (seconds vs minutes)
- No headed/headless browser management
- Reuses `httpx` already required by `sync` and `semantic` extras

## Authentication

The scraper authenticates using a session cookie from your browser.

### How to get your session key

1. Open [claude.ai](https://claude.ai) in your browser and log in
2. Open DevTools (`F12`)
3. Go to **Application** tab → **Cookies** → `claude.ai`
4. Find the cookie named `sessionKey`
5. Copy its value (starts with `sk-ant-sid01-...`)

## API Endpoints Used

All requests go to `https://claude.ai` with the `sessionKey` cookie.

| # | Method | Endpoint | Purpose |
|---|--------|----------|---------|
| 1 | GET | `/api/auth/current_user` | Get organization UUID |
| 2 | GET | `/api/organizations/{org_id}/projects` | List all projects |
| 3 | GET | `/api/organizations/{org_id}/chat_conversations?project_uuid={id}&limit=100` | List chats in a project |

Pagination: endpoint #3 may return `next_page_token` for projects with 100+ chats.

## Output Format

The scraper produces a `mapping.json` file:

```json
{
  "chats": {
    "chat-uuid-1": "project-folder-name",
    "chat-uuid-2": "project-folder-name"
  },
  "projects": {
    "project-uuid-1": {
      "name": "My Project",
      "instructions": "You are a helpful assistant..."
    }
  },
  "scraped_at": "2026-02-26T12:00:00+00:00"
}
```

- `chats`: maps each chat UUID to its project folder name (safe filename slug)
- `projects`: maps each project UUID to its name and instructions (prompt_template)
- `scraped_at`: ISO timestamp of when the scrape was performed

## CLI Usage

```bash
# Scrape and save mapping
aw scrape claude --session-key "sk-ant-sid01-..."

# Custom output path
aw scrape claude --session-key "sk-ant-sid01-..." -o my-mapping.json

# Then use mapping during import
aw import claude export.zip --mapping mapping.json
```

## Integration with Import

The `aw import claude` command accepts `--mapping` to route chats to correct
project folders. The mapping file is compatible with both:

- **New format** (from HTTP scraper): `{"chats": {...}, "projects": {...}}`
- **Legacy format**: `{"chat-uuid": "project-name", ...}` (flat dict)

## Dependencies

Requires `httpx` (included in `scraper` extra):

```bash
pip install anticlaw[scraper]
```

Since `httpx` is also used by `sync` and `semantic` extras, it may already
be installed.

## Security Notes

- The session key is passed via CLI option (not stored)
- All requests are read-only (GET only)
- No data is modified on Claude.ai
- Session keys expire; get a fresh one if you get auth errors
