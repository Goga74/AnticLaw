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

  # Task scheduler — configurable cron jobs
  tasks:
    - name: reindex
      schedule: "0 2 * * *"         # daily at 2 AM
      enabled: true
      action: reindex               # rebuild meta.db + vectors from filesystem

    - name: backup
      schedule: "0 3 * * *"         # daily at 3 AM
      enabled: false
      action: backup
      params:
        providers: [local]          # which backup providers to run

    - name: retention
      schedule: "0 4 * * *"         # daily at 4 AM
      enabled: true
      action: retention             # archive/purge per retention policy

    - name: health
      schedule: "0 5 * * 1"         # weekly Monday at 5 AM
      enabled: true
      action: health                # run health check, log warnings

    - name: sync
      schedule: "0 */6 * * *"       # every 6 hours
      enabled: false
      action: sync
      params:
        providers: [claude]
        direction: pull

    - name: summarize-inbox
      schedule: "0 6 * * *"         # daily at 6 AM
      enabled: false
      action: summarize-inbox       # auto-summarize + auto-tag new inbox chats
      params:
        auto_tag: true
        auto_summarize: true

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

### Phase 5: Advanced Search — Tiers 2–5 (Days 12–14) ✅

```
Goal: BM25, fuzzy, semantic, hybrid search.
```

**Files:**

`src/anticlaw/core/search.py` (extend):
- [x] Tier 2: `search_bm25(query)` — via bm25s library
- [x] Tier 3: `search_fuzzy(query)` — via rapidfuzz
- [x] Tier 4: `search_semantic(query)` — via ChromaDB + Ollama embeddings
- [x] Tier 5: `search_hybrid(query, alpha)` — BM25 + semantic fusion
- [x] Auto-tier selection based on installed deps
- [ ] `max_tokens` parameter for budget control (deferred)

`src/anticlaw/providers/embedding/base.py` (was `core/embeddings.py`):
- [x] `EmbeddingProvider` Protocol (`@runtime_checkable`)
- [x] `EmbeddingInfo` dataclass (name, dimensions, provider)

`src/anticlaw/providers/embedding/ollama.py`:
- [x] `OllamaEmbeddingProvider`: calls Ollama API for nomic-embed-text via httpx
- [x] `embed(text) → list[float]`
- [x] `embed_batch(texts) → list[list[float]]`
- [ ] Embedding cache via `diskcache` (deferred)

`src/anticlaw/core/index.py`:
- [x] `VectorIndex` class: ChromaDB persistent client, `chats` + `insights` collections
- [x] `index_chat_vectors(chat)` — embed all messages, store in ChromaDB
- [x] `index_insight_vectors(insight)` — embed insight text
- [x] `reindex_vectors(home)` — full re-embedding from MetaDB

> **Divergence from plan:** Embedding providers implemented in `providers/embedding/` (following provider family architecture from PROVIDERS.md) instead of `core/embeddings.py`. `OllamaEmbeddingProvider` uses `httpx` for Ollama API calls. `diskcache` embedding cache deferred. `max_tokens` token budget deferred. `VectorIndex` class manages ChromaDB `PersistentClient` with separate `chats` and `insights` collections using cosine distance. Helper functions `index_chat_vectors()`, `index_insight_vectors()`, `reindex_vectors()` compose embedder + index operations.

**Tests (65 new, 266 total):**
- [x] Each tier returns ranked results
- [x] Graceful degradation: missing dep → falls back to lower tier
- [x] Hybrid fusion produces better ranking than either alone
- [x] BM25, fuzzy, semantic, hybrid tier-specific tests
- [x] EmbeddingProvider Protocol tests + OllamaEmbeddingProvider mock tests
- [x] VectorIndex: index_chat, index_insight, search, clear, reindex
- [ ] Token budget respected (deferred with max_tokens)

**Deliverable:** `aw search "database choice"` finds semantic matches via 5-tier search ✅

---

### Phase 6: Knowledge Graph — MAGMA (Days 15–17) ✅

```
Goal: Insights connected via 4 edge types, intent-aware recall.
```

**Files:**

`src/anticlaw/core/graph.py`:
- [x] SQLite schema in `.acl/graph.db` (nodes + edges tables with indexes)
- [x] `add_node(insight)` → create node + auto-generate edges (all 4 types)
- [x] `_auto_temporal_edges(node)` — link to nodes within configurable time window (default 30 min)
- [x] `_auto_entity_edges(node)` — extract entities, link to same-entity nodes
- [x] `_auto_semantic_edges(node)` — embed, find top-K similar (>0.7 threshold), create edges
- [x] `_auto_causal_edges(node)` — detect causal keywords, link to cause/effect
- [x] `traverse(node_id, edge_type, depth)` → connected nodes with BFS
- [x] `intent_detect(query)` → preferred edge type ("why"→causal, "when"→temporal, "what"→entity)
- [x] `graph_stats()` → counts, top entities, project distribution

`src/anticlaw/core/entities.py`:
- [x] Regex entity extractor: file paths, URLs, CamelCase, mixed-case terms, UPPER_CASE identifiers
- [x] `has_causal_language(text)` — detect causal keywords (EN + RU)
- [ ] (Optional) LLM entity extractor via Ollama (deferred to Phase 7)

Update MCP server:
- [x] `aw_related` — real implementation (graph traversal with edge type filter)
- [x] `aw_graph_stats` — real implementation (node/edge counts, top entities)
- [x] `aw_remember` now also adds node to graph.db with auto-edge generation

`src/anticlaw/cli/graph_cmd.py`:
- [x] `aw related <node-id> [--edge-type causal] [--depth N]`
- [x] `aw why "decision X"` — causal traversal shortcut
- [x] `aw timeline <project>` — chronological node listing

> **Divergence from plan:** Semantic edge computation uses pure-Python cosine similarity over embeddings stored as JSON in graph.db (avoids coupling to ChromaDB VectorIndex). Embeddings are optional — if no embedder provided, semantic edges are skipped (graceful degradation). Causal edge generation links to both entity-overlapping and temporally close nodes when causal keywords detected. Node embeddings stored in graph.db `embedding` TEXT column (JSON array of floats). `resolve_node()` supports partial ID matching like other commands.

**Tests (67 new, 333 total):**
- [x] Add 3 nodes within time window → temporal edges auto-created
- [x] No temporal edges outside window
- [x] Same entity in 2 nodes → entity edge auto-created (CamelCase, URLs, technical terms)
- [x] Similar content with mock embedder → semantic edge with weight > 0.7
- [x] Dissimilar content → no semantic edge
- [x] No semantic edges without embedder
- [x] "because" in text → causal edge detected
- [x] Russian causal keywords → causal edge detected
- [x] No causal edges without causal keywords
- [x] Intent detection: "why X" → causal, "when X" → temporal, "what X" → entity
- [x] Graph traversal returns connected nodes with depth control
- [x] Graph stats: node/edge counts, project distribution
- [x] CLI: related, why, timeline commands (happy path + error cases)

**Deliverable:** `aw why "chose SQLite"` traces causal chain ✅

---

### Phase 7: Local LLM Integration (Days 18–19) ✅

```
Goal: Summarization, auto-tagging, Q&A via Ollama.
```

**Files:**

`src/anticlaw/llm/ollama_client.py`:
- [x] `OllamaClient`: wrapper around Ollama HTTP API (localhost:11434)
- [x] `generate(prompt, model)` → response text
- [x] `available_models()` → list of installed models
- [x] `is_available()` → check server reachability
- [x] Error handling: Ollama not running → graceful fallback (OllamaNotAvailable exception)

`src/anticlaw/llm/summarizer.py`:
- [x] `summarize_chat(chat) → str` — 2-3 sentence summary
- [x] `summarize_project(name, description, chats) → str` — project-level summary from chat summaries

`src/anticlaw/llm/tagger.py`:
- [x] `auto_tag(chat) → list[str]` — suggest tags based on content (with robust LLM output parsing)
- [x] `auto_categorize(chat) → str` — suggest project for inbox chats

`src/anticlaw/llm/qa.py`:
- [x] `ask(question, home) → QAResult` — search KB for relevant context, send to LLM, return answer with sources
- [x] Uses search to find relevant context, then sends to LLM
- [x] `QAResult` dataclass with answer, sources, error fields

`src/anticlaw/cli/llm_cmd.py`:
- [x] `aw summarize <project-or-chat>` — generate/update summary (updates file + index)
- [x] `aw autotag <chat-or-project>` — auto-tag via LLM (merges with existing tags)
- [x] `aw ask "question"` — Q&A over knowledge base with source references
- [ ] `aw import claude export.zip --summarize --autotag` (deferred)

> **Divergence from plan:** `OllamaClient` has `is_available()` method for pre-flight checks. CLI commands check Ollama availability upfront and show helpful error. `_resolve_target()` handles both chat IDs (including partial prefix) and project names. `auto_tag` uses robust parsing of LLM output (handles comma-separated, bulleted, quoted, bracketed formats). `ask()` returns `QAResult` dataclass instead of plain string. `--summarize --autotag` flags on import deferred.

**Tests (62 new, 395 total):**
- [x] OllamaClient: init, is_available, available_models, generate (14 tests)
- [x] Summarizer: chat summary, project summary, empty inputs, graceful fallback (9 tests)
- [x] Tagger: parse_tags (10 edge cases), auto_tag, auto_categorize, fallback (15 tests)
- [x] Q&A: answer with sources, no DB, no results, Ollama unavailable, context limits (7 tests)
- [x] CLI: summarize/autotag/ask for chat + project, Ollama not running, not found, help (17 tests)

**Deliverable:** `aw ask "what auth approach did we choose?"` → answer with references ✅

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
- [ ] APScheduler integration with configurable cron task system
- [ ] Built-in task types: reindex, backup, retention, health, sync, summarize-inbox
- [ ] Cron-style schedule from config.yaml
- [ ] Each task: name, schedule (cron expression), enabled flag, action, optional params
- [ ] Task execution logging to `.acl/daemon.log`
- [ ] Missed job handling: run on startup if missed by > 1 period

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

`src/anticlaw/providers/llm/chatgpt.py`:
- [x] Parse ChatGPT export format (mapping-tree message structure, Unix timestamps)
- [x] Map to same `ChatData` model
- [x] Handle: conversations, titles, model info (from metadata.model_slug)
- [x] Handle: system/tool message filtering, multipart content, code content
- [x] Reuse scrub_text from Claude provider

CLI (`src/anticlaw/cli/import_cmd.py`):
- [x] `aw import chatgpt <export.zip> [--scrub]`

**Tests:**
- [x] Parse sample ChatGPT export (31 unit tests)
- [x] Output .md files identical in format to Claude imports
- [x] Cross-provider search finds chats from both (import CLI test)

**Deliverable:** `aw search "topic"` returns results from both Claude and ChatGPT chats

---

### Phase 11: Polish + v1.0 Release (Days 28–30)

```
Goal: Production-ready release.
```

- [x] README.md with architecture diagram, feature list, quickstart, badge placeholders
- [x] Full documentation: docs/QUICKSTART.md, docs/TOOLS.md (MCP reference)
- [x] Interactive installer (`aw init [path] [--interactive]`)
- [x] Version bump to 1.0.0, PyPI metadata polished (classifiers, urls, license)
- [ ] `pip install anticlaw` works from PyPI (publish pending)
- [ ] Docker support: `docker-compose.yml` for daemon
- [ ] GitHub Actions: CI + release workflow (PyPI publish on tag)
- [x] Test coverage: 640+ unit tests passing
- [ ] Windows + macOS + Linux tested (manual verification pending)

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

### Phase 13: Web UI (Days 36–42)

```
Goal: Browser-based GUI at localhost for search, graph visualization, project management.
```

**Architecture:**

```
aw ui → uvicorn starts → browser opens http://localhost:8420

┌─────────────────────────────────────────────┐
│  Browser (localhost:8420)                    │
│  ┌────────────────────────────────────────┐  │
│  │  SPA (Svelte or React)                │  │
│  │  - Dashboard: stats, recent activity  │  │
│  │  - Search: unified, filters, previews │  │
│  │  - Projects: tree, chat list, viewer  │  │
│  │  - Graph: MAGMA visualization (D3.js) │  │
│  │  - Inbox: classify, drag & drop       │  │
│  │  - Settings: config editor            │  │
│  └──────────────┬─────────────────────────┘  │
│                 │ fetch()                     │
│  ┌──────────────▼─────────────────────────┐  │
│  │  FastAPI backend (Phase 12 API)        │  │
│  │  + SSE for live updates from daemon    │  │
│  │  + WebSocket for graph exploration     │  │
│  └────────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

**Prerequisite:** Phase 12 (HTTP API).

**Files:**

`src/anticlaw/ui/`:
- [ ] `__init__.py`
- [ ] `app.py` — mount SPA static files + API routes
- [ ] `static/` — built SPA bundle (committed, no Node.js needed at runtime)

`ui-src/` (separate, not in anticlaw package):
- [ ] Svelte/React project
- [ ] `npm run build` → outputs to `src/anticlaw/ui/static/`

**Pages:**

1. **Dashboard**
   - Total chats, insights, projects, files indexed
   - Recent activity timeline
   - Health status (from `aw health`)
   - Backup status (last backup time per provider)

2. **Search**
   - Search bar with auto-tier indicator (keyword/BM25/fuzzy/semantic/hybrid)
   - Filters: project, tags, type (chat/file/insight), date range, importance
   - Results with highlighted snippets
   - Click result → chat viewer or file preview
   - Token budget slider (for MCP context)

3. **Projects**
   - Sidebar: project tree (folders)
   - Main: chat list with metadata (date, tags, importance, summary)
   - Chat viewer: rendered markdown with message timestamps
   - Drag & drop: move chats between projects
   - Inline tag editing

4. **Knowledge Graph**
   - D3.js force-directed graph
   - Nodes: insights, colored by category (decision/finding/preference/fact)
   - Edges: colored by type (temporal=blue, entity=green, semantic=orange, causal=red)
   - Click node → detail panel with content, linked chats
   - Filter by project, edge type, importance
   - "Why" mode: highlight causal chains

5. **Inbox**
   - Unclassified chats from `_inbox/`
   - LLM-suggested project for each (via Ollama)
   - One-click accept or drag to project
   - Bulk actions: auto-classify all

6. **Settings**
   - Config editor (YAML with validation)
   - Provider status (✅/⬚)
   - Daemon status, backup schedule
   - Auth management

CLI:
- [ ] `aw ui` — start web UI, open browser
- [ ] `aw ui --port 8420` — custom port
- [ ] `aw ui --no-open` — start without opening browser

Config:
```yaml
ui:
  enabled: true
  port: 8420
  open_browser: true
  theme: auto                    # auto | light | dark
```

**Dependencies:**
```toml
[project.optional-dependencies]
ui = ["fastapi", "uvicorn", "jinja2"]
# Note: SPA is pre-built, no Node.js runtime dependency
```

**Tests:**
- [ ] API serves SPA at /
- [ ] All API endpoints accessible from UI
- [ ] SSE stream delivers live updates
- [ ] Graph data serialization correct for D3.js

**Deliverable:** `aw ui` → browser opens → full AnticLaw management in GUI

---

### Phase 14: Bidirectional LLM Sync (Days 39–42)

```
Goal: Push local chats to cloud LLM platforms via API, enabling
      file-as-interface workflow and bidirectional sync.
```

**Core concept — file-as-interface:**

1. User (or MCP tool) creates a `.md` file with `status: draft` in frontmatter
2. Daemon detects the new file, reads the push target from config hierarchy
3. Daemon sends content to the target LLM API (Claude/ChatGPT/Gemini)
4. LLM response is written back to the same `.md` file
5. File status changes to `status: complete`

The file system remains the source of truth — the cloud LLM is just another provider.

**Push target routing hierarchy:**

```
1. File frontmatter:  push_target: claude
2. Project config:    _project.yaml → default_push_target: chatgpt
3. Global config:     config.yaml → sync.default_push_target: claude
```

**Files:**

`src/anticlaw/core/sync.py`:
- [ ] `SyncEngine` class:
  - `push_chat(chat, provider)` — send local chat to cloud
  - `pull_new(provider, since)` — pull new chats from cloud (API-based, not export ZIP)
  - `resolve_push_target(file_path)` — walk config hierarchy for target
  - `sync_bidirectional(project, provider)` — full two-way sync with conflict resolution
- [ ] Conflict resolution: local wins by default (file-first philosophy), configurable
- [ ] Status tracking: `sync_status` in frontmatter (synced/pending/conflict)

`src/anticlaw/providers/llm/base.py` (extend):
- [ ] Add `Capability.PUSH` — provider can accept chat pushes via API
- [ ] Add `Capability.PULL_API` — provider can list/pull chats via API (not just export ZIP)

`src/anticlaw/providers/llm/claude.py` (extend):
- [ ] `push_chat()` via Claude API (requires API key, not web subscription)
- [ ] `pull_new()` via Claude API

`src/anticlaw/providers/llm/chatgpt.py` (extend):
- [ ] `push_chat()` via OpenAI API
- [ ] `pull_new()` via OpenAI API

`src/anticlaw/providers/llm/gemini.py` (extend):
- [ ] `push_chat()` via Google AI API
- [ ] `pull_new()` via Google AI API

`src/anticlaw/daemon/watcher.py` (extend):
- [ ] Detect `status: draft` files → trigger push to resolved target
- [ ] On push complete: update file with response, set `status: complete`

`src/anticlaw/cli/sync_cmd.py`:
- [ ] `aw sync <provider> [--project X] [--direction pull|push|both]`
- [ ] `aw push <chat-id> [--target claude]` — push single chat
- [ ] `aw pull <provider> [--since 7d]` — pull recent from cloud
- [ ] `aw sync status` — show sync state for all projects

**API key vs web subscription — critical distinction:**

| Platform | Web subscription | API access |
|----------|-----------------|------------|
| Claude | Claude Pro/Team ($20/mo) — NO API access | Anthropic API key (separate, pay-per-token) |
| ChatGPT | ChatGPT Plus ($20/mo) — NO API access | OpenAI API key (separate, pay-per-token) |
| Gemini | Gemini Advanced ($20/mo) — includes API | Google AI API key (free tier available) |

Users MUST have API keys for push/pull — web subscriptions alone don't provide API access. The CLI will warn about this clearly and guide users to obtain API keys.

**Config:**

```yaml
# config.yaml
sync:
  enabled: false
  default_push_target: claude         # fallback target
  auto_push_drafts: true              # daemon watches for status: draft
  conflict_resolution: local-wins     # local-wins | remote-wins | ask
  providers:
    claude:
      api_key: keyring                # stored in system keyring
    chatgpt:
      api_key: keyring
    gemini:
      api_key: keyring
```

**Frontmatter extensions:**

```yaml
---
id: "acl-20250218-001"
title: "Auth discussion"
status: active                        # active | draft | syncing | complete | conflict
push_target: claude                   # override project/global default
sync_status: synced                   # synced | pending | conflict | local-only
last_synced: 2025-02-20T09:15:00Z
remote_id: "conv_abc123"             # cloud platform's ID for this chat
---
```

**Tests:**
- [ ] Push target resolution: file > project > global
- [ ] SyncEngine push: local → cloud API → response written back
- [ ] SyncEngine pull: cloud → local .md files
- [ ] Conflict resolution: both sides modified
- [ ] Draft file detection by daemon watcher
- [ ] API key validation and helpful error messages
- [ ] CLI: sync, push, pull commands

**Deliverable:** Create a `.md` with `status: draft` → daemon sends to Claude API → response appears in same file

---

### Phase 15: Gemini Provider (Days 43–45)

```
Goal: Import Google Gemini conversations from Google Takeout export.
```

**Files:**

`src/anticlaw/providers/llm/gemini.py`:
- [ ] `GeminiProvider` implementing `LLMProvider` Protocol
- [ ] Parse Google Takeout Gemini export (different structure from Claude/ChatGPT)
- [ ] Map to same `ChatData` model — output identical `.md` files
- [ ] Handle: conversation titles, model info, timestamps, multi-turn format
- [ ] Scrub secrets if `--scrub` flag passed

`src/anticlaw/cli/import_cmd.py` (extend):
- [ ] `aw import gemini <takeout.zip> [--scrub] [--home PATH]`
- [ ] Same UX as `aw import claude`: progress bar, duplicate detection, summary

**Google Takeout structure:**
```
Takeout/
├── Gemini/
│   └── Conversations/
│       ├── 2025-01-15_conversation-title/
│       │   ├── conversation.json
│       │   └── (optional) attachments/
│       └── ...
```

**Tests:**
- [ ] Parse sample Gemini Takeout export
- [ ] Output .md files identical in format to Claude/ChatGPT imports
- [ ] Cross-provider search finds chats from all three providers

**Deliverable:** `aw import gemini takeout.zip` → chats searchable alongside Claude/ChatGPT chats

---

### Phase 16: Voice Input — Local Whisper (Days 46–49)

```
Goal: Voice-to-search using offline Whisper model.
```

**Files:**

`src/anticlaw/input/`:
- [ ] `base.py` — `InputProvider` Protocol
- [ ] `whisper_input.py` — `WhisperInputProvider` (faster-whisper, VAD, push-to-talk)

CLI:
- [ ] `aw listen` — listen → transcribe → search → show results
- [ ] `aw listen --continuous` — loop mode
- [ ] `aw listen --mode ask` — voice Q&A

**Deliverable:** `aw listen` → speak query → results appear

---

### Phase 17: Alexa Integration (Days 50–55)

```
Goal: Ask AnticLaw questions via Amazon Alexa.
```

**Prerequisite:** Phase 12 (HTTP API).

**Components:**
- `alexa/skill.json` — Alexa Skill manifest
- `alexa/lambda_function.py` — AWS Lambda handler
- `aw tunnel start` — expose API via Cloudflare Tunnel

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
[ui]         → fastapi, uvicorn, jinja2
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
| 0 | 1 | Scaffolding ✅ | `aw --version` |
| 1 | 2–3 | Core models + storage ✅ | (internal) |
| 2 | 4–5 | Claude import ✅ | `aw import claude` |
| 3 | 6–8 | Search + metadata ✅ | `aw search`, `aw list`, `aw show`, `aw move`, `aw tag` |
| 4 | 9–11 | MCP server ✅ | `aw mcp install`, MCP tools in Claude Code |
| 5 | 12–14 | Advanced search ✅ | 5-tier search operational |
| 6 | 15–17 | Knowledge graph ✅ | `aw related`, `aw why`, `aw timeline` |
| 7 | 18–19 | Local LLM ✅ | `aw summarize`, `aw autotag`, `aw ask` |
| 8 | 20–23 | Daemon + tray ✅ | `aw daemon install`, auto-indexing, backup |
| 9 | 24–25 | Antientropy ✅ | `aw inbox`, `aw stale`, `aw duplicates`, `aw health` |
| 10 | 26–27 | ChatGPT provider ✅ | `aw import chatgpt` |
| 11 | 28–30 | v1.0 Release ✅ | `aw init`, PyPI, docs |
| **12** | **31–35** | **Local files + HTTP API** | **`aw scan`, `aw api start`** |
| **13** | **36–38** | **Web UI** | **`aw ui`** |
| **14** | **39–42** | **Bidirectional LLM Sync** | **`aw sync`, `aw push`, `aw pull`** |
| **15** | **43–45** | **Gemini Provider** | **`aw import gemini`** |
| **16** | **46–49** | **Voice input (Whisper)** | **`aw listen`** |
| **17** | **50–55** | **Alexa integration** | **`aw tunnel start`, Alexa Skill** |

**Total: ~55 working days to v2.0**
