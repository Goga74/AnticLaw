"""CLI command for initializing the AnticLaw knowledge base."""

from __future__ import annotations

import logging
from pathlib import Path

import click
import yaml

from anticlaw.core.config import DEFAULTS, config_path, resolve_home
from anticlaw.core.storage import ChatStorage

log = logging.getLogger(__name__)

_GITIGNORE_CONTENT = """\
# AnticLaw internals
.acl/meta.db
.acl/meta.db-wal
.acl/meta.db-shm
.acl/graph.db
.acl/graph.db-wal
.acl/graph.db-shm
.acl/chroma/
.acl/contexts/
.acl/backups/
.acl/daemon.pid
.acl/daemon.sock
.acl/cron.log

# OS files
.DS_Store
Thumbs.db
"""


@click.command("init")
@click.argument("path", required=False, type=click.Path(path_type=Path), default=None)
@click.option("--interactive", "-i", is_flag=True, help="Guided setup with prompts.")
def init_cmd(path: Path | None, interactive: bool) -> None:
    """Initialize a new AnticLaw knowledge base.

    Creates the directory structure, default config.yaml, and .gitignore.
    PATH defaults to ~/anticlaw (or ACL_HOME if set).

    Use --interactive for guided setup that asks about your preferences.
    """
    home = path or resolve_home()
    home = home.expanduser().resolve()

    if (home / ".acl" / "config.yaml").exists() and not interactive:
        click.echo(f"Knowledge base already initialized at {home}")
        click.echo("Use --interactive to reconfigure.")
        return

    # Create directory structure
    storage = ChatStorage(home)
    storage.init_home()

    # Build config
    config = _interactive_setup() if interactive else _default_config()

    # Write config.yaml
    cfg_path = config_path(home)
    cfg_path.write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    # Write .gitignore
    gitignore_path = home / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(_GITIGNORE_CONTENT, encoding="utf-8")

    click.echo(f"Initialized AnticLaw knowledge base at {home}")
    click.echo()
    click.echo("Directory structure:")
    click.echo(f"  {home}/")
    click.echo("    .acl/          config, databases, cache")
    click.echo("    _inbox/        imported chats (unsorted)")
    click.echo("    _archive/      archived chats")
    click.echo("    .gitignore     git-safe defaults")
    click.echo()
    click.echo("Next steps:")
    click.echo("  aw import claude <export.zip>     Import Claude conversations")
    click.echo("  aw import chatgpt <export.zip>    Import ChatGPT conversations")
    click.echo("  aw search \"query\"                  Search your knowledge base")
    click.echo("  aw mcp install claude-code         Connect to Claude Code")


def _default_config() -> dict:
    """Generate default config.yaml content."""
    return {
        "search": DEFAULTS["search"],
        "embeddings": DEFAULTS["embeddings"],
        "llm": DEFAULTS["llm"],
        "providers": {
            "claude": {"enabled": True},
            "chatgpt": {"enabled": True},
            "gemini": {"enabled": False},
        },
        "daemon": {
            "enabled": False,
            "autostart": False,
        },
    }


def _interactive_setup() -> dict:
    """Guided setup with prompts."""
    config = _default_config()

    click.echo()
    click.echo("AnticLaw Setup")
    click.echo("=" * 40)
    click.echo()

    # Providers
    click.echo("Which LLM platforms do you use?")
    config["providers"]["claude"]["enabled"] = click.confirm(
        "  Claude.ai?", default=True
    )
    config["providers"]["chatgpt"]["enabled"] = click.confirm(
        "  ChatGPT?", default=True
    )
    config["providers"]["gemini"]["enabled"] = click.confirm(
        "  Gemini?", default=False
    )

    # Local LLM
    click.echo()
    use_ollama = click.confirm(
        "Use Ollama for local AI (summarization, tagging, Q&A)?", default=False,
    )
    if use_ollama:
        model = click.prompt(
            "  Ollama model for text generation",
            default="llama3.1:8b",
        )
        config["llm"]["model"] = model
        embed_model = click.prompt(
            "  Ollama model for embeddings",
            default="nomic-embed-text",
        )
        config["embeddings"]["model"] = embed_model

    # Daemon
    click.echo()
    use_daemon = click.confirm(
        "Enable background daemon (file watching, auto-indexing)?", default=False,
    )
    config["daemon"]["enabled"] = use_daemon
    if use_daemon:
        config["daemon"]["autostart"] = click.confirm(
            "  Auto-start daemon on login?", default=False,
        )

    click.echo()
    return config
