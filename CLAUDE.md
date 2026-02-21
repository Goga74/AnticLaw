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
│   └── retention.py         # 3-zone lifecycle (active → archive → purge)
├── mcp/
│   ├── server.py            # ✅ FastMCP server — 13 tools (all implemented)
│   ├── context_store.py     # ✅ Context-as-variable storage + 6 chunking strategies
│   ├── hooks.py             # ✅ TurnTracker, config generation, install functions
│   └── __main__.py          # ✅ Entry point for python -m anticlaw.mcp
├── providers/
│   ├── registry.py          # ✅ ProviderRegistry (unified for all 3 families)
│   ├── llm/
│   │   ├── base.py          # ✅ LLMProvider Protocol + ProviderInfo + Capability enum
│   │   ├── claude.py        # ✅ Parse conversations.json from export ZIP + scrubbing
│   │   ├── chatgpt.py       # Parse ChatGPT export
│   │   └── ollama.py        # Local LLM Q&A
│   ├── backup/
│   │   ├── base.py          # BackupProvider Protocol
│   │   ├── local.py         # shutil.copytree snapshots
│   │   ├── gdrive.py        # Google Drive API
│   │   ├── s3.py            # boto3 (AWS/MinIO/B2/R2)
│   │   └── rsync.py         # shells out to rsync
│   └── embedding/
│       ├── base.py          # ✅ EmbeddingProvider Protocol + EmbeddingInfo
│       ├── ollama.py        # ✅ OllamaEmbeddingProvider (nomic-embed-text, 768-dim)
│       └── local_model.py   # model2vec/fastembed (256-dim)
├── llm/
│   ├── __init__.py           # ✅ Package init
│   ├── ollama_client.py      # ✅ OllamaClient: generate(), available_models(), is_available()
│   ├── summarizer.py         # ✅ summarize_chat, summarize_project via Ollama
│   ├── tagger.py             # ✅ auto_tag, auto_categorize via Ollama
│   └── qa.py                 # ✅ ask() — search KB + LLM answer with references
├── daemon/
│   ├── watcher.py           # watchdog file monitor
│   ├── scheduler.py         # APScheduler cron jobs
│   ├── tray.py              # pystray system tray
│   └── ipc.py               # Unix socket / Named pipe
├── ui/
│   ├── app.py               # FastAPI mount for SPA + API routes
│   └── static/              # Pre-built SPA bundle
└── cli/
    ├── main.py              # ✅ Click entry point + version
    ├── import_cmd.py         # ✅ aw import claude <zip>
    ├── search_cmd.py         # ✅ aw search <query> with filters
    ├── project_cmd.py        # ✅ aw list, show, move, tag, create, reindex
    ├── graph_cmd.py           # ✅ aw related, aw why, aw timeline
    ├── llm_cmd.py             # ✅ aw summarize, aw autotag, aw ask
    ├── knowledge_cmd.py      # aw inbox, stale, duplicates ...
    ├── provider_cmd.py       # aw providers ...
    ├── daemon_cmd.py         # aw daemon ...
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
pytest                           # Run tests
pytest tests/unit/               # Unit tests only
ruff check src/                  # Lint
ruff format src/                 # Format

# CLI (after install)
aw --version                     # Version check
aw import claude export.zip      # Import Claude export
aw search "query"                # Search knowledge base
aw list                          # List projects
aw health                        # Check KB integrity
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

Phase 7 complete. Next: Phase 8 (Daemon + File Watcher).

### Completed
- **Phase 0:** Scaffolding — pyproject.toml, directory structure, `aw --version` ✅
- **Phase 1:** Core models + storage — dataclasses, ChatStorage, config loader, fileutil ✅
- **Phase 2:** Claude provider + import — ProviderRegistry, LLMProvider Protocol, ClaudeProvider, `aw import claude` ✅
- **Phase 3:** SQLite metadata + basic search — MetaDB (WAL+FTS5), search dispatcher, `aw search`, `aw list/show/move/tag/create/reindex` ✅
- **Phase 4:** MCP server — FastMCP with 13 tools, context-store with 6 chunking strategies, TurnTracker, `aw mcp start/install` ✅
- **Phase 5:** Advanced search — Tiers 2-5 (BM25 via bm25s, fuzzy via rapidfuzz, semantic via ChromaDB+Ollama embeddings, hybrid fusion), EmbeddingProvider Protocol, OllamaEmbeddingProvider, VectorIndex, auto-tier selection, graceful degradation ✅
- **Phase 6:** Knowledge graph — MAGMA 4-graph (GraphDB with temporal/entity/semantic/causal edges), regex entity extractor, intent detection, auto-edge generation on remember, `aw related/why/timeline`, real `aw_related`/`aw_graph_stats` MCP tools ✅
- **Phase 7:** Local LLM integration — OllamaClient (HTTP API wrapper, graceful fallback), summarizer (chat + project), tagger (auto_tag + auto_categorize), Q&A (search + LLM answer with references), CLI: `aw summarize`, `aw autotag`, `aw ask` ✅

### Test coverage
395 unit tests passing (models, fileutil, storage, config, registry, claude provider, import CLI, meta_db, search, search CLI, project CLI, context store, hooks, MCP tools, MCP CLI, embedding provider, vector index, advanced search tiers, fallback behavior, entities, graph, graph CLI, ollama client, summarizer, tagger, Q&A, LLM CLI).

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
