"""CLI commands for scraping LLM platforms via HTTP API."""

from __future__ import annotations

from pathlib import Path

import click


@click.group("scrape")
def scrape_group() -> None:
    """Scrape chat→project mapping from LLM platforms.

    Uses direct HTTP API calls (no browser needed).
    Requires a session cookie from your browser.
    """


@scrape_group.command("claude")
@click.option(
    "--session-key",
    required=True,
    help=(
        "Session cookie value from claude.ai. "
        "To get it: open claude.ai → DevTools (F12) → Application tab "
        "→ Cookies → claude.ai → copy the 'sessionKey' value."
    ),
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("mapping.json"),
    show_default=True,
    help="Output path for the mapping JSON file.",
)
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="AnticLaw home directory (default: ~/anticlaw or ACL_HOME).",
)
def scrape_claude(session_key: str, output: Path, home: Path | None) -> None:
    """Scrape chat→project mapping from Claude.ai.

    \b
    How to get your session key:
      1. Open https://claude.ai in your browser
      2. Open DevTools (F12)
      3. Go to Application tab → Cookies → claude.ai
      4. Copy the value of 'sessionKey'

    \b
    Example:
      aw scrape claude --session-key "sk-ant-sid01-..."
      aw scrape claude --session-key "sk-ant-sid01-..." -o my-mapping.json

    \b
    Then use the mapping with import:
      aw import claude export.zip --mapping mapping.json
    """
    from anticlaw.core.fileutil import safe_filename
    from anticlaw.providers.scraper.claude import ClaudeScraper

    scraper = ClaudeScraper(session_key=session_key)
    click.echo("Scraping Claude.ai projects and chat mapping...")

    try:
        mapping = scraper.scrape(output)
    except ImportError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"Scrape failed: {e}")

    click.echo(f"Found {len(mapping.projects)} projects:")
    for proj_info in mapping.projects.values():
        name = proj_info.get("name", "Untitled")
        folder = safe_filename(name)
        has_instructions = bool(proj_info.get("instructions"))
        suffix = " (has instructions)" if has_instructions else ""
        chat_count = sum(1 for v in mapping.chats.values() if v == folder)
        click.echo(f"  - {name}: {chat_count} chats{suffix}")

    click.echo(
        f"\nTotal: {len(mapping.chats)} chats mapped "
        f"across {len(mapping.projects)} projects."
    )
    click.echo(f"Saved to: {output}")
    click.echo(f"\nUse with import: aw import claude export.zip --mapping {output}")
