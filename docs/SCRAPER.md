# Scraper: Playwright Response Interception

## Overview

Phase 17 implements chat→project mapping by connecting to an already-running
Chrome instance via CDP (Chrome DevTools Protocol) and intercepting API
responses as the user browses their Claude.ai projects.

**How it works:**
1. Chrome runs with `--remote-debugging-port=9222`
2. Playwright connects via CDP — reuses the existing session (no login needed)
3. A response interceptor captures project and conversation API responses
4. The user clicks through their projects in Claude
5. When done, the mapping is built from captured data and saved

## Prerequisites

Start Chrome with remote debugging enabled:

```bash
# Windows
chrome.exe --remote-debugging-port=9222

# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# Linux
google-chrome --remote-debugging-port=9222
```

Then log in to [claude.ai](https://claude.ai) in that Chrome instance.

## API Responses Intercepted

The scraper captures responses matching these URL patterns:

| Pattern | Purpose |
|---------|---------|
| `/api/organizations/*/projects*` | Project list (uuid, name, is_starter_project) |
| `/projects/*/conversations_v2*` | Chat list per project (uuid extracted from URL + response body) |

Starter projects (`is_starter_project: true`) are automatically excluded.

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
# Start Chrome with debugging, then:
aw scrape claude

# Custom CDP URL
aw scrape claude --cdp-url http://localhost:9333

# Custom output path
aw scrape claude -o my-mapping.json

# Then use mapping during import
aw import claude export.zip --mapping mapping.json
```

## Integration with Import

The `aw import claude` command accepts `--mapping` to route chats to correct
project folders. The mapping file is compatible with both:

- **New format** (from Playwright scraper): `{"chats": {...}, "projects": {...}}`
- **Legacy format**: `{"chat-uuid": "project-name", ...}` (flat dict)

## Dependencies

Requires `playwright` (included in `scraper` extra):

```bash
pip install anticlaw[scraper]
playwright install chromium
```

## Security Notes

- No credentials are passed — the scraper reuses your existing Chrome session
- All interception is read-only (response capture only)
- No data is modified on Claude.ai
- Chrome must be started with `--remote-debugging-port` by the user
