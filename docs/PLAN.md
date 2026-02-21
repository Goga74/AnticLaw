# AnticLaw — Implementation Plan

**Date:** 2025-02-20  
**Companion to:** SPEC.md

---

## Architecture with Daemon

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Layer                               │
│  ┌──────┐  ┌──────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │  CLI │  │  TUI │  │  System Tray │  │  MCP Clients       │ │
│  │ (aw) │  │(v2.0)│  │  (aw-tray)   │  │  Claude/Cursor/... │ │
│  └──┬───┘  └──┬───┘  └──────┬───────┘  └────────┬───────────┘ │
│     │         │              │                    │             │
├─────┴─────────┴──────────────┴────────────────────┴─────────────┤
│                      Core Library                               │
│  anticlaw.core   — models, storage, index, graph, search       │
│  anticlaw.mcp    — MCP server (FastMCP, stdio)                 │
│  anticlaw.llm    — Ollama summarizer, tagger, Q&A              │
├─────────────────────────────────────────────────────────────────┤
│                      Daemon (aw-daemon)                         │
│  ┌──────────────┐ ┌────────────┐ ┌────────────┐ ┌───────────┐ │
│  │  File Watcher│ │  Scheduler │ │  Sync      │ │  Backup   │ │
│  │  (watchdog)  │ │  (APSched) │ │  Engine    │ │  Engine   │ │
│  └──────┬───────┘ └─────┬──────┘ └─────┬──────┘ └─────┬─────┘ │
│         │               │              │               │       │
│         ▼               ▼              ▼               ▼       │
│  On file change:   Periodic:      On trigger:     On schedule: │
│  - reindex         - auto-backup  - cloud sync    - GDrive     │
│  - update graph    - retention    - create proj   - S3         │
│  - recalc embeds   - health check - push chats    - local copy │
├─────────────────────────────────────────────────────────────────┤
│                      Storage Layer                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │File System│  │  SQLite  │  │ ChromaDB │  │System Keyring │  │
│  │  (truth) │  │meta+graph│  │ (vectors)│  │  (secrets)    │  │
│  └──────────┘  └──────────┘  └──────────┘  └───────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Daemon Details

### What it does

| Event | Daemon Reaction | Configurable? |
|-------|----------------|--------------|
| New .md file in project folder | Auto-index, extract entities, compute embeddings | Yes: `watch.auto_index: true` |
| .md file modified | Re-index, update graph edges | Yes |
| New folder created in ACL_HOME | Offer to register as project (notification) | Yes: `watch.auto_project: ask/auto/off` |
| Folder deleted | Mark project as archived (never auto-delete from cloud) | Yes |
| File moved between folders | Update project membership | Always |
| Scheduled: every N hours | Backup to GDrive / S3 / local path | Yes: `backup.schedule` |
| Scheduled: daily | Retention lifecycle (archive/purge) | Yes: `retention.auto_run` |
| Scheduled: daily | Health check (orphans, missing meta) | Yes |
| On demand (from tray) | Force sync with cloud provider | Manual trigger |
| On demand (from tray) | Open ACL_HOME in file manager | Manual trigger |

### Tech stack for daemon

| Component | Library | Why |
|-----------|---------|-----|
| File watching | `watchdog` | Cross-platform (Win/Mac/Linux), mature, stable |
| Scheduler | `APScheduler` | Cron-like scheduling in Python, lightweight |
| System tray (Windows) | `pystray` + `Pillow` | Native tray icon, menu, notifications |
| System tray (macOS) | `pystray` + `rumps` | Native menu bar integration |
| System tray (Linux) | `pystray` | AppIndicator / StatusNotifier |
| Notifications | `plyer` | Cross-platform desktop notifications |
| IPC (CLI ↔ Daemon) | Unix socket / Named pipe (Win) | CLI sends commands to running daemon |
| Process management | `python-daemon` (Linux) / Windows Service / launchd (macOS) | Auto-start on boot |
| Backup: Google Drive | `google-api-python-client` | Official SDK |
| Backup: S3 | `boto3` | Official SDK |
| Backup: local | `shutil` / `rsync` wrapper | Simple copy |

### Daemon config (in config.yaml)

```yaml
daemon:
  enabled: true
  autostart: true                    # register as system service on install
  pid_file: ~/.acl/daemon.pid
  log_file: ~/.acl/daemon.log
  log_level: info

  watch:
    enabled: true
    auto_index: true                 # re-index on file change
    auto_project: ask                # ask | auto | off — when new folder appears
    debounce_seconds: 2              # wait for writes to settle before processing
    ignore_patterns:
      - "*.tmp"
      - "*.swp"
      - ".git/*"

  backup:
    enabled: false
    schedule: "0 3 * * *"           # cron: daily at 3 AM
    targets:
      - type: gdrive
        folder_id: "1abc..."
        credential: keyring
      - type: local
        path: /mnt/backup/anticlaw
      # - type: s3
      #   bucket: my-anticlaw-backup
      #   credential: keyring

  sync:
    enabled: false
    auto_push: false                 # auto-push new local projects to cloud
    auto_pull: false                 # auto-pull new cloud chats to local
    providers: [claude]
    schedule: "0 */6 * * *"         # every 6 hours

  retention:
    auto_run: true
    schedule: "0 4 * * *"           # daily at 4 AM

  tray:
    enabled: true                    # show system tray icon
    show_notifications: true
```

---

## Step-by-Step Implementation Plan

### Phase 0: Project Scaffolding (Day 1) ✅

```
Goal: Empty project that installs, runs, and has CI.
```

- [x] Create git repo `anticlaw`
- [x] `pyproject.toml` with metadata, dependencies, extras (`[search]`, `[fuzzy]`, `[semantic]`, `[all]`, `[daemon]`, `[scraper]`, `[llm]`, `[backup]`, `[dev]`)
- [x] Project structure (src/anticlaw/ with core/, mcp/, providers/{llm,backup,embedding}/, llm/, daemon/, cli/)
- [x] `pip install -e .` works
- [x] `aw --version` prints version
- [ ] GitHub Actions: lint (ruff) + test (pytest)
- [ ] Pre-commit hooks: ruff, basic checks

**Deliverable:** `aw --version` → `anticlaw 0.1.0-dev` ✅

---

### Phase 1: Core Models + Storage (Days 2–3) ✅

```
Goal: Read and write chat files with YAML frontmatter.
```

**Files:**

`src/anticlaw/core/models.py`:
- [x] `ChatMessage` dataclass: role (human/assistant), content, timestamp
- [x] `Chat` dataclass: id, title, created, updated, provider, remote_id, remote_project_id, model, tags, summary, token_count, message_count, importance, status, messages
- [x] `Project` dataclass: name, description, created, updated, tags, status, providers: dict, settings: dict
- [x] `Insight` dataclass: id, content, category, importance, tags, project_id, chat_id, created, updated, status
- [x] `Edge` dataclass: id, source_id, target_id, edge_type, weight, metadata, created
- [x] Provider models: `RemoteProject`, `RemoteChat`, `ChatData`, `SyncResult`
- [x] Enums: `Status`, `Importance`, `InsightCategory`, `EdgeType`

> **Divergence from original plan:** Project field renamed from `provider_mappings` → `providers` (matches _project.yaml key). Chat has additional fields: `remote_project_id`, `model`, `token_count`, `message_count`. Edge and provider models added here (spec had them in providers/base.py) to keep core models centralized.

`src/anticlaw/core/storage.py`:
- [x] `ChatStorage.init_home()` — create directory structure (.acl/, _inbox/, _archive/)
- [x] `ChatStorage.list_projects()` → list[Project]
- [x] `ChatStorage.list_chats(project_path)` → list[Chat]
- [x] `ChatStorage.read_chat(path)` → Chat (parse YAML frontmatter + markdown body)
- [x] `ChatStorage.write_chat(path, chat)` → file (render YAML frontmatter + markdown)
- [x] `ChatStorage.read_project(path)` → Project (parse _project.yaml)
- [x] `ChatStorage.write_project(path, project)` → file
- [x] `ChatStorage.move_chat(src, dst_project)` → update file location + handle name collisions
- [x] `ChatStorage.chat_filename(chat)` → generate YYYY-MM-DD_slug.md filename
- [x] `ChatStorage.create_project(name)` → create folder + _project.yaml
- [x] File permissions: 0o600/0o700 on every write (via fileutil)

> **Divergence:** Storage is a class (`ChatStorage(home)`) rather than standalone functions, for cleaner API. Added `chat_filename()` and `create_project()` helpers not in original plan.

`src/anticlaw/core/fileutil.py`:
- [x] `safe_filename(title)` → slug (no path traversal, no special chars)
- [x] `atomic_write(path, content)` — write to .tmp, then os.replace
- [x] `file_lock(path)` — fcntl.flock (Unix) / msvcrt.locking (Windows)
- [x] `ensure_dir(path)` — mkdir with secure permissions
- [x] `ensure_file_permissions(path)` — chmod 0o600

`src/anticlaw/core/config.py` (added, not in original plan):
- [x] `load_config(path)` — load YAML with deep-merge defaults
- [x] `resolve_home()` — ACL_HOME from env / config / default
- [x] `DEFAULTS` dict matching config.example.yaml

**Tests (57 total):**
- [x] Round-trip: Chat → write_chat → read_chat → same Chat
- [x] Round-trip: Project → write_project → read_project → same Project
- [x] safe_filename edge cases (unicode, long names, path traversal, special chars)
- [x] Multiline content, empty messages, load_messages=False
- [x] list_projects, list_chats, move_chat with collision handling
- [x] Config: deep merge, env override, empty/corrupt YAML fallback

**Deliverable:** Can programmatically create and read `~/anticlaw/project/chat.md` ✅

---

### Phase 2: Claude Provider + Import (Days 4–5) ✅

```
Goal: Import Claude.ai export into local file structure.
```

**Files:**

`src/anticlaw/providers/registry.py` (added):
- [x] `ProviderRegistry` class: register, get, get_entry, list_family, list_all, families
- [x] `ProviderEntry` dataclass (family, name, cls, extras)
- [x] Global `registry` singleton

`src/anticlaw/providers/llm/base.py` (was `providers/base.py` in original plan):
- [x] `LLMProvider` Protocol (`@runtime_checkable`) — auth, list_projects, list_chats, export_chat, export_all, import_chat, sync
- [x] `ProviderInfo` dataclass (display_name, version, capabilities)
- [x] `Capability` enum (EXPORT_BULK, EXPORT_SINGLE, IMPORT, LIST_PROJECTS, LIST_CHATS, SYNC, SCRAPE)

> **Divergence:** Provider models (`ChatData`, `RemoteProject`, etc.) live in `core/models.py` rather than `providers/base.py`. Protocol and base types moved to `providers/llm/base.py` following the nested provider family structure from PROVIDERS.md.

`src/anticlaw/providers/llm/claude.py` (was `providers/claude.py`):
- [x] `ClaudeProvider.parse_export_zip(zip_path, scrub)` → list[ChatData]
- [x] `ClaudeProvider.load_project_mapping(path)` → dict[str, str]
- [x] `scrub_text(text)` — 7 regex patterns (API keys, Bearer tokens, GitHub tokens, AWS keys, private keys, connection strings, passwords)
- [x] Handle: simple `text` field and structured `content` array, message roles, timestamps
- [x] Graceful skip of malformed conversations

`src/anticlaw/providers/claude_scraper.py` (optional, requires `[scraper]`):
- [ ] Playwright script: login to claude.ai → list projects → map chat→project (deferred)

`src/anticlaw/cli/main.py`:
- [x] Click CLI entry point with import command group

`src/anticlaw/cli/import_cmd.py`:
- [x] `aw import claude <export.zip> [--scrub] [--mapping FILE] [--home PATH]`
- [x] If mapping provided: chat goes to correct project folder (auto-created)
- [x] If no mapping: everything goes to `_inbox/`
- [x] Progress bar (click.progressbar)
- [x] Duplicate detection (skip if filename exists)
- [x] Summary output (imported, skipped, mapped)

> **Divergence:** `aw init` not implemented as separate command yet — `aw import` auto-initializes home. Added `--home` flag for overriding ACL_HOME.

**Tests (40 new, 97 total):**
- [x] Parse sample conversations.json (ZIP fixture)
- [x] Conversation fields, messages, timestamps, structured content
- [x] Import creates correct file structure
- [x] Scrubbing removes 7 pattern types
- [x] Missing mapping → all in _inbox/
- [x] Duplicate skipping, empty export, help text
- [x] ProviderRegistry: register, get, list, families, entries

**Deliverable:** `aw import claude export.zip` → files appear in `~/anticlaw/` ✅

---

### Phase 3: SQLite Metadata + Basic Search (Days 6–8) ✅

```
Goal: Index all chats in SQLite, search by keyword.
```

**Files:**

`src/anticlaw/core/meta_db.py`:
- [x] SQLite database at `.acl/meta.db`
- [x] Tables:
  ```sql
  CREATE TABLE chats (
      id TEXT PRIMARY KEY,
      title TEXT,
      project_id TEXT,
      provider TEXT,
      remote_id TEXT,
      created TEXT,
      updated TEXT,
      tags TEXT,          -- JSON array
      summary TEXT,
      importance TEXT,
      status TEXT,
      file_path TEXT,
      token_count INTEGER,
      message_count INTEGER,
      content TEXT        -- full message text for FTS indexing
  );

  CREATE TABLE projects (
      id TEXT PRIMARY KEY,
      name TEXT,
      description TEXT,
      created TEXT,
      updated TEXT,
      tags TEXT,
      status TEXT,
      dir_path TEXT
  );

  CREATE VIRTUAL TABLE chats_fts USING fts5(
      chat_id UNINDEXED, title, summary, content, tags
  );
  ```
- [x] `index_chat(chat, file_path)` — insert/update in both tables
- [x] `index_project(project, dir_path)` — insert/update
- [x] `reindex_all(home)` — walk file system, index everything
- [x] `search_keyword(query)` → list of results with snippets

> **Divergence from plan:** FTS5 uses a standalone table with `chat_id UNINDEXED` instead of `content=chats, content_rowid=rowid` (external content table). This is simpler to maintain — no triggers needed, DELETE/INSERT for updates. Added `content TEXT` column to `chats` table to store concatenated message text for FTS indexing. Also added `MetaDB.get_chat()`, `list_projects()`, `list_chats()`, `update_chat_tags()`, `update_chat_path()` methods for CLI support. `SearchResult` dataclass lives in `meta_db.py`.

`src/anticlaw/core/search.py`:
- [x] Tier 1: `search_keyword(query)` — FTS5 MATCH
- [x] `search(db, query, **filters)` — dispatcher, currently only Tier 1
- [x] Filters: project, tags, importance, date range, max_results

> **Divergence:** `search()` takes `db: MetaDB` as explicit first argument (no global state). Tier 1 uses FTS5 MATCH with BM25 ranking (more powerful than the spec's "substring/regex" description).

`src/anticlaw/cli/search_cmd.py`:
- [x] `aw search <query> [--project X] [--tag Y] [--exact] [--max-results N]`
- [x] Display: title, project, short ID, snippet with `**highlight**` markers

`src/anticlaw/cli/project_cmd.py`:
- [x] `aw list` — list projects (from meta.db)
- [x] `aw list <project>` — list chats in project
- [x] `aw show <chat-id>` — display chat content
- [x] `aw move <chat-id> <project>` — move file + update meta.db
- [x] `aw tag <chat-id> <tags...>` — update tags in frontmatter + meta.db
- [x] `aw create project <name>` — create folder + _project.yaml
- [x] `aw reindex` — rebuild entire search index from filesystem

> **Divergence:** Added `aw reindex` command (not in original plan) — essential for building the index after imports. All commands that reference `<chat-id>` support partial (prefix) ID matching. Each command has `--home` flag for overriding ACL_HOME.

**Tests (52 new, 149 total):**
- [x] Index → search → find
- [x] FTS5 ranking (multi-word queries)
- [x] Move updates both file system and meta.db
- [x] Tag update reflects in both file and DB
- [x] Reindex from filesystem
- [x] CLI: search, list, show, move, tag, create, reindex

**Deliverable:** `aw search "авторизация"` returns results with snippets ✅

---

### Phase 4: MCP Server (Days 9–11) ✅

```
Goal: Claude Code can search and save to AnticLaw.
```

**Files:**

`src/anticlaw/mcp/server.py`:
- [x] FastMCP server registration
- [x] Tools:
  - `aw_ping` — health check
  - `aw_remember` — save insight (with MUST directive in description)
  - `aw_recall` — retrieve insights with filters
  - `aw_forget` — remove insight
  - `aw_search` — search across chats and insights
  - `aw_load_context` — store large content as variable
  - `aw_inspect_context` — metadata preview
  - `aw_get_context` — read content / line range
  - `aw_chunk_context` — split into chunks
  - `aw_peek_chunk` — read specific chunk
  - `aw_related` — graph traversal (stub until Phase 6)
  - `aw_graph_stats` — graph stats (stub until Phase 6)
  - `aw_projects` — list projects

`src/anticlaw/mcp/hooks.py`:
- [x] AutoReminder hook: progressive reminders at 10/20/30 turns (TurnTracker)
- [x] PostSave hook: reset turn counter on `aw_remember`
- [x] Hook installer: `install_claude_code()` and `install_cursor()` merge config JSON
- [ ] PreCompact hook: block until agent saves context (deferred — requires Claude Code hook integration)

`src/anticlaw/mcp/context_store.py`:
- [x] Context-as-variable: save large text to `.acl/contexts/`
- [x] Chunking: 6 strategies (auto, lines, paragraphs, headings, chars, regex)
- [x] Peek: read chunk by number
- [ ] Filter: regex grep on context content (deferred)

`src/anticlaw/mcp/__main__.py`:
- [x] Entry point for `python -m anticlaw.mcp`

`src/anticlaw/cli/mcp_cmd.py`:
- [x] `aw mcp install claude-code` — register MCP server
- [x] `aw mcp install cursor` — register for Cursor
- [x] `aw mcp start` — run MCP server (stdio)

**Templates:**
- [ ] `agents/anticlaw.md` — agent instructions for Claude Code (deferred to Phase 11)
- [ ] `templates/CLAUDE.md` — session instructions (deferred to Phase 11)

> **Divergence from plan:** Insights stored in `meta.db` (same database) instead of separate `graph.db` — graph.db is deferred to Phase 6. FTS5 not used for insights (simple LIKE query for now). Turn tracker is in-memory (resets on server restart). `aw_related` and `aw_graph_stats` are stubs returning `not_implemented`. Tool implementations separated into `*_impl(home)` functions for testability. Hook system uses in-server turn tracking rather than external shell hooks. `aw mcp install` writes JSON config files directly (Claude Code `settings.json`, Cursor `mcp.json`). Added `fastmcp>=2.0` to core dependencies.

**Tests (52 new, 201 total):**
- [x] MCP server ping, empty home
- [x] remember → recall round-trip with filters (query, category, project)
- [x] forget existing + nonexistent
- [x] search returns results via MCP impl
- [x] Context load → chunk → peek round-trip (all 6 strategies)
- [x] TurnTracker thresholds, reset, custom thresholds
- [x] Config generation, install_claude_code (preserves existing), install_cursor
- [x] CLI: mcp start --help, mcp install (claude-code, cursor, invalid target)

**Deliverable:** In Claude Code: `aw_search("авторизация")` returns results ✅

---

### Phase 5: Advanced Search — Tiers 2–5 (Days 12–14)

```
Goal: BM25, fuzzy, semantic, hybrid search.
```

**Files:**

`src/anticlaw/core/search.py` (extend):
- [ ] Tier 2: `search_bm25(query)` — via bm25s library
- [ ] Tier 3: `search_fuzzy(query)` — via rapidfuzz
- [ ] Tier 4: `search_semantic(query)` — via ChromaDB + Ollama embeddings
- [ ] Tier 5: `search_hybrid(query, alpha)` — BM25 + semantic fusion
- [ ] Auto-tier selection based on installed deps
- [ ] `max_tokens` parameter for budget control

`src/anticlaw/core/embeddings.py`:
- [ ] `OllamaEmbedder`: calls Ollama API for nomic-embed-text
- [ ] `embed_text(text) → list[float]`
- [ ] `embed_batch(texts) → list[list[float]]`
- [ ] Embedding cache via `diskcache`

`src/anticlaw/core/index.py`:
- [ ] ChromaDB collection management
- [ ] `index_chat_vectors(chat)` — embed all messages, store in ChromaDB
- [ ] `index_insight_vectors(insight)` — embed insight text
- [ ] `reindex_vectors(home)` — full re-embedding

**Tests:**
- [ ] Each tier returns ranked results
- [ ] Graceful degradation: missing dep → falls back to lower tier
- [ ] Hybrid fusion produces better ranking than either alone
- [ ] Token budget respected

**Deliverable:** `aw search "database choice"` finds "Decided on SQLite for graph storage" via semantic search

---

### Phase 6: Knowledge Graph — MAGMA (Days 15–17)

```
Goal: Insights connected via 4 edge types, intent-aware recall.
```

**Files:**

`src/anticlaw/core/graph.py`:
- [ ] SQLite schema in `.acl/graph.db`:
  ```sql
  CREATE TABLE nodes (
      id TEXT PRIMARY KEY,
      content TEXT,
      category TEXT,
      importance TEXT,
      tags TEXT,
      project_id TEXT,
      chat_id TEXT,
      created TEXT,
      updated TEXT,
      status TEXT
  );

  CREATE TABLE edges (
      id TEXT PRIMARY KEY,
      source_id TEXT,
      target_id TEXT,
      edge_type TEXT,     -- temporal | entity | semantic | causal
      weight REAL,
      metadata TEXT,      -- JSON: entity name, similarity score, etc.
      created TEXT,
      FOREIGN KEY (source_id) REFERENCES nodes(id),
      FOREIGN KEY (target_id) REFERENCES nodes(id)
  );
  ```
- [ ] `add_node(insight)` → create node + auto-generate edges
- [ ] `auto_temporal_edges(node)` — link to recent nodes (30 min window)
- [ ] `auto_entity_edges(node)` — extract entities, link to same-entity nodes
- [ ] `auto_semantic_edges(node)` — embed, find top-3 similar, create edges
- [ ] `auto_causal_edges(node)` — detect causal keywords, link to cause/effect
- [ ] `traverse(node_id, edge_type, depth)` → connected nodes
- [ ] `intent_detect(query)` → preferred edge type ("why"→causal, "when"→temporal)
- [ ] `graph_stats()` → counts, top entities

`src/anticlaw/core/entities.py`:
- [ ] Regex entity extractor: file paths, URLs, CamelCase, technical terms
- [ ] (Optional) LLM entity extractor via Ollama

Update MCP server:
- [ ] `aw_related` — real implementation
- [ ] `aw_graph_stats` — real implementation

CLI:
- [ ] `aw related <node-id> [--edge-type causal]`
- [ ] `aw why "decision X"` — causal traversal shortcut
- [ ] `aw timeline <project>` — temporal traversal

**Tests:**
- [ ] Add 3 nodes → temporal edges auto-created
- [ ] Same entity in 2 nodes → entity edge auto-created
- [ ] Similar content → semantic edge with weight > 0.7
- [ ] "because" in text → causal edge detected
- [ ] Intent detection: "why X" → causal, "when X" → temporal

**Deliverable:** `aw why "chose SQLite"` traces causal chain

---

### Phase 7: Local LLM Integration (Days 18–19)

```
Goal: Summarization, auto-tagging, Q&A via Ollama.
```

**Files:**

`src/anticlaw/llm/ollama_client.py`:
- [ ] `OllamaClient`: wrapper around Ollama HTTP API (localhost:11434)
- [ ] `generate(prompt, model)` → response text
- [ ] `available_models()` → list of installed models
- [ ] Error handling: Ollama not running → graceful fallback

`src/anticlaw/llm/summarizer.py`:
- [ ] `summarize_chat(chat) → str` — 2-3 sentence summary
- [ ] `summarize_project(project) → str` — project-level summary from all chats

`src/anticlaw/llm/tagger.py`:
- [ ] `auto_tag(chat) → list[str]` — suggest tags based on content
- [ ] `auto_categorize(chat) → str` — suggest project for inbox chats

`src/anticlaw/llm/qa.py`:
- [ ] `ask(question, context_chats) → str` — Q&A over selected chats
- [ ] Uses search to find relevant context, then sends to LLM

CLI:
- [ ] `aw summarize <project-or-chat>` — generate/update summary
- [ ] `aw autotag <chat-or-project>` — auto-tag via LLM
- [ ] `aw ask "question"` — Q&A over knowledge base
- [ ] `aw import claude export.zip --summarize --autotag`

**Tests:**
- [ ] Summarizer produces non-empty string
- [ ] Auto-tag returns relevant tags
- [ ] Q&A returns answer referencing correct chats
- [ ] Graceful fallback when Ollama not running

**Deliverable:** `aw ask "what auth approach did we choose?"` → answer with references

---

### Phase 8: Daemon + File Watcher (Days 20–23)

```
Goal: Background process watches file system, auto-indexes, tray icon.
```

**Files:**

`src/anticlaw/daemon/watcher.py`:
- [ ] `FileWatcher` class using `watchdog`
- [ ] Events: created, modified, deleted, moved
- [ ] Debounce: wait N seconds after last change before processing
- [ ] Ignore patterns: .tmp, .swp, .git/, .acl/
- [ ] On .md created/modified → reindex chat, update graph
- [ ] On folder created → offer to register as project
- [ ] On .md moved → update project membership
- [ ] On .md deleted → mark as archived in meta.db

`src/anticlaw/daemon/scheduler.py`:
- [ ] APScheduler integration
- [ ] Jobs: backup, retention, health check, sync
- [ ] Cron-style schedule from config.yaml

`src/anticlaw/daemon/backup.py`:
- [ ] `BackupEngine` with pluggable targets:
  - `LocalBackup`: rsync / shutil copy
  - `GDriveBackup`: google-api-python-client
  - `S3Backup`: boto3
- [ ] Incremental: only changed files since last backup
- [ ] Manifest: `.acl/backup_manifest.json`

`src/anticlaw/daemon/tray.py`:
- [ ] `pystray` system tray icon
- [ ] Menu:
  - Status: "Watching ~/anticlaw (42 chats, 5 projects)"
  - Force Sync Now
  - Force Backup Now
  - Open ACL_HOME in File Manager
  - Open Logs
  - Settings (opens config.yaml in editor)
  - Pause / Resume watching
  - Quit
- [ ] Desktop notifications via `plyer`:
  - "New chat indexed: auth-discussion.md"
  - "Backup completed: 3 files to Google Drive"
  - "Warning: 5 chats in _inbox/ need classification"

`src/anticlaw/daemon/service.py`:
- [ ] Platform-specific service registration:
  - Linux: systemd unit file
  - macOS: launchd plist
  - Windows: `pythonw.exe` + startup shortcut (or `pywin32` service)
- [ ] PID file management
- [ ] Log rotation

`src/anticlaw/daemon/ipc.py`:
- [ ] Unix socket (Linux/macOS) / Named pipe (Windows)
- [ ] CLI → Daemon commands: status, force-sync, force-backup, pause, resume
- [ ] Daemon → CLI responses: JSON status

CLI:
- [ ] `aw daemon start` — start daemon (foreground)
- [ ] `aw daemon install` — register as system service
- [ ] `aw daemon uninstall` — remove system service
- [ ] `aw daemon status` — check if running, show stats
- [ ] `aw daemon stop` — stop daemon
- [ ] `aw daemon logs` — tail daemon log
- [ ] `aw backup now` — trigger backup via IPC
- [ ] `aw sync now` — trigger sync via IPC

**Tests:**
- [ ] Watcher detects file creation → meta.db updated
- [ ] Watcher debounce works (multiple rapid changes → one index)
- [ ] Scheduler fires jobs at configured times (mocked clock)
- [ ] IPC round-trip: CLI sends command → daemon responds
- [ ] Backup creates correct file set
- [ ] Service install/uninstall on current platform

**Deliverable:** Daemon running in tray, auto-indexes on file change, notification appears

---

### Phase 9: Retention + Antientropy Features (Days 24–25)

```
Goal: Active knowledge management — inbox, stale, duplicates, health.
```

**Files:**

`src/anticlaw/core/retention.py`:
- [ ] `preview_retention()` → dry-run: what would be archived/purged
- [ ] `run_retention()` → move to _archive/, compress, update meta.db
- [ ] `restore(chat_id)` → move back from _archive/ to project
- [ ] Importance decay: half-life calculation

`src/anticlaw/core/antientropy.py`:
- [ ] `inbox_suggestions()` → for each _inbox/ chat, suggest project (via LLM or tag matching)
- [ ] `find_stale(days)` → projects with no activity > N days
- [ ] `find_duplicates()` → pairs of chats with semantic similarity > 0.9
- [ ] `health_check()` → orphan files, missing metadata, broken links, unindexed chats

CLI:
- [ ] `aw inbox` — show inbox chats with classification suggestions
- [ ] `aw inbox --auto` — auto-classify using LLM suggestions
- [ ] `aw stale [--days 30]` — list stale projects
- [ ] `aw duplicates` — list similar chat pairs
- [ ] `aw health` — full integrity check
- [ ] `aw retention preview` / `aw retention run` / `aw restore <id>`
- [ ] `aw stats` — global KB statistics

**Deliverable:** `aw health` reports all issues, `aw inbox` suggests classifications

---

### Phase 10: ChatGPT Provider (Days 26–27)

```
Goal: Import ChatGPT export, same file format output.
```

**Files:**

`src/anticlaw/providers/chatgpt.py`:
- [ ] Parse ChatGPT export format (different JSON schema)
- [ ] Map to same `ChatData` model
- [ ] Handle: conversations, titles, model info

CLI:
- [ ] `aw import chatgpt <export.zip> [--scrub]`

**Tests:**
- [ ] Parse sample ChatGPT export
- [ ] Output .md files identical in format to Claude imports
- [ ] Cross-provider search finds chats from both

**Deliverable:** `aw search "topic"` returns results from both Claude and ChatGPT chats

---

### Phase 11: Polish + v1.0 Release (Days 28–30)

```
Goal: Production-ready release.
```

- [ ] README.md with screenshots, quickstart, architecture diagram
- [ ] Full documentation in docs/
- [ ] Interactive installer (`aw init --interactive`)
- [ ] `pip install anticlaw` works from PyPI
- [ ] Docker support: `docker-compose.yml` for daemon
- [ ] GitHub Actions: CI + release workflow (PyPI publish on tag)
- [ ] Test coverage > 80%
- [ ] Windows + macOS + Linux tested

**Deliverable:** `pip install anticlaw && aw init && aw daemon install` — full working system

---

### Phase 12: Local File Source + HTTP API (Days 31–35)

```
Goal: Index local files (text, code, PDF) and expose HTTP API for external clients.
```

**Files:**

`src/anticlaw/providers/source/`:
- [ ] `base.py` — `SourceProvider` Protocol:
  ```python
  @runtime_checkable
  class SourceProvider(Protocol):
      @property
      def name(self) -> str: ...
      def scan(self, paths: list[Path], **filters) -> list[SourceDocument]: ...
      def read(self, path: Path) -> SourceDocument: ...
      def watch(self, paths: list[Path], callback: Callable) -> None: ...
  ```
- [ ] `local_files.py` — `LocalFilesProvider`:
  - Recursive scan of configured directories
  - File readers by extension:
    - `.txt`, `.md`, `.json`, `.yaml`, `.xml`, `.csv` → direct read
    - `.py`, `.java`, `.js`, `.ts`, `.go`, `.rs`, `.sql` → read with language tag
    - `.pdf` → `pymupdf` (fallback: `pdfplumber`)
    - `.properties`, `.ini`, `.toml`, `.cfg` → direct read
  - Exclude patterns: `node_modules`, `.git`, `__pycache__`, `target`, `build`, `dist`
  - Max file size limit (default 10 MB)
  - File hash for change detection (incremental reindex)

`src/anticlaw/core/models.py` (extend):
- [ ] `SourceDocument` dataclass: path, content, language, size, hash, indexed_at, source_provider

`src/anticlaw/core/meta_db.py` (extend):
- [ ] `source_files` table:
  ```sql
  CREATE TABLE source_files (
      id TEXT PRIMARY KEY,
      file_path TEXT UNIQUE,
      filename TEXT,
      extension TEXT,
      language TEXT,
      size INTEGER,
      hash TEXT,
      indexed_at TEXT,
      project_id TEXT
  );
  CREATE VIRTUAL TABLE source_files_fts USING fts5(
      filename, content,
      content=source_files, content_rowid=rowid
  );
  ```
- [ ] `index_source_file()`, `search_source_files()`, `reindex_source_files()`

`src/anticlaw/core/search.py` (extend):
- [ ] Unified search now queries both `chats_fts` and `source_files_fts`
- [ ] Result type tag: `chat` | `insight` | `file`
- [ ] Semantic search across all content types

`src/anticlaw/api/`:
- [ ] `server.py` — FastAPI app:
  ```python
  GET  /api/health
  GET  /api/search?q=...&project=...&type=...&max_results=...
  POST /api/ask      {"question": "...", "project": "..."}
  GET  /api/projects
  GET  /api/stats
  ```
- [ ] Auth: optional API key (for remote access), no auth for localhost
- [ ] CORS: configurable origins

CLI:
- [ ] `aw scan [path]` — index local files from configured paths
- [ ] `aw scan --watch` — watch for changes (one-shot, not daemon)
- [ ] `aw api start [--port 8420]` — start HTTP API server
- [ ] `aw search` — now shows results from files too

Config:
```yaml
sources:
  local-files:
    enabled: true
    paths:
      - C:\Users\igor.zamiatin\srdev
      - C:\Users\igor.zamiatin\Documents\specs
    extensions: [.java, .py, .txt, .md, .pdf, .json, .xml, .yaml, .properties, .sql]
    exclude: [node_modules, .git, __pycache__, target, build, dist, .idea, .vscode]
    max_file_size_mb: 10

api:
  enabled: false
  host: 127.0.0.1
  port: 8420
  api_key: keyring          # optional, for remote access
  cors_origins: []
```

**Dependencies:**
```toml
[project.optional-dependencies]
source-pdf = ["pymupdf"]
api        = ["fastapi", "uvicorn"]
```

**Tests:**
- [ ] Scan directory → correct files indexed
- [ ] PDF extraction works
- [ ] Exclude patterns respected
- [ ] Unified search returns both chats and files
- [ ] HTTP API endpoints respond correctly
- [ ] Incremental reindex (only changed files)

**Deliverable:** `aw search "TreeMap"` finds both LLM chats about TreeMap and .java files using TreeMap

---

### Phase 13: Voice Input — Local Whisper (Days 36–38)

```
Goal: Voice-to-search using offline Whisper model.
```

**Files:**

`src/anticlaw/input/`:
- [ ] `base.py` — `InputProvider` Protocol:
  ```python
  @runtime_checkable
  class InputProvider(Protocol):
      @property
      def name(self) -> str: ...
      def listen(self) -> str: ...       # returns transcribed text
      def is_available(self) -> bool: ... # check hardware/deps
  ```
- [ ] `whisper_input.py` — `WhisperInputProvider`:
  - Uses `faster-whisper` (CTranslate2 backend, fast on CPU)
  - Model: `base` (~150 MB, good for commands) or `small` (~500 MB, better accuracy)
  - Multilingual: Russian + English out of the box
  - VAD (Voice Activity Detection): auto-detect speech start/end
  - Push-to-talk mode: hold key to record
  - Continuous mode: always listening for wake word

CLI:
- [ ] `aw listen` — listen → transcribe → search → show results
- [ ] `aw listen --continuous` — loop: listen → search → speak result (via TTS)
- [ ] `aw listen --mode ask` — voice question → `aw ask` → spoken answer

Config:
```yaml
voice:
  enabled: false
  model: base                    # base (~150 MB) | small (~500 MB) | medium (~1.5 GB)
  language: auto                 # auto | ru | en
  push_to_talk_key: ctrl+space
  wake_word: null                # optional: "антик" or "hey antic"
```

**Dependencies:**
```toml
[project.optional-dependencies]
voice = ["faster-whisper", "sounddevice", "numpy"]
tts   = ["pyttsx3"]             # optional: text-to-speech for answers
```

**Tests:**
- [ ] Whisper model loads and transcribes sample audio
- [ ] Russian text recognized
- [ ] Push-to-talk key binding works
- [ ] Transcribed text passed to search correctly

**Deliverable:** `aw listen` → say "найди чаты про авторизацию" → results appear

---

### Phase 14: Alexa Integration (Days 39–42)

```
Goal: Ask AnticLaw questions via Amazon Alexa.
```

**Architecture:**

```
Voice → Alexa → AWS Lambda → HTTPS tunnel → AnticLaw HTTP API → response → Lambda → Alexa → Voice
                                  ↑
                          Cloudflare Tunnel / ngrok / Tailscale
```

**Components:**

`alexa/` (separate directory, not in anticlaw package):
- [ ] `skill.json` — Alexa Skill manifest
- [ ] `interaction_model.json` — intents:
  - `SearchIntent`: "найди {query}" / "search for {query}"
  - `AskIntent`: "спроси {question}" / "ask {question}"
  - `StatusIntent`: "статус базы знаний" / "knowledge base status"
- [ ] `lambda_function.py` — AWS Lambda handler:
  - Receives Alexa request
  - Calls AnticLaw HTTP API (Phase 12)
  - Formats response for speech
  - Handles Russian + English

`src/anticlaw/api/server.py` (extend):
- [ ] `/api/voice/search` — optimized for short spoken responses
- [ ] `/api/voice/ask` — Q&A with concise answer format

CLI:
- [ ] `aw tunnel start` — start Cloudflare Tunnel to expose API
- [ ] `aw tunnel status` — show tunnel URL
- [ ] `aw alexa setup` — guide for Alexa Skill configuration

Config:
```yaml
api:
  tunnel:
    provider: cloudflare         # cloudflare | ngrok | tailscale
    enabled: false
    # Cloudflare Tunnel: requires cloudflared installed
    # ngrok: requires ngrok token in keyring
```

**Dependencies:**
```toml
[project.optional-dependencies]
alexa = ["ask-sdk-core"]         # Alexa Skills Kit SDK (for Lambda)
tunnel = ["cloudflared"]         # or just document manual install
```

**Prerequisite:** Phase 12 (HTTP API) must be complete.

**Tests:**
- [ ] Lambda handler processes Alexa request correctly
- [ ] Voice-optimized responses are concise (<8 seconds spoken)
- [ ] Russian intent recognition works
- [ ] Tunnel exposes local API

**Deliverable:** "Alexa, ask AnticLaw to find chats about authorization" → spoken answer

---

## Dependency Summary

### Core (always installed)

```
click              # CLI framework
pyyaml             # YAML parsing
python-frontmatter # Markdown + YAML frontmatter
keyring            # Secrets management
```

> **Note:** Data models use stdlib `dataclasses` (not Pydantic) per coding standards in CLAUDE.md — keeps core deps minimal.

### Optional extras

```
[search]     → bm25s
[fuzzy]      → rapidfuzz
[semantic]   → chromadb, numpy, httpx (for Ollama API)
[daemon]     → watchdog, apscheduler, pystray, pillow, plyer
[backup]     → google-api-python-client, boto3
[scraper]    → playwright
[llm]        → httpx (for Ollama API)
[dev]        → pytest, ruff, pre-commit
[all]        → everything above
```

### External (user installs separately)

```
Ollama       → ollama.com (for embeddings + local LLM)
  Models:
  - nomic-embed-text  (~275 MB, for embeddings)
  - llama3.1:8b       (~4.7 GB, for summarization/Q&A)
```

---

## Milestones

| Phase | Days | Milestone | CLI Commands |
|-------|------|-----------|-------------|
| 0 | 1 | Scaffolding | `aw --version` |
| 1 | 2–3 | Core models + storage | (internal) |
| 2 | 4–5 | Claude import | `aw init`, `aw import claude` |
| 3 | 6–8 | Search + metadata | `aw search`, `aw list`, `aw show`, `aw move`, `aw tag` |
| 4 | 9–11 | MCP server | `aw mcp install`, MCP tools in Claude Code |
| 5 | 12–14 | Advanced search | 5-tier search operational |
| 6 | 15–17 | Knowledge graph | `aw related`, `aw why`, `aw timeline` |
| 7 | 18–19 | Local LLM | `aw summarize`, `aw autotag`, `aw ask` |
| 8 | 20–23 | Daemon + tray | `aw daemon install`, auto-indexing, backup |
| 9 | 24–25 | Antientropy | `aw inbox`, `aw stale`, `aw duplicates`, `aw health` |
| 10 | 26–27 | ChatGPT provider | `aw import chatgpt` |
| 11 | 28–30 | v1.0 Release | PyPI, Docker, docs |
| **12** | **31–35** | **Local files + HTTP API** | **`aw scan`, `aw api start`** |
| **13** | **36–38** | **Voice input (Whisper)** | **`aw listen`** |
| **14** | **39–42** | **Alexa integration** | **`aw tunnel start`, Alexa Skill** |

**Total: ~42 working days to v1.5**
