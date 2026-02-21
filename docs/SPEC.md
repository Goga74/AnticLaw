# AnticLaw — Project Specification

**Version:** 0.1-draft  
**Date:** 2025-02-20  
**Status:** Design phase

---

## 1. Philosophy

**AnticLaw** is a local-first knowledge base management system that treats the user's file system as the source of truth and cloud LLMs as interchangeable clients.

### Core Principles

1. **Files are the source of truth.** Folder = project, file = chat. Everything is readable, greppable, version-controllable with git.
2. **LLMs are clients, not masters.** Claude, ChatGPT, Gemini, local Ollama — all are "windows" into the same knowledge base. None owns the data.
3. **Local LLM is the administrator.** Search, summarization, classification, tagging — all run locally without sending data to the cloud.
4. **AnticLaw = active knowledge management.** Not a dump of chats, but a living structure: tags, cross-links, auto-summaries, duplicate detection, stale project alerts.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                   CLI (ae) / TUI / Web UI               │
│  aw import claude export.zip                            │
│  aw search "авторизация"                                │
│  aw move chat-123 project-alpha                         │
│  aw ask "what decisions did we make about auth?"        │
├─────────────────────────────────────────────────────────┤
│                   Core Engine (Python)                   │
│  - Project / Chat / Message CRUD                        │
│  - Import / Export pipeline                             │
│  - Auto-summarize, auto-tag, auto-link                  │
│  - Conflict resolution                                  │
│  - Retention lifecycle (active → archive → purge)       │
├─────────────────────────────────────────────────────────┤
│               MCP Server (FastMCP, stdio)                │
│  Exposes tools to Claude Code / Cursor / Codex:         │
│  load_context, search, save, recall, related, ...       │
├────────────────────┬────────────────────────────────────┤
│  Local LLM         │  Vector DB + Metadata DB           │
│  (Ollama)          │  (ChromaDB + SQLite)               │
│  - embeddings      │  - semantic index                  │
│  - summarization   │  - FTS5 full-text index            │
│  - Q&A over KB     │  - MAGMA knowledge graph           │
│  - classification  │  - metadata, tags, links           │
├────────────────────┴────────────────────────────────────┤
│               File System (source of truth)              │
│  ~/anticlaw/                                         │
│  ├── .acl/              # config, databases, index       │
│  ├── project-alpha/    # folder = project               │
│  │   ├── _project.yaml                                  │
│  │   ├── 2025-02-18_auth-discussion.md                  │
│  │   └── 2025-02-20_api-design.md                       │
│  └── _inbox/           # unprocessed chats              │
├─────────────────────────────────────────────────────────┤
│               Provider Modules                           │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌──────────┐     │
│  │ Claude  │ │ ChatGPT │ │ Gemini  │ │  Ollama  │     │
│  │ Provider│ │ Provider│ │ Provider│ │  Provider│     │
│  └─────────┘ └─────────┘ └─────────┘ └──────────┘     │
│  Each: import, export, sync, map project                │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Directory Structure

```
~/anticlaw/                          # ACL_HOME (configurable)
├── .acl/                                # Internal data (gitignored)
│   ├── config.yaml                     # Global configuration
│   ├── meta.db                         # SQLite: metadata, tags, links, sessions
│   ├── graph.db                        # SQLite: MAGMA knowledge graph
│   ├── vectors/                        # ChromaDB persistent storage
│   └── cache/                          # Embedding cache (diskcache)
│
├── project-alpha/                      # Project = folder
│   ├── _project.yaml                   # Project metadata
│   ├── 2025-02-18_auth-discussion.md   # Chat = file
│   ├── 2025-02-20_api-design.md
│   └── _knowledge/                     # Project Knowledge files (optional)
│       └── architecture.md
│
├── project-beta/
│   └── ...
│
├── _inbox/                             # Unprocessed / uncategorized chats
│   └── 2025-01-10_untitled.md
│
└── _archive/                           # Archived projects and chats
    └── old-project/
```

---

## 4. File Formats

### 4.1 Chat file (Markdown + YAML frontmatter)

```yaml
# ~/anticlaw/project-alpha/2025-02-18_auth-discussion.md

---
id: "ae-20250218-001"
title: "Auth discussion: JWT vs sessions"
created: 2025-02-18T14:30:00Z
updated: 2025-02-20T09:15:00Z
provider: claude
remote_id: "28d595a3-5db0-492d-a49a-af74f13de505"
remote_project_id: "proj_abc123"
model: "claude-opus-4-6"
tags: [auth, jwt, security, api]
summary: "Chose JWT + refresh tokens over sessions. Key reasons: stateless, scalable, mobile-friendly."
token_count: 12450
message_count: 24
importance: high
status: active          # active | archived | purged
---

## Human (14:30)
How should we implement auth for our API?

## Assistant (14:31)
There are three main approaches...

## Human (14:35)
Let's go with JWT. What about refresh tokens?

## Assistant (14:36)
Good choice. Here's the implementation plan...
```

**Design decisions:**
- YAML frontmatter: machine-parseable metadata, supported by Obsidian, VS Code, Hugo, etc.
- Markdown body: human-readable, greppable, diffable.
- Timestamp per message: enables temporal analysis.
- `remote_id` + `provider`: bidirectional mapping to cloud LLM.
- `summary`: auto-generated by local LLM on import, updatable.

### 4.2 Project metadata (_project.yaml)

```yaml
# ~/anticlaw/project-alpha/_project.yaml

name: "Project Alpha"
description: "Main product API development"
created: 2025-01-15T10:00:00Z
updated: 2025-02-20T09:15:00Z
tags: [api, backend, python]
status: active

# Provider mappings (one project can map to multiple LLMs)
providers:
  claude:
    project_id: "proj_abc123"
    project_name: "Alpha API"
    last_sync: 2025-02-20T09:00:00Z
  chatgpt:
    project_id: null           # not mapped yet
  ollama:
    default_model: "llama3.1:8b"

# Project-level settings
settings:
  auto_summarize: true
  auto_tag: true
  retention_days: 90           # override global setting
```

---

## 5. Provider Modules

### 5.1 Provider Interface

Every LLM provider implements a common Protocol. Providers declare capabilities via `ProviderInfo` — not every provider supports every method. See `providers/llm/base.py` for the actual implementation and `docs/PROVIDERS.md` for the full three-family architecture (LLM, Backup, Embedding).

```python
# src/anticlaw/providers/llm/base.py (actual implementation)

from pathlib import Path
from typing import Protocol, runtime_checkable
from anticlaw.core.models import ChatData, RemoteProject, RemoteChat, SyncResult

@runtime_checkable
class LLMProvider(Protocol):
    """Contract for LLM platform integration."""

    @property
    def name(self) -> str:
        """Unique provider ID: 'claude', 'chatgpt', 'gemini', 'ollama'."""
        ...

    @property
    def info(self) -> ProviderInfo:
        """Display name, version, capabilities."""
        ...

    def auth(self, config: dict) -> bool:
        """Verify credentials / connectivity."""
        ...

    def list_projects(self) -> list[RemoteProject]:
        """List all projects on the remote platform."""
        ...

    def list_chats(self, project_id: str | None = None) -> list[RemoteChat]:
        """List chats, optionally filtered by project."""
        ...

    def export_chat(self, chat_id: str) -> ChatData:
        """Export a single chat with all messages."""
        ...

    def import_chat(self, project_id: str | None, chat: ChatData) -> str:
        """Import a chat into the remote platform. Returns remote chat ID."""
        ...

    def export_all(self, output_dir: Path) -> int:
        """Bulk export. Returns number of chats exported."""
        ...

    def sync(
        self, local_project: Path, remote_project_id: str,
        direction: str = "pull",
    ) -> SyncResult:
        """Sync between local folder and remote project."""
        ...
```

### 5.2 Claude Provider

**Import sources:**
1. **Official export** (primary): Settings → Privacy → Export Data → ZIP with `conversations.json`. Parses JSON, maps to chat files. Project mapping obtained via Playwright (one-time scrape of sidebar structure).
2. **Playwright scraper** (supplementary): One-time collection of project→chat mapping, Project Knowledge files, system prompts.

**Export format (conversations.json):**
```json
[
  {
    "uuid": "28d595a3-...",
    "name": "Auth Discussion",
    "created_at": "2025-02-18T14:30:00.000Z",
    "chat_messages": [
      {"sender": "human", "text": "..."},
      {"sender": "assistant", "text": "..."}
    ]
  }
]
```

**Known limitations:**
- Project membership (chat→project link) may not be in export — requires Playwright supplement.
- Project Knowledge files not exported — requires Playwright.
- Deleted chats not included.

### 5.3 ChatGPT Provider

**Import source:** Settings → Data controls → Export data → ZIP with `conversations.json`.

Different JSON schema from Claude — separate parser needed. Same output: `.md` files with YAML frontmatter.

### 5.4 Gemini Provider

**Import source:** Google Takeout → Gemini data.

Lower priority. Placeholder for v0.4+.

### 5.5 Ollama Provider

Special case — not a cloud platform. Functions:
- `import_chat`: Load a chat file as context for local Q&A session.
- `export_chat`: Save local Ollama session as a chat file.
- `ask`: Q&A over the knowledge base using local LLM.
- `summarize`: Generate summary for a chat or project.

---

## 6. Search System (5-Tier)

Inspired by MemCP's tiered search architecture. Single entry point (`aw search`), auto-selects best available tier. Graceful degradation: works with zero optional deps (Tier 1), each extra unlocks better search.

```
Query → Tier 5 (hybrid) if available
       → Tier 4 (semantic) if embeddings available
       → Tier 3 (fuzzy) if rapidfuzz installed
       → Tier 2 (BM25) if bm25s installed
       → Tier 1 (keyword) always available
```

### Tier 1: Keyword (SQLite FTS5)

- **How:** Full-text search via SQLite FTS5 MATCH with BM25 ranking. Searches across chat titles, summaries, message content, and tags.
- **Deps:** None (FTS5 is built into Python's sqlite3 module).
- **When:** Always available as fallback.
- **Features:** Multi-word AND queries, exact phrase matching (`--exact`), ranked results with snippets.
- **Limitation:** No typo tolerance, no semantic understanding.

### Tier 2: BM25 (bm25s)

- **How:** TF-IDF-based ranked search. Rare terms weighted higher.
- **Deps:** `bm25s` (~5 MB).
- **When:** `pip install anticlaw[search]`.
- **Strength:** Good ranking for keyword queries.

### Tier 3: Fuzzy (rapidfuzz)

- **How:** Levenshtein distance. Tolerates typos.
- **Deps:** `rapidfuzz` (~2 MB).
- **When:** `pip install anticlaw[fuzzy]`.
- **Strength:** "autentication" → finds "authentication".

### Tier 4: Semantic (embeddings)

- **How:** Vector embeddings via Ollama + nomic-embed-text. Cosine similarity.
- **Deps:** `numpy` + running Ollama with `nomic-embed-text` model.
- **When:** `pip install anticlaw[semantic]` + `ollama pull nomic-embed-text`.
- **Strength:** "why did we pick a database?" → finds "Decided on SQLite for graph storage".
- **Storage:** ChromaDB for vector persistence.

### Tier 5: Hybrid Fusion

- **How:** Combines BM25 score + semantic score.
- **Formula:** `score = α × semantic + (1-α) × BM25`, where `α` defaults to 0.6.
- **Deps:** All of the above.
- **Config:** `ACL_SEARCH_ALPHA=0.6` in config.yaml.

### Search scope

Searches across:
- Chat content (messages).
- Chat metadata (title, tags, summary).
- Project metadata (name, description, tags).
- Knowledge graph insights.

### Token budgeting

`aw search --max-tokens 2000 "auth"` — caps total output to fit within a context window. Critical for MCP tool usage.

---

## 7. Knowledge Graph (MAGMA)

Based on MAGMA (Multi-Agent Graph Memory Architecture). SQLite-backed graph with 4 edge types.

### Nodes

Every chat summary, key decision, or explicitly saved insight becomes a node:

```
Node {
    id: UUID
    content: str               # The insight text
    category: str              # decision | finding | preference | fact | question
    importance: str            # low | medium | high | critical
    tags: list[str]
    project_id: str            # Link to project
    chat_id: str | None        # Link to source chat
    created: datetime
    updated: datetime
    status: str                # active | archived | purged
}
```

### 4 Edge Types

#### 1. Temporal edges

Auto-generated between nodes created within a configurable time window (default: 30 min).

```
Node A (14:00) ──temporal──► Node B (14:25)
```

**Query intent detection:** "when", "когда", "timeline", "sequence" → prioritize temporal traversal.

#### 2. Entity edges

Auto-extracted entities (files, modules, URLs, CamelCase names, technical terms) link nodes that mention the same entity.

```
Node "Use SQLite for graph" ──entity:SQLite──► Node "SQLite WAL mode for concurrency"
```

**Extraction methods:**
- Regex-based (fast, always available): file paths, URLs, CamelCase identifiers.
- LLM-based (optional, via Ollama): complex entity extraction.

#### 3. Semantic edges

On node creation: compute embedding → find top-3 most similar existing nodes → create weighted edges.

```
Node "Chose SQLite for storage" ──semantic(0.87)──► Node "Database should be embedded"
```

**Requires:** Ollama + nomic-embed-text.

#### 4. Causal edges

Detected by keywords: "because", "therefore", "fixed by", "caused by", "решили потому что", "из-за", "в результате".

```
Node "Found race condition in writer" ──causal──► Node "Fixed with flock"
```

**Query intent detection:** "why", "почему", "reason", "cause" → prioritize causal traversal.

### Graph operations

| Operation | Description |
|-----------|-------------|
| `aw related <node-id>` | Traverse from a node, filter by edge type |
| `aw graph-stats` | Node count, edge counts by type, top entities |
| `aw graph-viz` | Export to Mermaid / DOT for visualization |
| `aw why "decision X"` | Shortcut: causal traversal from matching nodes |
| `aw timeline project-alpha` | Temporal traversal of all project nodes |

---

## 8. MCP Server

FastMCP-based stdio server. Connects to Claude Code, Cursor, Codex — any MCP-compatible client. All clients share the same knowledge base.

### Registration

```bash
# Claude Code
aw mcp install claude-code          # writes to ~/.claude/mcp_servers.json

# Cursor
aw mcp install cursor               # writes to ~/.cursor/mcp.json

# Manual
claude mcp add anticlaw -s user -- python -m anticlaw.mcp
```

### Tool Catalog (13 tools)

Inspired by MemCP, but adapted for AnticLaw's project-centric model.

#### Core Memory (4 tools)

| # | Tool | Description |
|---|------|-------------|
| 1 | `aw_ping` | Health check. Returns server status, project count, insight count. |
| 2 | `aw_remember` | Save an insight: text + category + importance + tags + project_id. Creates graph node + auto-edges. **Tool description includes: "You MUST call this before ending any session where you made decisions or learned something."** |
| 3 | `aw_recall` | Retrieve insights. Filters: query, project, category, importance, max_tokens. Intent-aware: "why X?" follows causal edges. |
| 4 | `aw_forget` | Remove an insight by ID. |

#### Context Management (5 tools)

| # | Tool | Description |
|---|------|-------------|
| 5 | `aw_load_context` | Store large content as named variable on disk. Claude sees only metadata (name, type, size, token count). |
| 6 | `aw_inspect_context` | Show metadata + preview of a stored context without loading it. |
| 7 | `aw_get_context` | Read stored context content, or a specific line range. |
| 8 | `aw_chunk_context` | Split context into numbered chunks. Strategies: auto, lines, paragraphs, headings, chars, regex. |
| 9 | `aw_peek_chunk` | Read a specific chunk by number. |

#### Search (1 tool)

| # | Tool | Description |
|---|------|-------------|
| 10 | `aw_search` | Unified search across all chats, insights, and contexts. Auto-selects best tier. `max_tokens` parameter for budget control. |

#### Graph (2 tools)

| # | Tool | Description |
|---|------|-------------|
| 11 | `aw_related` | Traverse graph from an insight. Filter by edge type (semantic / temporal / causal / entity). |
| 12 | `aw_graph_stats` | Graph statistics: node count, edge counts by type, top entities, project distribution. |

#### Project (1 tool)

| # | Tool | Description |
|---|------|-------------|
| 13 | `aw_projects` | List all projects with insight count, chat count, last activity. |

### Hooks

Merged into `~/.claude/settings.json`:

| Hook | Trigger | Behavior |
|------|---------|----------|
| PreCompact | Before `/compact` | Blocks until agent calls `aw_remember` to save context. |
| AutoReminder | Every 10/20/30 turns | Progressive reminders: "Consider saving context" → "You should save now" → "SAVE REQUIRED". |
| PostSave | After `aw_remember` | Resets turn counter. |

---

## 9. Local LLM Integration (Ollama)

### Models

| Purpose | Model | Size | Why |
|---------|-------|------|-----|
| Embeddings | `nomic-embed-text` | ~275 MB | 768-dim, excellent quality, local, fast |
| Summarization | `llama3.1:8b` or `qwen2.5:7b` | ~4.7 GB | Good balance of quality and speed |
| Q&A over KB | Same as summarization | — | Reuses the same model |
| Classification / tagging | Same as summarization | — | Reuses the same model |

### Operations

```bash
# Auto-summarize a chat on import
aw import claude export.zip --summarize

# Summarize a specific project
aw summarize project-alpha

# Ask a question over the knowledge base
aw ask "what auth approach did we choose and why?"

# Auto-tag untagged chats
aw autotag _inbox/

# Detect duplicates
aw duplicates
```

---

## 10. CLI Reference (aw)

### Import / Export

```bash
aw import claude <export.zip>          # Import from Claude.ai export
aw import chatgpt <export.zip>        # Import from ChatGPT export
aw import file <path.md>              # Import a standalone markdown file
aw export project-alpha --format json # Export project as JSON
aw export --all --format zip          # Export entire KB
```

### Project Management

```bash
aw list                               # List all projects (from meta.db index)
aw list project-alpha                 # List chats in a project
aw show <chat-id>                     # Display a chat (supports partial ID)
aw create project "New Project"       # Create a new project
aw move <chat-id> <project>           # Move chat between projects
aw tag <chat-id> auth security        # Add tags
aw reindex                            # Rebuild search index from filesystem
aw rename <chat-id> "New title"       # Rename a chat (planned)
aw untag <chat-id> security           # Remove tag (planned)
aw link <chat-A> <chat-B>            # Create cross-reference (planned)
```

### Search & Discovery

```bash
aw search "авторизация"               # FTS5 keyword search (Tier 1)
aw search --exact "JWT"               # Exact phrase match
aw search --project alpha "tokens"    # Scope to project
aw search --tag security "auth"       # Filter by tag
aw search --max-results 10 "auth"     # Limit results
aw search --max-tokens 2000 "auth"    # Token-budgeted search (planned)
aw related <node-id>                  # Graph traversal (planned)
aw why "chose SQLite"                 # Causal chain lookup (planned)
aw timeline project-alpha             # Chronological view (planned)
```

### Knowledge Management (AnticLaw)

```bash
aw inbox                              # Show unprocessed chats with suggestions
aw stale                              # Projects with no activity >N days
aw duplicates                         # Detect similar/duplicate chats
aw summarize <project>                # Generate/update project summary
aw autotag <chat-or-project>          # Auto-generate tags via LLM
aw stats                              # Global KB statistics
aw health                             # Check for issues (orphans, missing meta, etc.)
```

### MCP Server

```bash
aw mcp start                          # Start MCP server (stdio)
aw mcp install claude-code            # Register with Claude Code
aw mcp install cursor                 # Register with Cursor
```

### Provider Sync

```bash
aw sync claude                        # Sync with Claude.ai
aw sync chatgpt                       # Sync with ChatGPT
aw providers                          # List configured providers
```

---

## 11. Retention Lifecycle

Three-zone model (inspired by MemCP):

```
┌──────────┐    30 days    ┌──────────┐    180 days    ┌──────────┐
│  Active  │──────────────►│ Archive  │───────────────►│  Purge   │
│          │               │(compress)│                │ (logged) │
└──────────┘               └──────────┘                └──────────┘
      ▲                         │
      │     aw restore          │
      └─────────────────────────┘
```

- **Active:** Full content, indexed, searchable.
- **Archive:** Moved to `_archive/`, summary retained, full text compressed. Still searchable by metadata.
- **Purge:** Deleted. Deletion logged in `meta.db` for audit trail.

Configurable per-project via `_project.yaml` → `retention_days`.

```bash
aw retention preview                  # Dry-run: what would be archived/purged
aw retention run                      # Execute retention
aw restore <chat-id>                  # Restore from archive
```

---

## 12. Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.10+ | Ecosystem, LLM tooling, FastMCP SDK |
| MCP Framework | FastMCP | Official Python MCP framework |
| Metadata DB | SQLite (WAL mode) | Zero-config, ACID, local, fast |
| Full-text search | SQLite FTS5 | Built into SQLite, no extra deps |
| Vector DB | ChromaDB | pip install, zero-config, persistent |
| Embeddings | Ollama + nomic-embed-text | Local, free, 768-dim, high quality |
| Local LLM | Ollama + llama3.1:8b | Summarization, Q&A, tagging |
| BM25 search | bm25s | Lightweight ranked search |
| Fuzzy search | rapidfuzz | Typo tolerance |
| CLI framework | Click | Standard, well-documented |
| Config format | YAML | Human-readable, widely supported |
| Chat format | Markdown + YAML frontmatter | Readable, Obsidian-compatible, greppable |
| Browser automation | Playwright (optional) | One-time scraping of Claude/ChatGPT structure |

### Optional dependency tiers

```bash
pip install anticlaw                       # Core: keyword search, file management
pip install anticlaw[search]               # + BM25 ranked search (~5 MB)
pip install anticlaw[search,fuzzy]         # + typo tolerance (~7 MB)
pip install anticlaw[search,semantic]      # + vector embeddings (~40 MB)
pip install anticlaw[all]                  # Everything
pip install anticlaw[scraper]              # + Playwright for one-time import
```

---

## 13. Project Structure (Source Code)

> **Note:** Provider modules use a nested family structure (`providers/llm/`, `providers/backup/`, `providers/embedding/`) as defined in PROVIDERS.md, not the flat layout originally shown here. Provider data models (`ChatData`, `RemoteProject`, etc.) live in `core/models.py` to keep them co-located with core types.

```
anticlaw/
├── src/anticlaw/
│   ├── __init__.py              # ✅ __version__
│   ├── core/
│   │   ├── models.py            # ✅ Chat, ChatMessage, Project, Insight, Edge + provider models
│   │   ├── storage.py           # ✅ ChatStorage: file system CRUD
│   │   ├── config.py            # ✅ Config loader with defaults, ACL_HOME resolution
│   │   ├── fileutil.py          # ✅ Atomic writes, safe names, locking, permissions
│   │   ├── meta_db.py           # ✅ SQLite WAL + FTS5 metadata index (MetaDB)
│   │   ├── search.py            # ✅ Tier 1 keyword search dispatcher
│   │   ├── index.py             # ChromaDB vector indexing
│   │   ├── graph.py             # MAGMA 4-graph (SQLite)
│   │   ├── embeddings.py        # Ollama embedding provider
│   │   └── retention.py         # 3-zone lifecycle
│   ├── mcp/
│   │   ├── server.py            # ✅ FastMCP server — 13 tool definitions
│   │   ├── context_store.py     # ✅ Context-as-variable storage + chunking
│   │   ├── hooks.py             # ✅ TurnTracker, config generation, install functions
│   │   └── __main__.py          # ✅ Entry point for python -m anticlaw.mcp
│   ├── providers/
│   │   ├── registry.py          # ✅ ProviderRegistry (unified for all 3 families)
│   │   ├── llm/
│   │   │   ├── base.py          # ✅ LLMProvider Protocol + ProviderInfo + Capability
│   │   │   ├── claude.py        # ✅ Parse conversations.json + scrubbing
│   │   │   ├── chatgpt.py       # ChatGPT import/export
│   │   │   └── ollama.py        # Local LLM operations
│   │   ├── backup/
│   │   │   ├── base.py          # BackupProvider Protocol
│   │   │   ├── local.py         # shutil.copytree snapshots
│   │   │   ├── gdrive.py        # Google Drive API
│   │   │   ├── s3.py            # boto3 (AWS/MinIO/B2/R2)
│   │   │   └── rsync.py         # shells out to rsync
│   │   └── embedding/
│   │       ├── base.py          # EmbeddingProvider Protocol
│   │       ├── ollama.py        # nomic-embed-text (768-dim)
│   │       └── local_model.py   # model2vec/fastembed (256-dim)
│   ├── llm/
│   │   ├── summarizer.py        # Summarization via Ollama
│   │   ├── tagger.py            # Auto-tagging via Ollama
│   │   └── qa.py                # Q&A over knowledge base
│   ├── daemon/
│   │   ├── watcher.py           # watchdog file monitor
│   │   ├── scheduler.py         # APScheduler cron jobs
│   │   ├── tray.py              # pystray system tray
│   │   └── ipc.py               # Unix socket / Named pipe
│   └── cli/
│       ├── main.py              # ✅ Click CLI entry point
│       ├── import_cmd.py        # ✅ aw import claude <zip>
│       ├── search_cmd.py        # ✅ aw search with filters
│       ├── project_cmd.py       # ✅ aw list, show, move, tag, create, reindex
│       ├── knowledge_cmd.py     # aw inbox, stale, duplicates ...
│       ├── provider_cmd.py      # aw providers ...
│       ├── daemon_cmd.py        # aw daemon ...
│       └── mcp_cmd.py           # ✅ aw mcp start, install
├── tests/
│   ├── unit/
│   └── integration/
├── docs/
│   ├── SPEC.md                  # This document
│   ├── PLAN.md                  # Implementation plan
│   └── PROVIDERS.md             # Provider contracts and architecture
├── pyproject.toml
├── config.example.yaml
├── README.md
└── LICENSE                      # MIT
```

---

## 14. Configuration (config.yaml)

```yaml
# ~/anticlaw/.acl/config.yaml

# Paths
home: ~/anticlaw                    # ACL_HOME

# Search
search:
  alpha: 0.6                           # Hybrid blend (0=BM25, 1=semantic)
  max_results: 20                      # Default result limit
  default_max_tokens: 4000             # Default token budget

# Embeddings
embeddings:
  provider: ollama                     # ollama | none
  model: nomic-embed-text
  dimensions: 768

# Local LLM
llm:
  provider: ollama
  model: llama3.1:8b                   # For summarization, Q&A, tagging
  base_url: http://localhost:11434

# Graph
graph:
  temporal_window_minutes: 30          # Auto-link nodes within this window
  semantic_top_k: 3                    # Top-K similar nodes for semantic edges
  auto_entities: true                  # Auto-extract entities on remember

# Retention
retention:
  archive_days: 30                     # Days before archiving stale items
  purge_days: 180                      # Days before purging archived items
  importance_decay_days: 30            # Half-life for importance decay

# Providers
providers:
  claude:
    enabled: true
  chatgpt:
    enabled: false
  gemini:
    enabled: false

# MCP
mcp:
  auto_save_reminder_turns: [10, 20, 30]  # Reminder intervals
  pre_compact_block: true                  # Block /compact until saved
```

---

## 15. Security

### 15.1 Threat Model

| Data | Sensitivity | Risk |
|------|-------------|------|
| Chat texts | **High** — may contain API keys, passwords, business logic, personal data | Leak on disk compromise |
| Embeddings | **Medium** — cannot reconstruct source text, but topic inference possible | Partial leak via similarity attack |
| Metadata (tags, dates, project names) | **Low** — but reveals work structure | Activity profiling |
| config.yaml | **High** — may contain provider tokens if misconfigured | Cloud account compromise |
| SQLite databases (meta.db, graph.db) | **High** — contains indexed chat content | Same as chat texts |

### 15.2 File System Permissions

```python
# Applied on: init, import, every write operation
FILE_MODE = 0o600    # Owner read/write only
DIR_MODE  = 0o700    # Owner read/write/execute only
```

**Windows:** NTFS ACLs set via `icacls` — restrict to current user only. Documented in installation guide.

### 15.3 Secrets Management

API tokens and credentials are **never** stored in `config.yaml`.

```yaml
# config.yaml — stores only the reference
providers:
  claude:
    enabled: true
    credential: keyring          # actual token in system keyring

# Supported backends (via 'keyring' Python library):
# - macOS: Keychain
# - Windows: Credential Manager
# - Linux: Secret Service (GNOME Keyring / KDE Wallet)
```

```bash
# Set a provider token
aw auth claude                   # interactive prompt, stores in system keyring

# Verify
aw auth status                   # shows which providers are configured (no secrets printed)
```

### 15.4 Content Scrubbing

Auto-detection and redaction of secrets during import:

```bash
aw import claude export.zip --scrub    # strip secrets before writing .md files
```

**Detected patterns:**
- API keys: `sk-*`, `Bearer *`, `ghp_*`, `gho_*`, `AKIA*`
- Passwords: `password=*`, `passwd:*`
- Connection strings: `postgres://*:*@*`, `mysql://*:*@*`
- Private keys: `-----BEGIN * PRIVATE KEY-----`
- Tokens: `token=*`, `secret=*`

Replaced with: `[REDACTED:api_key]`, `[REDACTED:password]`, etc. Original value never written to disk.

### 15.5 Git Safety

Auto-generated `.gitignore` at `~/anticlaw/.gitignore`:

```gitignore
# AnticLaw internal data — NEVER commit
.acl/meta.db
.acl/graph.db
.acl/vectors/
.acl/cache/
.acl/config.yaml

# Chat files are OK to commit (if desired), but review first
# Consider: git-crypt or age encryption for sensitive projects
```

**Pre-commit hook** (optional, installed via `aw init --git-hooks`):
- Scans staged `.md` files for API keys / tokens / passwords.
- Blocks commit if secrets detected.
- Suggests `aw scrub <file>` to clean.

### 15.6 Encryption at Rest (v1.0+)

Optional. For users with elevated security requirements.

```yaml
# config.yaml
security:
  encryption: none               # none | age | gpg
  encryption_recipient: "age1..."  # age public key (if encryption=age)
```

When enabled:
- `.md` files stored encrypted on disk.
- Decrypted only in memory for indexing / search.
- Embeddings stored in ChromaDB (not reversible to original text).
- `aw show <chat>` decrypts on the fly.

### 15.7 MCP Server Isolation

- **Transport:** stdio only — no HTTP endpoint, no network exposure.
- **Scope:** Tools cannot access files outside `ACL_HOME` directory.
- **No elevation:** Runs as current user, no privileged operations.
- **Read-only for agents:** `aw_remember` and `aw_search` cannot modify existing chat files — only add new insights to graph.db.

### 15.8 Platform-Specific Notes

| Platform | Issue | Mitigation |
|----------|-------|-----------|
| **Windows** | Default file permissions 0o666 | Explicit `icacls` on every write |
| **Windows** | Antivirus may lock SQLite WAL files | Document: add `~/anticlaw/` to AV exclusions |
| **Windows** | `ACL` is a system term | CLI alias is `aw`, no naming conflict |
| **macOS** | Gatekeeper may block Ollama | Document: `xattr -d com.apple.quarantine` |
| **Linux** | SELinux may restrict file access | Document: `semanage fcontext` for `~/anticlaw/` |

---

## 16. Roadmap

### v0.1 — Foundation (2 weeks)

- [x] Directory structure, config loader
- [x] Core models: Project, Chat, ChatMessage, Insight, Edge + provider models
- [x] File system storage: read/write chat .md files with YAML frontmatter
- [x] Claude Provider: parse `conversations.json` → .md files
- [ ] Playwright scraper: collect project→chat mapping from claude.ai (one-time)
- [x] SQLite metadata DB (meta_db.py with WAL mode + FTS5)
- [x] CLI: `aw import claude`
- [x] CLI: `aw list`, `aw show`, `aw move`, `aw tag`, `aw create project`, `aw reindex`

### v0.2 — Search (1 week)

- [x] Tier 1: keyword search (SQLite FTS5 with BM25 ranking)
- [ ] Tier 2: BM25 (bm25s)
- [ ] Tier 3: fuzzy (rapidfuzz)
- [ ] Tier 4: semantic (Ollama + ChromaDB)
- [ ] Tier 5: hybrid fusion
- [x] CLI: `aw search` with --project, --tag, --exact, --max-results
- [ ] Indexing pipeline: auto-index on import

### v0.3 — MCP Server (1 week) ✅

- [x] FastMCP server with 13 tools (aw_related, aw_graph_stats are stubs)
- [x] Hooks: AutoReminder (TurnTracker at 10/20/30 turns), PostSave (reset on remember)
- [x] Registration: `aw mcp install claude-code`, `aw mcp install cursor`
- [x] Context-as-variable storage with 6 chunking strategies
- [ ] Agent template: `agents/anticlaw.md` (deferred to v1.0)
- [ ] CLAUDE.md template for projects (deferred to v1.0)

### v0.4 — Knowledge Graph (1 week)

- [ ] MAGMA graph: nodes, 4 edge types
- [ ] Auto-edge generation on `aw_remember`
- [ ] Intent-aware recall (why/when/what)
- [ ] CLI: `aw related`, `aw why`, `aw timeline`

### v0.5 — Local LLM (1 week)

- [ ] Ollama integration: summarizer, tagger, Q&A
- [ ] Auto-summarize on import
- [ ] Auto-tag on import
- [ ] CLI: `aw summarize`, `aw autotag`, `aw ask`

### v0.6 — AnticLaw (1 week)

- [ ] `aw inbox` — classify unprocessed chats
- [ ] `aw stale` — detect inactive projects
- [ ] `aw duplicates` — find similar chats
- [ ] `aw health` — integrity check
- [ ] Retention lifecycle: archive, purge, restore

### v0.7 — Second Provider (1 week)

- [ ] ChatGPT Provider: parse their export format
- [ ] Unified import: both providers produce same .md format
- [ ] Cross-provider search

### v1.0 — Stable Release

- [ ] Full test coverage
- [ ] Documentation
- [ ] PyPI package
- [ ] Interactive installer
- [ ] Docker support

---

## 17. Prior Art & Inspiration

| Project | What we take | What we do differently |
|---------|-------------|----------------------|
| **EchoVault** | MCP tool pattern, directive descriptions, SQLite + FTS5, Ollama embeddings | Add project hierarchy, multi-provider, anticlaw features |
| **MemCP** | 5-tier search, MAGMA graph, context-as-variable, retention lifecycle, hooks | Simplify to 13 tools (vs 21), add provider abstraction, file-first philosophy |
| **Obsidian** | Markdown + YAML frontmatter, folder = project, human-readable files | Add LLM integration, semantic search, MCP server |
| **Letta (MemGPT)** | External memory for LLMs concept | Local-first, no cloud dependency |
| **Beads** | Git-backed task/memory tracking | Broader scope (full KB, not just tasks) |

---

## 18. Design Decisions

1. **Markdown over JSON for chats.** JSON is better for machines, but Markdown is readable, editable, greppable, and compatible with Obsidian/VS Code. YAML frontmatter gives us the structured metadata we need.

2. **SQLite over MySQL/PostgreSQL.** Zero-config, single file, embedded. Perfect for local-first tool. No daemon to manage. WAL mode gives us concurrent reads.

3. **ChromaDB over sqlite-vec.** ChromaDB is a proper vector DB with built-in persistence, filtering, and metadata. sqlite-vec is lighter but requires manual similarity computation.

4. **Ollama over cloud embeddings.** Privacy (no data leaves the machine), cost (free), speed (local inference). Trade-off: requires ~5 GB disk for models.

5. **13 MCP tools, not 21.** MemCP's 21 tools is too many — leads to tool confusion for the LLM. We merge retention and project tools into CLI-only commands, keeping MCP focused on what the agent needs during a session.

6. **No fork of EchoVault or MemCP.** Both solve different problems. Our file-first, multi-provider architecture is fundamentally different. Easier to build from scratch and borrow patterns than to refactor someone else's data model.

---

## 19. Source Providers (v1.1+)

Fourth provider family — content sources beyond LLM chat exports.

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Provider Registry                       │
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ LLM         │  │ Backup       │  │ Embedding     │  │
│  │ Providers   │  │ Providers    │  │ Providers     │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
│                                                         │
│  ┌─────────────┐  ┌──────────────┐                     │
│  │ Source       │  │ Input        │  ← NEW             │
│  │ Providers   │  │ Providers    │                     │
│  ├─────────────┤  ├──────────────┤                     │
│  │ llm-export  │  │ cli          │                     │
│  │ local-files │  │ mcp          │                     │
│  │ obsidian    │  │ http-api     │                     │
│  │ notion      │  │ whisper      │                     │
│  │ (your own)  │  │ alexa        │                     │
│  └─────────────┘  └──────────────┘                     │
└─────────────────────────────────────────────────────────┘
```

### Source Provider Contract

```python
@runtime_checkable
class SourceProvider(Protocol):
    """Contract for content source integration."""

    @property
    def name(self) -> str: ...

    @property
    def info(self) -> SourceInfo: ...

    def scan(self, paths: list[Path], **filters) -> list[SourceDocument]:
        """Scan paths, return indexable documents."""
        ...

    def read(self, path: Path) -> SourceDocument:
        """Read a single document."""
        ...

    def watch(self, paths: list[Path], callback: Callable) -> None:
        """Watch for changes (integrates with daemon watcher)."""
        ...
```

### Local Files Provider

Scans configured directories, reads text/code/PDF files, indexes into the same
search pipeline as LLM chats. Results appear alongside chat results in unified search.

**Supported formats:**

| Category | Extensions | Reader |
|----------|-----------|--------|
| Text | `.txt`, `.md`, `.csv`, `.json`, `.xml`, `.yaml`, `.toml` | Direct read (UTF-8) |
| Code | `.py`, `.java`, `.js`, `.ts`, `.go`, `.rs`, `.sql`, `.sh` | Read with language metadata |
| Config | `.properties`, `.ini`, `.cfg`, `.env.example` | Direct read |
| PDF | `.pdf` | `pymupdf` (fast) or `pdfplumber` (fallback) |

**Not supported (v1.1):** `.docx`, `.xlsx`, `.pptx`, `.png`, `.jpg` (planned for v2.0 with OCR).

### Unified Search

After Phase 12, `aw search` returns three result types:

```
$ aw search "TreeMap"

[chat]  2025-02-18 — "Java Collections Discussion" (project: java-dev)
        ...discussed TreeMap vs HashMap performance for sorted keys...

[file]  C:\srdev\myapp\src\Cache.java (line 42)
        private TreeMap<String, Object> cache = new TreeMap<>();

[insight] "Use TreeMap when iteration order matters" (decision, high)
```

---

## 20. Input Providers (v1.2+)

Fifth provider family — how queries reach AnticLaw.

### Input Provider Contract

```python
@runtime_checkable
class InputProvider(Protocol):
    """Contract for query input methods."""

    @property
    def name(self) -> str: ...

    def listen(self) -> str:
        """Get input from user. Returns query text."""
        ...

    def respond(self, text: str) -> None:
        """Send response back to user (text, voice, etc.)."""
        ...

    def is_available(self) -> bool:
        """Check if hardware/dependencies are available."""
        ...
```

### Existing inputs (already implemented)

| Input | How it works |
|-------|-------------|
| CLI | `aw search "query"` — text in terminal |
| MCP | Claude Code calls `aw_search()` via stdio |

### New inputs (post-v1.0)

| Input | How it works |
|-------|-------------|
| HTTP API | `GET /api/search?q=...` — any HTTP client |
| Whisper | Microphone → offline STT → search → results in terminal |
| Alexa | Voice → AWS Lambda → HTTP API → voice response |

---

## 21. HTTP API (v1.1+)

FastAPI-based REST API. Runs alongside CLI and MCP server.

### Endpoints

```
GET  /api/health                    → {"status": "ok", "version": "..."}
GET  /api/search?q=...&project=...  → {"results": [...]}
POST /api/ask   {"question": "..."}  → {"answer": "...", "sources": [...]}
GET  /api/projects                   → {"projects": [...]}
GET  /api/stats                      → {"chats": N, "insights": N, ...}
```

### Voice-optimized endpoints

```
GET  /api/voice/search?q=...        → {"spoken": "short answer for TTS"}
POST /api/voice/ask                  → {"spoken": "concise answer < 30 words"}
```

### Security

- **Localhost:** No auth required (default: bind to 127.0.0.1)
- **Remote access:** API key in `Authorization: Bearer <key>` header, key stored in keyring
- **Tunnel:** Cloudflare Tunnel / ngrok for Alexa integration (HTTPS required by Amazon)

---

## 22. Voice Input — Whisper (v1.2+)

Offline speech-to-text using `faster-whisper` (CTranslate2 backend).

### Models

| Model | Size | Speed | Quality | Use case |
|-------|------|-------|---------|----------|
| `tiny` | ~75 MB | Fastest | Basic | Wake word detection |
| `base` | ~150 MB | Fast | Good | Short commands |
| `small` | ~500 MB | Medium | Great | Full sentences, Russian |
| `medium` | ~1.5 GB | Slow | Excellent | Complex queries |

### Modes

1. **Push-to-talk:** Hold `Ctrl+Space` → speak → release → search
2. **Continuous:** Always listening, activated by wake word ("антик" / "hey antic")
3. **Single shot:** `aw listen` → one query → results → exit

### Language

Whisper supports 99 languages. Russian and English work without configuration.
`language: auto` detects automatically.

---

## 23. Alexa Integration (v1.3+)

### Prerequisites

1. HTTP API running (Phase 12)
2. HTTPS tunnel to localhost (Cloudflare Tunnel recommended)
3. Amazon Developer account (free)
4. Alexa-enabled device on same Amazon account

### Alexa Skill Intents

| Intent | Utterances (EN) | Utterances (RU) |
|--------|----------------|-----------------|
| SearchIntent | "search for {query}" | "найди {query}" |
| AskIntent | "ask {question}" | "спроси {question}" |
| StatusIntent | "status" | "статус" |

### Data Flow

```
User: "Alexa, ask AnticLaw to find chats about authorization"
  → Alexa STT: "find chats about authorization"
  → Intent: SearchIntent, query="authorization"
  → Lambda: GET https://tunnel.example.com/api/voice/search?q=authorization
  → AnticLaw: search → format short answer
  → Lambda: build Alexa response
  → Alexa TTS: "I found 3 chats about authorization. The most recent is
                from February 18th in project Alpha, about JWT tokens."
```

### Limitations

- Alexa response max ~8 seconds of speech (~60 words)
- Requires internet (Alexa → AWS → tunnel → local)
- Tunnel must be running (daemon manages this)
- Latency: ~2-4 seconds end-to-end
