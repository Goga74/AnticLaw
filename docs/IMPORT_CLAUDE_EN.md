# Importing Claude Chats into AnticLaw

## Prerequisites
- AnticLaw installed: `pip install anticlaw` or `pip install -e .`
- Chrome browser with claude.ai logged in
- Chrome started with remote debugging (for project mapping)

---

## Step 1: Export your Claude data

1. Open [claude.ai](https://claude.ai) → click your avatar (bottom left) → **Settings**
2. Go to **Privacy** → **Export Data**
3. Click **Export Data** button
4. Wait for email from Anthropic with download link (usually 1–5 minutes)
5. Download the ZIP file, e.g. `data-2026-02-17-15-09-31-batch-0000.zip`
6. Optionally unzip it — both ZIP and folder are supported

---

## Step 2: Initialize AnticLaw (first time only)

```bash
aw init --home C:\AnticlawData        # Windows
aw init --home ~/anticlaw             # Mac/Linux
```

---

## Step 3: Import without project mapping (quick)

If you don't care about project assignment — all chats go to `_inbox/`:

```bash
# Windows
aw import claude C:\Downloads\data-2026-02-17-batch-0000.zip --home C:\AnticlawData

# Mac/Linux
aw import claude ~/Downloads/data-2026-02-17-batch-0000.zip --home ~/anticlaw
```

---

## Step 4: Generate project mapping (recommended)

Claude's export does **not** include chat→project assignments. To route chats to correct
project folders, run the scraper.

**4a. Start Chrome with remote debugging:**

```bash
# Windows (find your Chrome path first)
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222

# Mac
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# Linux
google-chrome --remote-debugging-port=9222
```

**4b. Log in to claude.ai** in that Chrome window (if not already logged in).

**4c. Run the scraper:**

```bash
# Windows
aw scrape claude --cdp-url http://localhost:9222 --output C:\AnticlawData\mapping.json --home C:\AnticlawData

# Mac/Linux
aw scrape claude --cdp-url http://localhost:9222 --output ~/anticlaw/mapping.json --home ~/anticlaw
```

The scraper automatically fetches all your chats and their project assignments. Takes 10–30 seconds.

---

## Step 5: Import with project mapping

```bash
# Windows
aw import claude C:\Downloads\data-2026-02-17-batch-0000.zip --mapping C:\AnticlawData\mapping.json --home C:\AnticlawData

# Mac/Linux
aw import claude ~/Downloads/data-2026-02-17-batch-0000.zip --mapping ~/anticlaw/mapping.json --home ~/anticlaw
```

---

## Step 6: Verify

```bash
aw list --home C:\AnticlawData        # show all projects
aw search "your query" --home C:\AnticlawData
```

---

## Notes

- Chats without a project in Claude go to `_inbox/` — this is expected
- Re-running import is safe: already imported chats are skipped
- The scraper only reads data, it does not modify anything in Claude
- `mapping.json` can be reused for future imports until your project structure changes
