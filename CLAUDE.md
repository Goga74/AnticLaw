# AnticLaw — Local-First Knowledge Base for LLM Conversations

## What This Is

AnticLaw (`aw` CLI) manages exported LLM conversations (Claude, ChatGPT, Gemini) as local Markdown files with YAML frontmatter. Files = source of truth. LLMs = interchangeable clients.

## Tech Stack

- **Language:** Python 3.10+, `src/anticlaw/` layout
- **CLI:** Click, entry point `aw`
- **MCP:** FastMCP (stdio), 13 tools prefixed `aw_*`
- **Storage:** Markdown+YAML frontmatter (chats), SQLite WAL (meta.db, graph.db), ChromaDB (vectors)
- **Search:** 5-tier (keyword → BM25 → fuzzy → semantic → hybrid)
- **Embeddings:** Ollama + nomic-embed-text (768-dim)
- **Local LLM:** Ollama (summarization, tagging, Q&A)
- **Providers:** 6 families (LLM, Backup, Embedding, Source, Input, Scraper)
- **Config:** YAML (`~/.acl/config.yaml`), secrets in system keyring
- **Build:** pyproject.toml, pip extras for optional deps

## Project Structure

Files marked with ✅ are implemented; unmarked are planned for future phases.

```
src/anticlaw/
├── __init__.py              # ✅ __version__
├── core/
│   ├── models.py            # ✅ Chat, ChatMessage, Project, Insight, Edge + provider models
│   ├── storage.py           # ✅ ChatStorage: read/write .md with frontmatter, CRUD
│   ├── config.py            # ✅ Config loader with defaults, ACL_HOME resolution
│   ├── fileutil.py          # ✅ Atomic writes, safe names, flock, permissions
│   ├── meta_db.py           # ✅ SQLite WAL + FTS5 metadata index (MetaDB)
│   ├── search.py            # ✅ 5-tier search dispatcher (keyword/BM25/fuzzy/semantic/hybrid)
│   ├── index.py             # ✅ ChromaDB vector indexing (VectorIndex)
│   ├── graph.py             # ✅ MAGMA 4-graph (temporal/entity/semantic/causal edges)
│   ├── entities.py          # ✅ Regex entity extractor (paths, URLs, CamelCase, terms)
│   ├── embeddings.py        # Ollama/OpenAI/local embedding providers
│   ├── retention.py         # ✅ 3-zone lifecycle (active → archive → purge)
│   └── antientropy.py       # ✅ Inbox suggestions, stale detection, duplicates, health check
├── mcp/
│   ├── server.py            # ✅ FastMCP server — 13 tools (all implemented)
│   ├── context_store.py     # ✅ Context-as-variable storage + 6 chunking strategies
│   ├── hooks.py             # ✅ TurnTracker, config generation, install functions
│   └── __main__.py          # ✅ Entry point for python -m anticlaw.mcp
├── providers/
│   ├── registry.py          # ✅ ProviderRegistry (unified for all 6 families)
│   ├── llm/
│   │   ├── base.py          # ✅ LLMProvider Protocol + ProviderInfo + Capability enum
│   │   ├── claude.py        # ✅ Parse conversations.json from export ZIP + scrubbing
│   │   ├── chatgpt.py       # ✅ Parse ChatGPT export ZIP (mapping-tree messages, Unix timestamps)
│   │   ├── gemini.py        # ✅ Parse Google Takeout Gemini export (per-folder JSON, multi-format)
│   │   └── ollama.py        # Local LLM Q&A
│   ├── backup/
│   │   ├── base.py          # ✅ BackupProvider Protocol + BackupResult + BackupInfo
│   │   ├── local.py         # ✅ LocalBackupProvider (shutil, incremental, snapshots)
│   │   ├── gdrive.py        # ✅ GDriveBackupProvider (google-api, OAuth2, MD5 incremental)
│   │   ├── s3.py            # boto3 (AWS/MinIO/B2/R2)
│   │   └── rsync.py         # shells out to rsync
│   ├── embedding/
│   │   ├── base.py          # ✅ EmbeddingProvider Protocol + EmbeddingInfo
│   │   ├── ollama.py        # ✅ OllamaEmbeddingProvider (nomic-embed-text, 768-dim)
│   │   └── local_model.py   # model2vec/fastembed (256-dim)
│   ├── source/
│   │   ├── base.py          # ✅ SourceProvider Protocol + SourceInfo
│   │   └── local_files.py   # ✅ LocalFilesProvider (recursive walk, SHA-256, PDF)
│   └── scraper/
│       ├── base.py          # ✅ ScraperProvider Protocol + ScraperInfo + ScrapedMapping
│       ├── claude.py        # ✅ ClaudeScraper (httpx, session cookie auth, chat→project mapping)
│       ├── chatgpt.py       # ChatGPT structure scraper
│       ├── gemini.py        # Gemini data scraper
│       └── perplexity.py    # Perplexity thread scraper
├── input/
│   ├── __init__.py          # ✅ Package init
│   ├── base.py              # ✅ InputProvider Protocol + InputInfo
│   └── whisper_input.py     # ✅ WhisperInputProvider (faster-whisper, VAD, push-to-talk)
├── llm/
│   ├── __init__.py           # ✅ Package init
│   ├── ollama_client.py      # ✅ OllamaClient: generate(), available_models(), is_available()
│   ├── summarizer.py         # ✅ summarize_chat, summarize_project via Ollama
│   ├── tagger.py             # ✅ auto_tag, auto_categorize via Ollama
│   └── qa.py                 # ✅ ask() — search KB + LLM answer with references
├── daemon/
│   ├── watcher.py           # ✅ watchdog file monitor (debounce, reindex, graph, draft detection)
│   ├── scheduler.py         # ✅ APScheduler cron jobs (7 built-in actions)
│   ├── tray.py              # ✅ pystray system tray (menu, notifications)
│   ├── ipc.py               # ✅ Unix socket / Named pipe (CLI ↔ daemon)
│   └── service.py           # ✅ Platform service registration (systemd/launchd/Windows)
├── sync/
│   ├── __init__.py          # ✅ Package init (API key warnings)
│   ├── providers.py         # ✅ SyncProvider Protocol + 4 adapters (Claude, OpenAI, Gemini, Ollama)
│   └── engine.py            # ✅ SyncEngine (push target hierarchy, send_chat, find/process drafts)
├── ui/
│   ├── __init__.py          # ✅ Package init
│   ├── app.py               # ✅ mount_ui() — Jinja2 + HTMX routes (dashboard/search/projects/inbox)
│   ├── templates/           # ✅ 8 templates (base, dashboard, search, projects, inbox, partials)
│   └── static/              # ✅ Static files directory (CSS/JS overrides)
└── cli/
    ├── main.py              # ✅ Click entry point + version
    ├── init_cmd.py           # ✅ aw init [path] [--interactive], config.yaml, .gitignore
    ├── import_cmd.py         # ✅ aw import claude <zip>, aw import chatgpt <zip>
    ├── search_cmd.py         # ✅ aw search <query> with filters
    ├── project_cmd.py        # ✅ aw list, show, move, tag, create, reindex
    ├── graph_cmd.py           # ✅ aw related, aw why, aw timeline
    ├── llm_cmd.py             # ✅ aw summarize, aw autotag, aw ask
    ├── knowledge_cmd.py      # ✅ aw inbox, stale, duplicates, health, retention, stats
    ├── scan_cmd.py           # ✅ aw scan [path] [--watch]
    ├── api_cmd.py            # ✅ aw api start [--port] [--host]
    ├── listen_cmd.py         # ✅ aw listen [--continuous] [--mode ask] (voice input)
    ├── clear_cmd.py          # ✅ aw clear [--all] (delete _inbox/_archive contents)
    ├── scraper_cmd.py        # ✅ aw scrape claude --session-key <KEY> [-o mapping.json]
    ├── provider_cmd.py       # aw providers ...
    ├── sync_cmd.py           # ✅ aw send <chat-id>, aw chat <project> (bidirectional sync)
    ├── daemon_cmd.py         # ✅ aw daemon start/stop/status/install/uninstall/logs
    ├── backup_cmd.py         # ✅ aw backup now/list/restore/verify/status
    ├── cron_cmd.py           # ✅ aw cron list/add/run/logs/remove
    └── mcp_cmd.py            # ✅ aw mcp start, install
```

## Key Naming Conventions

- **Package:** `anticlaw` (import anticlaw)
- **CLI command:** `aw` (pyproject.toml `[project.scripts]`)
- **Internal dirs:** `.acl/` (config, databases, cache)
- **Env var prefix:** `ACL_` (e.g. `ACL_HOME`)
- **MCP tool prefix:** `aw_` (e.g. `aw_search`, `aw_remember`)
- **Data home default:** `~/anticlaw/` (override via `ACL_HOME`)

## Coding Standards

- Python 3.10+ (use `X | Y` union syntax, not `Union[X, Y]`)
- Type hints on all public functions
- Dataclasses for models (not Pydantic in core — keep deps minimal)
- `Protocol` for provider contracts (runtime_checkable)
- Docstrings: one-line for simple functions, Google-style for complex
- f-strings, not .format()
- `pathlib.Path` everywhere, never raw string paths
- File permissions: 0o600 files, 0o700 dirs — enforced on every write
- Secrets: system keyring via `keyring` library, NEVER in config files
- Errors: custom exception hierarchy rooted at `AnticLawError`
- Logging: `logging` stdlib, logger per module (`__name__`)

## Common Commands

```bash
# Development
pip install -e ".[dev]"          # Install in dev mode
pip install -e ".[dev,llm]"      # Dev mode + LLM support (httpx for Ollama)
pytest                           # Run tests
pytest tests/unit/               # Unit tests only
ruff check src/                  # Lint
ruff format src/                 # Format

# CLI (after install)
aw --version                     # Version check
aw init                          # Initialize knowledge base
aw init --interactive            # Guided setup
aw import claude export.zip      # Import Claude export
aw import chatgpt export.zip    # Import ChatGPT export
aw import gemini takeout.zip    # Import Google Takeout Gemini export
aw search "query"                # Search knowledge base
aw list                          # List projects
aw summarize <chat-or-project>   # Generate/update summary via Ollama
aw autotag <chat-or-project>     # Auto-generate tags via Ollama
aw ask "question"                # Q&A over knowledge base via Ollama
aw related <node-id>             # Graph traversal from a node
aw why "decision"                # Trace causal chain
aw health                        # Check KB integrity
aw daemon start                  # Start background daemon
aw daemon status                 # Check daemon status
aw daemon install                # Register as system service
aw backup now                    # Run backup now
aw backup list                   # List backup snapshots
aw cron list                     # List cron tasks
aw cron run <task>               # Run a cron task now
aw ui                            # Start Web UI (opens browser)
aw ui --no-open                  # Start Web UI without opening browser
aw send <chat-id>                # Send chat to LLM API, append response
aw send <chat-id> -p ollama      # Send to specific provider
aw chat <project> -p ollama      # Interactive file-based chat
aw listen                        # Voice query → search results
aw listen --continuous           # Keep listening for queries
aw listen --mode ask             # Voice question → LLM answer
aw listen --model small          # Use larger Whisper model
aw clear                         # Delete all files in _inbox/ (with confirmation)
aw clear --all                   # Delete _inbox/ + _archive/ + rebuild index
aw scrape claude --session-key KEY  # Scrape chat→project mapping from claude.ai
aw scrape claude --session-key KEY -o map.json  # Custom output path
```

## File Format: Chat (.md)

```yaml
---
id: "acl-20250218-001"
title: "Auth discussion"
created: 2025-02-18T14:30:00Z
updated: 2025-02-20T09:15:00Z
provider: claude
remote_id: "28d595a3-..."
remote_project_id: "proj_abc123"
model: "claude-opus-4-6"
tags: [auth, jwt]
summary: "Chose JWT + refresh tokens."
token_count: 12450
message_count: 24
importance: high
status: active
---

## Human (14:30)
How should we implement auth?

## Assistant (14:31)
There are three main approaches...
```

## Current Phase

Phase 18 next (Alexa integration). Phase 17 complete.

### Completed
- **Phase 0:** Scaffolding — pyproject.toml, directory structure, `aw --version` ✅
- **Phase 1:** Core models + storage — dataclasses, ChatStorage, config loader, fileutil ✅
- **Phase 2:** Claude provider + import — ProviderRegistry, LLMProvider Protocol, ClaudeProvider, `aw import claude` ✅ (Note: export format lacks project mapping; all chats → _inbox/)
- **Phase 3:** SQLite metadata + basic search — MetaDB (WAL+FTS5), search dispatcher, `aw search`, `aw list/show/move/tag/create/reindex` ✅
- **Phase 4:** MCP server — FastMCP with 13 tools, context-store with 6 chunking strategies, TurnTracker, `aw mcp start/install` ✅
- **Phase 5:** Advanced search — Tiers 2-5 (BM25 via bm25s, fuzzy via rapidfuzz, semantic via ChromaDB+Ollama embeddings, hybrid fusion), EmbeddingProvider Protocol, OllamaEmbeddingProvider, VectorIndex, auto-tier selection, graceful degradation ✅
- **Phase 6:** Knowledge graph — MAGMA 4-graph (GraphDB with temporal/entity/semantic/causal edges), regex entity extractor, intent detection, auto-edge generation on remember, `aw related/why/timeline`, real `aw_related`/`aw_graph_stats` MCP tools ✅
- **Phase 7:** Local LLM integration — OllamaClient (HTTP API wrapper, graceful fallback), summarizer (chat + project), tagger (auto_tag + auto_categorize), Q&A (search + LLM answer with references), CLI: `aw summarize`, `aw autotag`, `aw ask` ✅
- **Phase 8:** Daemon + file watcher + backup + cron — FileWatcher (watchdog, debounce, reindex+graph on change), TaskScheduler (APScheduler, 7 built-in actions, cron.log, missed job handling), BackupProvider Protocol, LocalBackupProvider (shutil, incremental manifest, snapshots), GDriveBackupProvider (google-api, OAuth2, MD5 incremental), TrayIcon (pystray, menu), IPC (Unix socket/Named pipe, CLI↔daemon), ServiceManager (systemd/launchd/Windows), CLI: `aw daemon start/stop/status/install/uninstall/logs`, `aw backup now/list/restore/verify/status`, `aw cron list/add/run/logs/remove` ✅
- **Phase 9:** Retention + antientropy — 3-zone retention lifecycle (preview/run/restore, importance decay with half-life), antientropy features (inbox_suggestions via tag matching, find_stale, find_duplicates via semantic similarity, health_check with 4 checks), CLI: `aw inbox [--auto]`, `aw stale [--days]`, `aw duplicates`, `aw health`, `aw retention preview/run`, `aw restore`, `aw stats` ✅
- **Phase 10:** ChatGPT provider — ChatGPTProvider (parse ChatGPT export ZIP with mapping-tree message structure, Unix timestamps, role normalization user→human, model extraction from metadata, multipart/code content, system/tool message filtering), reuses scrub_text from Claude provider, CLI: `aw import chatgpt <zip> [--scrub]`, cross-provider search (results from both Claude and ChatGPT) ✅
- **Phase 11:** v1.0 release polish — version bump to 1.0.0, `aw init [path] [--interactive]` (guided setup, config.yaml generation, .gitignore), README.md with architecture diagram/feature list/quickstart/badges, docs/QUICKSTART.md (step-by-step guide), docs/TOOLS.md (MCP tool reference for Claude Code), PyPI metadata (classifiers, urls, license), pyproject.toml polished ✅
- **Phase 12:** Local file source + HTTP API — SourceProvider Protocol + SourceInfo, LocalFilesProvider (recursive walk, SHA-256 change detection, 30+ extensions, PDF via pymupdf, exclude patterns), SourceDocument dataclass, MetaDB source_files table + FTS5, search_unified() (chats+files+insights), FastAPI HTTP API (health/search/ask/projects/stats, API key auth, localhost bypass, CORS), CLI: `aw scan [path] [--watch]`, `aw api start [--port] [--host]`, config: sources + api sections, deps: `api` + `source-pdf` extras ✅
- **Phase 13:** Web UI — Jinja2 + HTMX + Tailwind CSS (CDN, no build tools), `mount_ui()` on FastAPI, 4 full-page routes (dashboard/search/projects/inbox), 2 HTMX partial routes (search results/project chats), stat cards, sidebar nav, search with project/type filters, `enable_ui` param on `create_app()`, CLI: `aw ui [--port] [--host] [--no-open]` (auto-opens browser), config: `ui` section, deps: `ui` extra (jinja2) ✅
- **Phase 14:** Bidirectional LLM sync — SyncProvider Protocol + 4 adapters (ClaudeAPI, OpenAIAPI, GeminiAPI, OllamaLocal) with httpx, SyncEngine (3-level push target hierarchy: frontmatter → _project.yaml → config.yaml, send_chat with response writeback, find/process drafts), daemon draft detection (auto_push_drafts config), CLI: `aw send <chat-id> [--provider]`, `aw chat <project> [--provider]` (interactive file-based chat), API key warnings (cloud requires separate paid keys), keyring integration, deps: `sync` extra (httpx) ✅
- **Phase 15:** Gemini provider — GeminiProvider (parse Google Takeout ZIP or extracted directory, per-conversation-folder structure with conversation.json, multi-format support: text/content/parts/chunkedPrompt, ISO+Unix timestamps, user/model→human/assistant role normalization, title from JSON or folder name, model extraction from conversation or message metadata), reuses scrub_text from Claude provider, CLI: `aw import gemini <takeout.zip-or-dir> [--scrub] [--home PATH]`, cross-provider search (results from Claude + ChatGPT + Gemini) ✅
- **Phase 16:** Voice input via Whisper — InputProvider Protocol + InputInfo (fifth provider family), WhisperInputProvider (faster-whisper CTranslate2 backend, models: tiny/base/small/medium, sounddevice recording, silence detection with auto-stop, push-to-talk mode, Russian + English auto-detect via Whisper), CLI: `aw listen` (single query → search → results), `aw listen --continuous` (loop mode), `aw listen --mode ask` (voice Q&A via Ollama), `--model`/`--language`/`--push-to-talk` overrides, graceful fallback when faster-whisper/sounddevice not installed, config: `voice` section (model, language, push_to_talk, silence_threshold, max_duration), deps: `voice` extra (faster-whisper, sounddevice, numpy) ✅
- **Phase 17:** Playwright scraper for chat→project mapping — ScraperProvider Protocol + ScraperInfo + ScrapedMapping (sixth provider family), ClaudeScraper (Playwright CDP, response interception for org_id, page.evaluate() with offset-based pagination for chat_conversations, starred + unstarred fetch, project info from chat objects), mapping.json output format (`{chats, projects, scraped_at}`), load_project_mapping supports both new and legacy formats, CLI: `aw scrape claude [--cdp-url] [-o mapping.json]`, docs/SCRAPER.md, deps: `scraper` extra (playwright) ✅

### Test coverage
993 unit tests passing (models, fileutil, storage, config, registry, claude provider, chatgpt provider, gemini provider, import CLI (claude + chatgpt + gemini), cross-provider import (3-provider), init CLI, meta_db, search, search CLI, project CLI, context store, hooks, MCP tools, MCP CLI, embedding provider, vector index, advanced search tiers, fallback behavior, entities, graph, graph CLI, ollama client, summarizer, tagger, Q&A, LLM CLI, backup base, backup local, backup gdrive, watcher, watcher draft detection, scheduler, IPC, service, daemon CLI, backup CLI, cron CLI, retention, antientropy, knowledge CLI, source models, local files provider, meta_db source files, search unified, scan CLI, API server, UI routes, sync providers, sync engine, sync CLI, input base, whisper input, listen CLI, clear CLI, scraper base, scraper claude, scraper CLI).

## Specs

Full specification: `docs/SPEC.md`
Implementation plan: `docs/PLAN.md`
Provider architecture: `docs/PROVIDERS.md`

Read these files BEFORE implementing any phase. They contain exact data models, CLI signatures, provider contracts, and architectural decisions.

## Important Rules

1. **Read the spec first.** Before writing code for any phase, read the relevant sections of SPEC.md and PLAN.md.
2. **File-first philosophy.** The file system is the source of truth. SQLite/ChromaDB are indexes that can be rebuilt from files.
3. **Graceful degradation.** Core features must work with zero optional deps. Each pip extra unlocks better capabilities.
4. **No network by default.** Core operations never call external services. Ollama/cloud providers are opt-in.
5. **Security from day one.** File permissions, keyring for secrets, content scrubbing on import.
6. **Tests for every module.** Write tests alongside code, not after. Minimum: happy path + error case.
7. **After completing a task**, update this file's "Current Phase" section if the phase changed.

## Planned Features (post-Phase 17)

Key upcoming features documented in PLAN.md and SPEC.md:
- **Phase 15:** ~~Gemini provider — Google Takeout import (`aw import gemini`)~~ (done)
- **Phase 16:** ~~Voice input via Whisper (`aw listen`)~~ (done)
- **Phase 17:** ~~HTTP scraper — chat→project mapping (`aw scrape claude`)~~ (done)
- **Phase 18:** Alexa integration
- **Scraper providers:** Additional scrapers (chatgpt, gemini, perplexity) via httpx
- **6 provider families:** LLM, Backup, Embedding, Source, Input, Scraper

## Environment Rules

- If a required tool (Python, Ollama, Git) is not available, STOP immediately and give the user exact install instructions for their OS. Do NOT search the filesystem or attempt workarounds.
- Always check `python --version` and `pip --version` before running tests or installs.
