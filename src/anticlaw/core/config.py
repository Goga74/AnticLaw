"""Configuration loader for AnticLaw."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

DEFAULTS: dict = {
    "home": "~/anticlaw",
    "search": {
        "alpha": 0.6,
        "max_results": 20,
        "default_max_tokens": 4000,
    },
    "embeddings": {
        "provider": "ollama",
        "model": "nomic-embed-text",
        "dimensions": 768,
    },
    "llm": {
        "provider": "ollama",
        "model": "llama3.1:8b",
        "base_url": "http://localhost:11434",
    },
    "graph": {
        "temporal_window_minutes": 30,
        "semantic_top_k": 3,
        "auto_entities": True,
    },
    "retention": {
        "archive_days": 30,
        "purge_days": 180,
        "importance_decay_days": 30,
    },
    "providers": {
        "claude": {"enabled": True},
        "chatgpt": {"enabled": False},
        "gemini": {"enabled": False},
    },
    "mcp": {
        "auto_save_reminder_turns": [10, 20, 30],
        "pre_compact_block": True,
    },
    "sources": {
        "local-files": {
            "enabled": False,
            "paths": [],
            "extensions": [
                ".java", ".py", ".js", ".ts", ".go", ".rs", ".sql",
                ".txt", ".md", ".json", ".xml", ".yaml", ".yml", ".toml",
                ".csv", ".properties", ".ini", ".cfg", ".html", ".css",
                ".sh", ".pdf",
            ],
            "exclude": [
                "node_modules", ".git", "__pycache__", "target",
                "build", "dist", ".idea", ".vscode",
            ],
            "max_file_size_mb": 10,
        },
    },
    "api": {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 8420,
        "api_key": None,
        "cors_origins": [],
    },
    "ui": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8420,
        "open_browser": True,
        "theme": "auto",
    },
    # Bidirectional LLM sync (Phase 14)
    # WARNING: Cloud API access (Claude, ChatGPT) requires SEPARATE paid API keys.
    # Web subscriptions (Claude Pro $20/mo, ChatGPT Plus $20/mo) do NOT provide API access.
    # Gemini has a free tier: 15 RPM, 1M tokens/day.
    # Ollama is free — runs locally, no API key needed.
    "sync": {
        "enabled": False,
        "default_push_target": None,
        "auto_push_drafts": False,
        "providers": {
            "claude": {"api_key": "keyring"},
            "chatgpt": {"api_key": "keyring"},
            "gemini": {"api_key": "keyring"},
            "ollama": {},
        },
    },
    "daemon": {
        "enabled": False,
        "autostart": False,
        "log_level": "info",
        "watch": {
            "enabled": True,
            "auto_index": True,
            "auto_project": "ask",
            "debounce_seconds": 2,
            "ignore_patterns": ["*.tmp", "*.swp", ".git/*"],
        },
        "backup": {
            "enabled": False,
            "targets": [],
        },
        "tray": {
            "enabled": True,
            "show_notifications": True,
        },
        "tasks": [],
    },
}


def resolve_home() -> Path:
    """Resolve ACL_HOME: env var > config > default ~/anticlaw."""
    env_home = os.environ.get("ACL_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()
    return Path("~/anticlaw").expanduser().resolve()


def config_path(home: Path | None = None) -> Path:
    """Return the path to config.yaml."""
    if home is None:
        home = resolve_home()
    return home / ".acl" / "config.yaml"


def load_config(path: Path | None = None) -> dict:
    """Load config.yaml and merge with defaults.

    Args:
        path: Explicit path to config.yaml. If None, uses default location.

    Returns:
        Merged configuration dict.
    """
    if path is None:
        path = config_path()

    user_config: dict = {}
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8")
            user_config = yaml.safe_load(raw) or {}
        except Exception:
            log.warning("Failed to read config at %s, using defaults", path, exc_info=True)

    merged = _deep_merge(DEFAULTS, user_config)

    # Resolve home path
    home_str = os.environ.get("ACL_HOME") or merged.get("home", "~/anticlaw")
    merged["home"] = str(Path(home_str).expanduser().resolve())

    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
