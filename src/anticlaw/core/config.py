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
    "daemon": {
        "enabled": False,
        "autostart": False,
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
