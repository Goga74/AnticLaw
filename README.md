# AnticLaw

Local-first knowledge base for LLM conversations.

AnticLaw (`aw` CLI) manages exported LLM conversations (Claude, ChatGPT, Gemini) as local Markdown files with YAML frontmatter. Files are the source of truth. LLMs are interchangeable clients.

## Installation

```bash
pip install anticlaw                       # Core
pip install anticlaw[search]               # + BM25 ranked search
pip install anticlaw[search,fuzzy]         # + typo tolerance
pip install anticlaw[search,semantic]      # + vector embeddings
pip install anticlaw[all]                  # Everything
```

### Development

```bash
git clone https://github.com/izamiatin/anticlaw.git
cd anticlaw
pip install -e ".[dev]"
```

## Quick Start

```bash
aw --version                    # Verify installation
aw init                         # Initialize knowledge base at ~/anticlaw/
aw import claude export.zip     # Import Claude conversations
aw search "query"               # Search your knowledge base
aw list                         # List projects
```

## Architecture

- **Storage:** Markdown + YAML frontmatter (chats), SQLite (metadata), ChromaDB (vectors)
- **Search:** 5-tier (keyword > BM25 > fuzzy > semantic > hybrid)
- **MCP Server:** 13 tools for Claude Code / Cursor integration
- **Local LLM:** Ollama for summarization, tagging, Q&A

## License

MIT
