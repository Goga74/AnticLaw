# AnticLaw

<!-- Badges -->
[![PyPI version](https://img.shields.io/pypi/v/anticlaw)](https://pypi.org/project/anticlaw/)
[![Python 3.10+](https://img.shields.io/pypi/pyversions/anticlaw)](https://pypi.org/project/anticlaw/)
[![Tests](https://img.shields.io/github/actions/workflow/status/izamiatin/anticlaw/ci.yml?label=tests)](https://github.com/izamiatin/anticlaw/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Local-first knowledge base for LLM conversations.**

AnticLaw (`aw` CLI) manages exported LLM conversations (Claude, ChatGPT, Gemini) as local Markdown files with YAML frontmatter. Files are the source of truth. LLMs are interchangeable clients.

## Why AnticLaw?

- **You own your data.** Conversations live as plain Markdown files on your disk — greppable, version-controllable, readable without any tool.
- **Cross-platform search.** Import from Claude *and* ChatGPT, search across everything with one command.
- **MCP integration.** 13 tools that let Claude Code / Cursor access your knowledge base directly.
- **No cloud required.** Core features work offline. Ollama powers local summarization, tagging, and Q&A.
- **Knowledge graph.** Automatic entity extraction, causal chains, temporal links between your conversations.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│           CLI (aw) / MCP Server (13 tools)          │
├─────────────────────────────────────────────────────┤
│                    Core Engine                       │
│  Import ─► Storage ─► Index ─► Search ─► Graph      │
├──────────────┬──────────────────┬───────────────────┤
│  Local LLM   │  Vector + Meta   │  File System      │
│  (Ollama)    │  (ChromaDB +     │  (Markdown +      │
│  summarize   │   SQLite FTS5)   │   YAML front-     │
│  tag, Q&A    │                  │   matter)         │
├──────────────┴──────────────────┴───────────────────┤
│  Providers: Claude │ ChatGPT │ Gemini │ Ollama      │
└─────────────────────────────────────────────────────┘
```

**Data directory** (`~/anticlaw/` by default):

```
~/anticlaw/
├── .acl/               # Config, databases, cache
│   ├── config.yaml     # Settings
│   ├── meta.db         # SQLite FTS5 metadata index
│   └── graph.db        # Knowledge graph
├── _inbox/             # Imported chats (unsorted)
├── _archive/           # Archived chats
├── project-alpha/      # Your projects
│   ├── _project.yaml   # Project metadata
│   └── 2025-02-18_auth-discussion.md
└── .gitignore
```

## Installation

```bash
pip install anticlaw                       # Core (import, search, MCP)
pip install anticlaw[search]               # + BM25 ranked search
pip install anticlaw[search,fuzzy]         # + typo-tolerant search
pip install anticlaw[search,semantic,llm]  # + vector search + Ollama
pip install anticlaw[all]                  # Everything
```

### Development

```bash
git clone https://github.com/izamiatin/anticlaw.git
cd anticlaw
pip install -e ".[dev,llm]"
pytest
```

## Quick Start

```bash
# 1. Initialize knowledge base
aw init

# 2. Import your conversations
aw import claude ~/Downloads/claude-export.zip
aw import chatgpt ~/Downloads/chatgpt-export.zip

# 3. Search across everything
aw search "authentication"
aw search "JWT" --project project-alpha

# 4. Organize
aw list                          # List projects
aw create project "Auth System"  # Create a project
aw move 2025-02-18_auth.md auth-system  # Move chat to project
aw tag 2025-02-18_auth.md jwt security  # Add tags

# 5. Knowledge graph
aw related <insight-id>          # Find connected insights
aw why "chose JWT"               # Trace decisions
aw timeline project-alpha        # Temporal view

# 6. Local AI (requires Ollama)
aw summarize project-alpha       # Generate summaries
aw autotag project-alpha         # Auto-generate tags
aw ask "what auth approach did we choose?"

# 7. Knowledge management
aw inbox                         # See suggestions for unsorted chats
aw health                        # Check KB integrity
aw stats                         # Global statistics
```

## MCP Integration

Connect AnticLaw to Claude Code so it can access your knowledge base:

```bash
aw mcp install claude-code
```

This gives Claude Code 13 tools: `aw_search`, `aw_remember`, `aw_recall`, `aw_forget`, `aw_load_context`, `aw_chunk_context`, `aw_related`, `aw_projects`, and more.

See [docs/TOOLS.md](docs/TOOLS.md) for the full MCP tool reference.

## Features

### Import & Storage
- Import Claude.ai and ChatGPT data exports (ZIP)
- Markdown + YAML frontmatter — human-readable, git-friendly
- Secret scrubbing (API keys, passwords) on import
- Duplicate detection on re-import

### Search (5-tier)
| Tier | Engine | Needs |
|------|--------|-------|
| Keyword | SQLite FTS5 | Core |
| BM25 | bm25s | `pip install anticlaw[search]` |
| Fuzzy | RapidFuzz | `pip install anticlaw[fuzzy]` |
| Semantic | ChromaDB + Ollama | `pip install anticlaw[semantic]` |
| Hybrid | Fusion of all tiers | All extras |

### Knowledge Graph (MAGMA)
- 4 edge types: temporal, entity, semantic, causal
- Automatic entity extraction (paths, URLs, terms)
- Decision tracing with `aw why`

### Local LLM (Ollama)
- Chat/project summarization
- Automatic tag generation
- Q&A over your knowledge base with source references
- No data leaves your machine

### Background Daemon
- File watcher with auto-indexing
- Cron scheduler (7 built-in actions)
- System tray with notifications
- System service registration (systemd/launchd/Windows)

### Backup
- Local incremental backups with snapshots
- Google Drive backup (OAuth2, MD5 incremental)

### Retention & Health
- 3-zone lifecycle: active → archive → purge
- Importance decay with configurable half-life
- Stale project detection, duplicate finding
- Inbox suggestions for unsorted chats

## File Format

Each chat is a Markdown file with YAML frontmatter:

```yaml
---
id: "acl-20250218-001"
title: "Auth discussion"
created: 2025-02-18T14:30:00Z
provider: claude
model: "claude-opus-4-6"
tags: [auth, jwt]
summary: "Chose JWT + refresh tokens."
status: active
---

## Human (14:30)
How should we implement auth?

## Assistant (14:31)
There are three main approaches...
```

## Configuration

Config lives at `~/anticlaw/.acl/config.yaml`:

```yaml
search:
  max_results: 20
embeddings:
  provider: ollama
  model: nomic-embed-text
llm:
  provider: ollama
  model: llama3.1:8b
providers:
  claude:
    enabled: true
  chatgpt:
    enabled: true
daemon:
  enabled: false
```

Override data location with `ACL_HOME` environment variable.

## Documentation

- [Quick Start Guide](docs/QUICKSTART.md) — Install to first search in 5 minutes
- [MCP Tools Reference](docs/TOOLS.md) — All 13 MCP tools for Claude Code
- [Full Specification](docs/SPEC.md) — Architecture, data models, provider contracts
- [Implementation Plan](docs/PLAN.md) — Phase-by-phase development roadmap

## License

MIT
