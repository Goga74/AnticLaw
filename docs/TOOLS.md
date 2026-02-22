# MCP Tools Reference

AnticLaw exposes 13 tools via the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP). These tools let Claude Code, Cursor, and other MCP clients interact with your knowledge base.

## Setup

```bash
aw mcp install claude-code
```

Restart Claude Code after installation. The tools will appear with the `aw_` prefix.

## Tool Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| Core Memory | `aw_remember`, `aw_recall`, `aw_forget` | Save and retrieve insights |
| Health | `aw_ping` | Server status check |
| Search | `aw_search` | Full-text search across chats |
| Context | `aw_load_context`, `aw_inspect_context`, `aw_get_context`, `aw_chunk_context`, `aw_peek_chunk` | Store and process large content |
| Graph | `aw_related`, `aw_graph_stats` | Knowledge graph traversal |
| Project | `aw_projects` | List projects |

---

## Core Memory

### aw_ping

Health check. Returns server status, project count, chat count, insight count.

**Parameters:** None

**Returns:**
```json
{
  "status": "ok",
  "version": "1.0.0",
  "projects": 5,
  "chats": 142,
  "insights": 38
}
```

---

### aw_remember

Save an insight or decision to the knowledge base. **Call this before ending any session where important decisions were made.**

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `content` | string | yes | The insight text to save |
| `category` | string | no | `decision`, `finding`, `preference`, `fact`, `question` (default: `fact`) |
| `importance` | string | no | `low`, `medium`, `high`, `critical` (default: `medium`) |
| `tags` | list[string] | no | Tags for categorization |
| `project_id` | string | no | Associate with a project |

**Returns:**
```json
{"id": "a1b2c3d4-...", "status": "saved"}
```

---

### aw_recall

Retrieve insights from the knowledge base with optional filters.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | string | no | Keyword search filter |
| `project` | string | no | Filter by project name |
| `category` | string | no | Filter by category |
| `importance` | string | no | Minimum importance level |
| `max_results` | int | no | Maximum results (default: 10) |

**Returns:** Array of insight objects with `id`, `content`, `category`, `importance`, `tags`, `project_id`.

---

### aw_forget

Remove an insight by ID. Use with caution — this cannot be undone.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `insight_id` | string | yes | The insight ID to delete |

**Returns:**
```json
{"status": "deleted", "id": "a1b2c3d4-..."}
```

---

## Search

### aw_search

Search across all chats in the knowledge base. Uses full-text search across titles, summaries, message content, and tags.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | string | yes | Search query |
| `project` | string | no | Filter by project name |
| `tag` | string | no | Filter by tag |
| `exact` | bool | no | Exact phrase match (default: false) |
| `max_results` | int | no | Maximum results (default: 20) |

**Returns:** Array of search results with `chat_id`, `title`, `project`, `snippet`.

---

## Context Management

These tools let you store large content (files, logs, code) as named variables on disk, avoiding context window bloat. Load once, then read by line range or chunk.

### aw_load_context

Store large content as a named variable.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | yes | Variable name (e.g., `"server_log"`) |
| `content` | string | yes | The content to store |
| `content_type` | string | no | `text`, `code`, `markdown` (default: `text`) |

**Returns:** Metadata — name, size, line count, token estimate.

---

### aw_inspect_context

Show metadata and preview of a stored context without loading the full content.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | yes | Variable name |

**Returns:** Name, type, size, line count, token estimate, chunk info, first 5 lines preview.

---

### aw_get_context

Read stored content, or a specific line range.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | yes | Variable name |
| `start_line` | int | no | Start line (1-indexed) |
| `end_line` | int | no | End line (inclusive) |

Omit `start_line` and `end_line` to read the full content.

---

### aw_chunk_context

Split stored content into numbered chunks for incremental reading.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | yes | Variable name |
| `strategy` | string | no | `auto`, `lines`, `paragraphs`, `headings`, `chars` (default: `auto`) |
| `chunk_size` | int | no | Size per chunk (default: 100) |

**Strategies:**
- **auto** — Detects best strategy (headings > paragraphs > lines)
- **lines** — N lines per chunk
- **paragraphs** — N paragraphs per chunk
- **headings** — Split on markdown headings
- **chars** — N characters per chunk

**Returns:** Chunk count, chunk sizes, strategy used.

---

### aw_peek_chunk

Read a specific chunk by number (1-indexed).

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | yes | Variable name |
| `chunk_number` | int | yes | Chunk number (1-indexed) |

---

## Knowledge Graph

### aw_related

Traverse the knowledge graph from a node. Returns connected insights via edges.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `node_id` | string | yes | Starting node ID (or keyword to resolve) |
| `edge_type` | string | no | Filter: `semantic`, `temporal`, `causal`, `entity` |
| `depth` | int | no | Traversal depth (default: 2) |

**Returns:**
```json
{
  "status": "ok",
  "node": {"id": "...", "content": "...", "category": "decision"},
  "related": [
    {"id": "...", "content": "...", "edge_type": "causal", "weight": 0.85, "depth": 1}
  ]
}
```

---

### aw_graph_stats

Knowledge graph statistics.

**Parameters:** None

**Returns:** Node count, edge counts by type, top entities, project distribution.

---

## Project

### aw_projects

List all projects in the knowledge base.

**Parameters:** None

**Returns:** Array of projects with `id`, `name`, `description`, `chat_count`, `last_activity`.
