# AnticLaw — Provider Contracts

**Companion to:** SPEC.md, PLAN.md

---

## Provider Philosophy

Every external integration in AnticLaw is a **provider** — a pluggable module
that implements a strict contract (Python Protocol). New providers are added
without touching core code.

Six provider families:

```
┌──────────────────────────────────────────────────────────────────┐
│                      Provider Registry                            │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐           │
│  │ LLM         │  │ Backup       │  │ Embedding     │           │
│  │ Providers   │  │ Providers    │  │ Providers     │           │
│  ├─────────────┤  ├──────────────┤  ├───────────────┤           │
│  │ Claude      │  │ Local (copy) │  │ Ollama        │           │
│  │ ChatGPT     │  │ Google Drive │  │ OpenAI API    │           │
│  │ Gemini      │  │ S3 / MinIO   │  │ HuggingFace   │           │
│  │ Ollama      │  │ Dropbox      │  │ (local model) │           │
│  │ (your own)  │  │ WebDAV       │  │ (your own)    │           │
│  │             │  │ rsync/ssh    │  │               │           │
│  └─────────────┘  └──────────────┘  └───────────────┘           │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐           │
│  │ Source       │  │ Input        │  │ Scraper       │           │
│  │ Providers   │  │ Providers    │  │ Providers     │           │
│  ├─────────────┤  ├──────────────┤  ├───────────────┤           │
│  │ local-files │  │ cli          │  │ claude-web   │           │
│  │ obsidian    │  │ mcp          │  │ chatgpt-web  │           │
│  │ notion      │  │ http-api     │  │ gemini-web   │           │
│  │ (your own)  │  │ whisper      │  │ perplexity   │           │
│  └─────────────┘  └──────────────┘  └───────────────┘           │
└──────────────────────────────────────────────────────────────────┘
```

---

## 1. LLM Providers

**Purpose:** Import/export chats, sync projects with cloud LLM platforms.

### Contract

```python
from pathlib import Path
from typing import Protocol, runtime_checkable
from anticlaw.core.models import (
    ChatData, RemoteProject, RemoteChat, SyncResult, ProviderInfo
)

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
        """List all projects/folders on the remote platform."""
        ...

    def list_chats(self, project_id: str | None = None) -> list[RemoteChat]:
        """List chats, optionally filtered by project."""
        ...

    def export_chat(self, chat_id: str) -> ChatData:
        """Export a single chat with all messages."""
        ...

    def export_all(self, output_dir: Path) -> int:
        """Bulk export from official data dump (ZIP/JSON). Returns count."""
        ...

    def import_chat(self, project_id: str | None, chat: ChatData) -> str:
        """Push a chat to the remote platform. Returns remote chat ID."""
        ...

    def sync(
        self,
        local_project: Path,
        remote_project_id: str,
        direction: str = "pull",    # pull | push | both
    ) -> SyncResult:
        """Sync between local folder and remote project."""
        ...
```

### Capabilities

Not every provider supports every method. Declare capabilities:

```python
from dataclasses import dataclass, field

@dataclass
class ProviderInfo:
    display_name: str               # "Claude.ai"
    version: str                    # "1.0.0"
    capabilities: set[str] = field(default_factory=set)
    # Possible capabilities:
    #   "export_bulk"    — can export all chats at once (official ZIP)
    #   "export_single"  — can export one chat by ID
    #   "import"         — can push chats to platform
    #   "list_projects"  — can enumerate remote projects
    #   "list_chats"     — can enumerate remote chats
    #   "sync"           — supports bidirectional sync
    #   "scrape"         — has browser scraper for supplementary data
```

### Provider: Claude

```python
class ClaudeProvider:
    name = "claude"
    info = ProviderInfo(
        display_name="Claude.ai",
        version="1.0.0",
        capabilities={"export_bulk", "scrape"},
    )
    # export_bulk  → parse conversations.json from official ZIP
    # scrape       → Playwright: project mapping, Knowledge files
    # No import, no sync (no API for claude.ai)
```

### Provider: ChatGPT

```python
class ChatGPTProvider:
    name = "chatgpt"
    info = ProviderInfo(
        display_name="ChatGPT",
        version="1.0.0",
        capabilities={"export_bulk"},
    )
    # export_bulk → parse conversations.json from OpenAI export
```

### Provider: Gemini

```python
class GeminiProvider:
    name = "gemini"
    info = ProviderInfo(
        display_name="Google Gemini",
        version="1.0.0",
        capabilities={"export_bulk", "import", "scrape"},
    )
    # export_bulk → parse Google Takeout Gemini export (Phase 16)
    # import      → push chats via Google AI API (Phase 17)
    # scrape      → Playwright: Gems, extensions data
    # Note: Gemini Advanced includes some API access (unlike Claude/ChatGPT)
```

### Provider: Ollama

```python
class OllamaProvider:
    name = "ollama"
    info = ProviderInfo(
        display_name="Ollama (local)",
        version="1.0.0",
        capabilities={"export_single", "import"},
    )
    # Special: not a cloud platform
    # import_chat  → load chat as context for local session
    # export_chat  → save local session as .md file
```

### Registration

```yaml
# config.yaml
providers:
  llm:
    claude:
      enabled: true
      credential: keyring
    chatgpt:
      enabled: false
    ollama:
      enabled: true
      base_url: http://localhost:11434
      default_model: llama3.1:8b
```

```python
# src/anticlaw/providers/registry.py

from anticlaw.providers.claude import ClaudeProvider
from anticlaw.providers.chatgpt import ChatGPTProvider
from anticlaw.providers.ollama import OllamaProvider

LLM_PROVIDERS: dict[str, type] = {
    "claude": ClaudeProvider,
    "chatgpt": ChatGPTProvider,
    "ollama": OllamaProvider,
}

def get_llm_provider(name: str, config: dict) -> LLMProvider:
    cls = LLM_PROVIDERS[name]
    return cls(config)
```

---

## 2. Backup Providers

**Purpose:** Copy/sync AnticLaw data to external storage for safety.

### Contract

```python
from pathlib import Path
from typing import Protocol, runtime_checkable
from dataclasses import dataclass
from datetime import datetime

@dataclass
class BackupResult:
    success: bool
    files_copied: int
    files_skipped: int              # already up-to-date
    bytes_transferred: int
    duration_seconds: float
    errors: list[str]
    timestamp: datetime

@dataclass
class BackupInfo:
    display_name: str               # "Google Drive"
    version: str
    supports_incremental: bool      # can skip unchanged files
    supports_restore: bool          # can restore from backup
    requires_auth: bool

@runtime_checkable
class BackupProvider(Protocol):
    """Contract for backup storage integration."""

    @property
    def name(self) -> str:
        """Unique provider ID: 'local', 'gdrive', 's3', 'dropbox', etc."""
        ...

    @property
    def info(self) -> BackupInfo:
        ...

    def auth(self, config: dict) -> bool:
        """Verify credentials / connectivity."""
        ...

    def backup(
        self,
        source_dir: Path,          # ACL_HOME
        manifest: dict | None,     # previous backup state (for incremental)
    ) -> BackupResult:
        """Run backup. Returns result + updated manifest."""
        ...

    def restore(
        self,
        target_dir: Path,          # where to restore
        snapshot: str | None,      # specific snapshot ID, or latest
    ) -> BackupResult:
        """Restore from backup."""
        ...

    def list_snapshots(self) -> list[dict]:
        """List available backup snapshots with dates and sizes."""
        ...

    def verify(self) -> bool:
        """Verify backup integrity."""
        ...
```

### Provider: Local

```python
class LocalBackupProvider:
    name = "local"
    info = BackupInfo(
        display_name="Local copy",
        version="1.0.0",
        supports_incremental=True,
        supports_restore=True,
        requires_auth=False,
    )
    # Uses shutil.copytree with dirs_exist_ok=True
    # Incremental: compares mtime from manifest
    # Snapshots: timestamped folders (2025-02-20T03-00-00/)
```

### Provider: Google Drive

```python
class GDriveBackupProvider:
    name = "gdrive"
    info = BackupInfo(
        display_name="Google Drive",
        version="1.0.0",
        supports_incremental=True,
        supports_restore=True,
        requires_auth=True,
    )
    # Uses google-api-python-client
    # Credential: OAuth2 token in system keyring
    # Incremental: compares MD5 hash
    # Uploads to configurable folder_id
```

### Provider: S3 / MinIO

```python
class S3BackupProvider:
    name = "s3"
    info = BackupInfo(
        display_name="S3 / MinIO",
        version="1.0.0",
        supports_incremental=True,
        supports_restore=True,
        requires_auth=True,
    )
    # Uses boto3
    # Works with AWS S3, MinIO, Backblaze B2, Cloudflare R2
    # Credential: access_key + secret_key in system keyring
    # Incremental: compares ETag
```

### Provider: rsync/SSH

```python
class RsyncBackupProvider:
    name = "rsync"
    info = BackupInfo(
        display_name="rsync over SSH",
        version="1.0.0",
        supports_incremental=True,
        supports_restore=True,
        requires_auth=True,         # SSH key
    )
    # Shells out to rsync binary
    # Fastest for local network / NAS
```

### Provider: WebDAV

```python
class WebDAVBackupProvider:
    name = "webdav"
    info = BackupInfo(
        display_name="WebDAV",
        version="1.0.0",
        supports_incremental=True,
        supports_restore=True,
        requires_auth=True,
    )
    # Uses webdavclient3
    # Works with Nextcloud, ownCloud, etc.
```

### Registration

```yaml
# config.yaml
providers:
  backup:
    local:
      enabled: true
      path: /mnt/backup/anticlaw
    gdrive:
      enabled: true
      folder_id: "1aBcDeFgHiJk..."
      credential: keyring
    s3:
      enabled: false
      bucket: my-anticlaw-backup
      region: eu-west-1
      endpoint_url: null            # for MinIO: http://localhost:9000
      credential: keyring
    rsync:
      enabled: false
      target: user@nas:/backup/anticlaw
      ssh_key: ~/.ssh/id_ed25519
    webdav:
      enabled: false
      url: https://nextcloud.example.com/remote.php/dav/files/user/anticlaw
      credential: keyring
```

```python
# src/anticlaw/providers/backup_registry.py

BACKUP_PROVIDERS: dict[str, type] = {
    "local": LocalBackupProvider,
    "gdrive": GDriveBackupProvider,
    "s3": S3BackupProvider,
    "rsync": RsyncBackupProvider,
    "webdav": WebDAVBackupProvider,
}
```

### CLI

```bash
aw backup now                          # run all enabled backup providers
aw backup now --provider gdrive        # run specific provider
aw backup list                         # list snapshots across all providers
aw backup list --provider s3           # list snapshots for specific provider
aw backup restore --provider local     # restore latest from local
aw backup restore --provider gdrive --snapshot 2025-02-20T03-00-00
aw backup verify                       # verify all backup integrity
aw backup status                       # show last backup time per provider
```

### Daemon integration

```yaml
daemon:
  backup:
    enabled: true
    schedule: "0 3 * * *"             # daily at 3 AM
    # Daemon runs ALL enabled backup providers on schedule.
    # Each provider independently tracks its manifest.
    notify_on_success: true
    notify_on_failure: true
```

---

## 3. Embedding Providers

**Purpose:** Generate vector embeddings for semantic search.

### Contract

```python
from typing import Protocol, runtime_checkable
from dataclasses import dataclass

@dataclass
class EmbeddingInfo:
    display_name: str
    version: str
    dimensions: int                 # 768, 384, 1536, etc.
    max_tokens: int                 # max input length
    is_local: bool                  # runs on user's machine
    requires_auth: bool

@runtime_checkable
class EmbeddingProvider(Protocol):
    """Contract for embedding generation."""

    @property
    def name(self) -> str:
        """Unique provider ID: 'ollama', 'openai', 'local-model'."""
        ...

    @property
    def info(self) -> EmbeddingInfo:
        ...

    def auth(self, config: dict) -> bool:
        """Verify connectivity / credentials."""
        ...

    def embed(self, text: str) -> list[float]:
        """Embed a single text. Returns vector."""
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Returns list of vectors."""
        ...
```

### Provider: Ollama

```python
class OllamaEmbeddingProvider:
    name = "ollama"
    info = EmbeddingInfo(
        display_name="Ollama (nomic-embed-text)",
        version="1.0.0",
        dimensions=768,
        max_tokens=8192,
        is_local=True,
        requires_auth=False,
    )
    # HTTP API: POST http://localhost:11434/api/embeddings
    # Model: nomic-embed-text
```

### Provider: OpenAI API

```python
class OpenAIEmbeddingProvider:
    name = "openai"
    info = EmbeddingInfo(
        display_name="OpenAI text-embedding-3-small",
        version="1.0.0",
        dimensions=1536,
        max_tokens=8191,
        is_local=False,
        requires_auth=True,
    )
    # For users who want higher quality and don't mind cloud
    # Credential: API key in system keyring
```

### Provider: Local model (model2vec / fastembed)

```python
class LocalModelEmbeddingProvider:
    name = "local-model"
    info = EmbeddingInfo(
        display_name="model2vec (local)",
        version="1.0.0",
        dimensions=256,
        max_tokens=512,
        is_local=True,
        requires_auth=False,
    )
    # No Ollama needed — pure Python
    # Lighter but lower quality than nomic-embed-text
    # Good fallback for machines without Ollama
```

### Registration

```yaml
# config.yaml
providers:
  embedding:
    ollama:
      enabled: true
      model: nomic-embed-text
      base_url: http://localhost:11434
    openai:
      enabled: false
      model: text-embedding-3-small
      credential: keyring
    local-model:
      enabled: false
      model: minishlab/potion-base-8M
```

---

## 4. Scraper Providers

**Purpose:** Browser-based data collection from LLM platforms that don't expose full APIs. Supplements official exports with project mapping, Knowledge files, and other data not available in export ZIPs.

### Contract

```python
from typing import Protocol, runtime_checkable
from dataclasses import dataclass
from playwright.sync_api import Browser

@dataclass
class ScraperInfo:
    display_name: str               # "Claude.ai Scraper"
    login_url: str                  # "https://claude.ai/login"
    capabilities: set[str]          # {"projects", "chat_mapping", "knowledge"}

@runtime_checkable
class ScraperProvider(Protocol):
    """Contract for browser-based data collection."""

    @property
    def name(self) -> str:
        """Unique provider ID: 'claude-scraper', 'chatgpt-scraper', etc."""
        ...

    @property
    def info(self) -> ScraperInfo:
        ...

    def login(self, browser: Browser) -> bool:
        """Navigate to login page, wait for user to authenticate.
        Returns True if login successful."""
        ...

    def scrape_projects(self, browser: Browser) -> list[RemoteProject]:
        """Scrape project/folder structure from sidebar."""
        ...

    def scrape_chat_mapping(self, browser: Browser) -> dict[str, str]:
        """Map chat_id → project_id by navigating the UI."""
        ...

    def scrape_knowledge(self, browser: Browser, project_id: str) -> list[Path]:
        """Download Knowledge files attached to a project."""
        ...
```

### Provider: Claude Scraper

```python
class ClaudeScraper:
    name = "claude-scraper"
    info = ScraperInfo(
        display_name="Claude.ai Scraper",
        login_url="https://claude.ai/login",
        capabilities={"projects", "chat_mapping", "knowledge"},
    )
    # One-time: map chats to projects, download Knowledge files
    # Requires: user logs in via browser, scraper reads sidebar
    # No API key needed — uses existing web session
```

### Provider: ChatGPT Scraper

```python
class ChatGPTScraper:
    name = "chatgpt-scraper"
    info = ScraperInfo(
        display_name="ChatGPT Scraper",
        login_url="https://chat.openai.com/auth/login",
        capabilities={"projects", "chat_mapping"},
    )
    # Scrape folder structure, custom GPT configs
```

### Provider: Gemini Scraper

```python
class GeminiScraper:
    name = "gemini-scraper"
    info = ScraperInfo(
        display_name="Gemini Scraper",
        login_url="https://gemini.google.com",
        capabilities={"projects", "chat_mapping"},
    )
    # Scrape Gems, extensions data
```

### Provider: Perplexity Scraper

```python
class PerplexityScraper:
    name = "perplexity-scraper"
    info = ScraperInfo(
        display_name="Perplexity Scraper",
        login_url="https://www.perplexity.ai",
        capabilities={"chat_mapping"},
    )
    # Scrape conversation threads and source citations
    # Perplexity has no official export — scraper is the only option
    # No API key needed — uses existing web session via Playwright
```

### Security

- Runs Playwright in **headed mode** — user sees exactly what happens
- No credentials stored — user logs in manually each time
- Read-only — never modifies data on the platform
- Rate-limited: 1-2 second delays between page navigations
- Requires `pip install anticlaw[scraper]` (Playwright ~50 MB)

### Registration

```yaml
# config.yaml
providers:
  scraper:
    claude:
      enabled: true
    chatgpt:
      enabled: false
    gemini:
      enabled: false
    perplexity:
      enabled: false
```

### CLI

```bash
aw scrape claude                    # launch browser, login, scrape project mapping
aw scrape claude --knowledge        # also download Knowledge files
aw scrape chatgpt                   # scrape ChatGPT structure
aw scrape gemini                    # scrape Gemini structure
aw scrape perplexity                # scrape Perplexity threads
```

---

## 5. Unified Provider Registry

All six families share common patterns:

```python
# src/anticlaw/providers/registry.py

from dataclasses import dataclass

@dataclass
class ProviderEntry:
    family: str          # "llm", "backup", "embedding"
    name: str            # "claude", "gdrive", "ollama"
    cls: type            # ClaudeProvider, GDriveBackupProvider, etc.
    extras: list[str]    # pip extras needed: ["scraper"], ["backup-gdrive"]

class ProviderRegistry:
    """Central registry for all provider types."""

    _providers: dict[str, dict[str, ProviderEntry]] = {}

    def register(self, family: str, name: str, cls: type, extras: list[str] = []):
        self._providers.setdefault(family, {})[name] = ProviderEntry(
            family=family, name=name, cls=cls, extras=extras
        )

    def get(self, family: str, name: str, config: dict):
        entry = self._providers[family][name]
        return entry.cls(config)

    def list_family(self, family: str) -> list[ProviderEntry]:
        return list(self._providers.get(family, {}).values())

    def list_all(self) -> list[ProviderEntry]:
        return [e for fam in self._providers.values() for e in fam.values()]

# Global registry instance
registry = ProviderRegistry()

# Auto-registration happens at import time:
# src/anticlaw/providers/llm/__init__.py registers LLM providers
# src/anticlaw/providers/backup/__init__.py registers Backup providers
# src/anticlaw/providers/embedding/__init__.py registers Embedding providers
# src/anticlaw/providers/scraper/__init__.py registers Scraper providers
# (Source and Input providers registered similarly)
```

### CLI

```bash
aw providers                           # list all registered providers
aw providers --family llm              # list LLM providers only
aw providers --family backup           # list backup providers only
aw providers --family embedding        # list embedding providers only
aw auth <provider>                     # configure credentials
aw auth status                         # show auth status for all providers
```

Example output:
```
$ aw providers

LLM Providers:
  ✅ claude        Claude.ai              [export_bulk, scrape]
  ⬚ chatgpt       ChatGPT                [export_bulk]
  ✅ ollama        Ollama (local)          [export_single, import]

Backup Providers:
  ✅ local         Local copy             /mnt/backup/anticlaw
  ✅ gdrive        Google Drive           folder: 1aBcDe...
  ⬚ s3            S3 / MinIO             (not configured)
  ⬚ rsync         rsync over SSH         (not configured)
  ⬚ webdav        WebDAV                 (not configured)

Embedding Providers:
  ✅ ollama        Ollama (nomic)         768-dim, local
  ⬚ openai        OpenAI                 (not configured)
  ⬚ local-model   model2vec              (not installed)

✅ = enabled + authenticated    ⬚ = disabled or not configured
```

---

## 6. Source Code Layout (updated)

```
src/anticlaw/providers/
├── __init__.py
├── registry.py              # ProviderRegistry + global instance
├── llm/
│   ├── __init__.py          # auto-register all LLM providers
│   ├── base.py              # LLMProvider Protocol + ProviderInfo
│   ├── claude.py
│   ├── chatgpt.py
│   ├── gemini.py
│   └── ollama.py
├── backup/
│   ├── __init__.py          # auto-register all backup providers
│   ├── base.py              # BackupProvider Protocol + BackupInfo + BackupResult
│   ├── local.py
│   ├── gdrive.py
│   ├── s3.py
│   ├── rsync.py
│   └── webdav.py
├── embedding/
│   ├── __init__.py          # auto-register all embedding providers
│   ├── base.py              # EmbeddingProvider Protocol + EmbeddingInfo
│   ├── ollama.py
│   ├── openai.py
│   └── local_model.py
└── scraper/
    ├── __init__.py          # auto-register all scraper providers
    ├── base.py              # ScraperProvider Protocol + ScraperInfo
    ├── claude.py            # Claude.ai project/knowledge scraper
    ├── chatgpt.py           # ChatGPT structure scraper
    ├── gemini.py            # Gemini data scraper
    └── perplexity.py        # Perplexity thread scraper
```

---

## 7. pip extras (updated)

```toml
# pyproject.toml
[project.optional-dependencies]
search       = ["bm25s"]
fuzzy        = ["rapidfuzz"]
semantic     = ["chromadb", "numpy", "httpx"]
llm          = ["httpx"]
sync         = ["httpx", "anthropic", "openai", "google-generativeai"]
daemon       = ["watchdog", "apscheduler", "pystray", "pillow", "plyer"]
scraper      = ["playwright"]
backup-gdrive = ["google-api-python-client", "google-auth-oauthlib"]
backup-s3    = ["boto3"]
backup-webdav = ["webdavclient3"]
embed-openai = ["openai"]
embed-local  = ["model2vec"]
dev          = ["pytest", "ruff", "pre-commit"]
all          = [
    "anticlaw[search,fuzzy,semantic,llm,daemon,scraper]",
    "anticlaw[backup-gdrive,backup-s3,backup-webdav]",
    "anticlaw[embed-openai,embed-local,dev]",
]
```
