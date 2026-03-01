"""CLI commands for scraping LLM platforms via Playwright CDP."""

from __future__ import annotations

from pathlib import Path

import click


@click.group("scrape")
def scrape_group() -> None:
    """Scrape chat→project mapping from LLM platforms.

    Uses Playwright response interception via Chrome DevTools Protocol (CDP).
    Requires Chrome to be running with remote debugging enabled.
    """


@scrape_group.command("claude")
@click.option(
    "--cdp-url",
    default="http://localhost:9222",
    show_default=True,
    help="Chrome DevTools Protocol endpoint URL.",
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
def scrape_claude(cdp_url: str, output: Path, home: Path | None) -> None:
    """Scrape chat→project mapping from Claude.ai via Playwright CDP.

    \b
    Prerequisites:
      1. Start Chrome with remote debugging:
         chrome --remote-debugging-port=9222
      2. Log in to https://claude.ai in that Chrome instance

    \b
    Usage:
      aw scrape claude
      aw scrape claude --cdp-url http://localhost:9333
      aw scrape claude -o my-mapping.json

    \b
    How it works:
      - Connects to Chrome via CDP (no extra login needed)
      - Intercepts API responses as you browse projects
      - You click through your projects in Claude
      - Press Enter when done to save the mapping

    \b
    Then use the mapping with import:
      aw import claude export.zip --mapping mapping.json
    """
    from anticlaw.core.fileutil import safe_filename
    from anticlaw.providers.scraper.claude import ClaudeScraper

    scraper = ClaudeScraper(cdp_url=cdp_url)
    click.echo(f"Connecting to Chrome at {cdp_url}...")

    try:
        mapping = scraper.scrape(output)
    except ImportError as e:
        raise click.ClickException(str(e)) from e
    except Exception as e:
        raise click.ClickException(f"Scrape failed: {e}") from e

    click.echo(f"\nFound {len(mapping.projects)} projects:")
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
