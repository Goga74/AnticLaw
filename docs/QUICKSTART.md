# Quick Start Guide

Get from zero to searching your LLM conversations in 5 minutes.

## 1. Install

```bash
pip install anticlaw
```

For enhanced search (recommended):

```bash
pip install anticlaw[search,fuzzy]
```

Verify the installation:

```bash
aw --version
```

## 2. Initialize

```bash
aw init
```

This creates `~/anticlaw/` with the directory structure:

```
~/anticlaw/
├── .acl/
│   └── config.yaml
├── _inbox/
├── _archive/
└── .gitignore
```

For guided setup with preferences:

```bash
aw init --interactive
```

## 3. Import Conversations

### From Claude.ai

1. Go to Claude.ai → Settings → Privacy → Export Data
2. Download the ZIP file
3. Import:

```bash
aw import claude ~/Downloads/claude-export.zip
```

### From ChatGPT

1. Go to ChatGPT → Settings → Data controls → Export data
2. Wait for the email, download the ZIP
3. Import:

```bash
aw import chatgpt ~/Downloads/chatgpt-export.zip
```

### With secret scrubbing

If your conversations contain API keys or passwords:

```bash
aw import claude export.zip --scrub
```

This redacts detected secrets (API keys, tokens, connection strings) during import.

## 4. Search

```bash
# Basic keyword search
aw search "authentication"

# Filter by project
aw search "JWT" --project my-project

# Filter by tag
aw search "database" --tag postgres

# Exact phrase match
aw search "refresh tokens" --exact
```

## 5. Organize

```bash
# List all projects
aw list

# See chats in a project (or _inbox)
aw list _inbox

# Create a project
aw create project "Backend API"

# Move a chat from inbox to a project
aw move 2025-02-18_auth-discussion.md backend-api

# Add tags
aw tag 2025-02-18_auth-discussion.md auth jwt security

# View a chat
aw show 2025-02-18_auth-discussion.md
```

## 6. Rebuild Index

If you edit Markdown files directly (they're just text files!), rebuild the search index:

```bash
aw reindex
```

## 7. Connect to Claude Code (MCP)

AnticLaw works as an MCP server, giving Claude Code access to your knowledge base:

```bash
aw mcp install claude-code
```

After restarting Claude Code, it will have access to tools like `aw_search`, `aw_remember`, `aw_recall`, and `aw_projects`. See [TOOLS.md](TOOLS.md) for the full reference.

## 8. Local AI (Optional)

If you have [Ollama](https://ollama.ai) installed:

```bash
# Install required models
ollama pull nomic-embed-text    # For semantic search
ollama pull llama3.1:8b         # For summarization/Q&A

# Generate summaries
aw summarize my-project

# Auto-tag chats
aw autotag my-project

# Ask questions over your knowledge base
aw ask "what authentication approach did we decide on?"
```

## 9. Knowledge Graph

```bash
# Find related insights
aw related <insight-id>

# Trace decision chains
aw why "chose JWT over sessions"

# See temporal timeline
aw timeline my-project
```

## 10. Knowledge Maintenance

```bash
# Check inbox for unsorted chats with suggestions
aw inbox

# Find stale projects
aw stale

# Detect duplicate chats
aw duplicates

# Check overall KB health
aw health

# View statistics
aw stats
```

## Next Steps

- Set up the [background daemon](../README.md#background-daemon) for auto-indexing
- Configure [backups](../README.md#backup) for data safety
- Read the full [MCP tool reference](TOOLS.md) for Claude Code integration
- Check the [specification](SPEC.md) for architecture details
