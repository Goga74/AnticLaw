"""CLI commands for Telegram bot: aw bot start."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from anticlaw.core.config import load_config, resolve_home


@click.group("bot")
def bot_group() -> None:
    """Manage the AnticLaw Telegram bot."""


@bot_group.command("start")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
@click.option("--daemon", "daemonize", is_flag=True, help="Run in background.")
def bot_start(home: Path | None, daemonize: bool) -> None:
    """Start the Telegram bot (long polling)."""
    home_path = home or resolve_home()
    config = load_config(home_path / ".acl" / "config.yaml")
    bot_cfg = config.get("bot", {})

    # Get token from keyring
    token = _get_token()
    if not token:
        click.echo(
            "Error: No Telegram bot token configured.\n"
            "Run: aw auth bot  (to set token interactively)\n"
            "Or set via keyring API: "
            "keyring.set_password('anticlaw', 'telegram_token', 'TOKEN')"
        )
        raise SystemExit(1)

    allowed_ids = bot_cfg.get("allowed_user_ids", [])
    claude_path = bot_cfg.get("claude_code_path", "claude")

    # Setup logging
    log_level = bot_cfg.get("log_level", "info").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if daemonize:
        click.echo("Starting bot in background...")
        _start_background(home_path, token, allowed_ids, claude_path)
    else:
        click.echo(f"Starting bot (home={home_path})...")
        click.echo("Press Ctrl+C to stop.")

        from anticlaw.bot.bot import start_bot

        start_bot(
            token=token,
            home=home_path,
            allowed_user_ids=allowed_ids,
            claude_code_path=claude_path,
        )


@bot_group.command("auth")
def bot_auth() -> None:
    """Set Telegram bot token (stored in system keyring)."""
    token = click.prompt("Enter Telegram bot token", hide_input=True)
    if not token.strip():
        click.echo("Error: Token cannot be empty.")
        raise SystemExit(1)

    try:
        import keyring

        keyring.set_password("anticlaw", "telegram_token", token.strip())
        click.echo("Token saved to system keyring.")
    except Exception as e:
        click.echo(f"Error saving token: {e}")
        raise SystemExit(1) from e


def _get_token() -> str | None:
    """Retrieve Telegram token from keyring."""
    try:
        import keyring

        return keyring.get_password("anticlaw", "telegram_token")
    except Exception:
        return None


def _start_background(
    home: Path, token: str, allowed_ids: list[int], claude_path: str
) -> None:
    """Start bot as a background subprocess."""
    import subprocess
    import sys

    cmd = [sys.executable, "-m", "anticlaw.bot", "--token", token, "--home", str(home)]
    if allowed_ids:
        cmd.extend(["--allowed-ids", ",".join(str(i) for i in allowed_ids)])
    cmd.extend(["--claude-path", claude_path])

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    click.echo(f"Bot started in background (PID {proc.pid}).")
