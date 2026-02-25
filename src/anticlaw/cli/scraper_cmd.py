"""CLI command for scraping LLM platforms: aw scrape."""

from __future__ import annotations

from pathlib import Path

import click

from anticlaw.core.config import resolve_home


@click.group("scrape")
def scrape_group() -> None:
    """Scrape chat→project mapping from LLM platforms via browser."""


@scrape_group.command("claude")
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    default=Path("mapping.json"),
    show_default=True,
    help="Path to save the mapping JSON file.",
)
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def scrape_claude(output: Path, home: Path | None) -> None:
    """Scrape chat→project mapping from claude.ai.

    Opens a browser window. Log in to claude.ai manually, then the scraper
    collects which chats belong to which projects.

    \b
    Output: mapping.json with {chat_uuid: project_name, ...}
    Usage:
      aw scrape claude                        # Save to ./mapping.json
      aw scrape claude -o my-mapping.json     # Custom output path
      aw import claude export.zip --mapping mapping.json  # Use with import
    """
    try:
        from anticlaw.providers.scraper.claude import ClaudeScraper
    except ImportError as err:
        click.echo(
            "Error: scraper dependencies not installed.\n"
            "Run: pip install anticlaw[scraper] && playwright install chromium"
        )
        raise SystemExit(1) from err

    scraper = ClaudeScraper()

    click.echo("Launching browser... Log in to claude.ai to continue.")
    click.echo("(You have 5 minutes to complete login.)\n")

    try:
        mapping = scraper.scrape(output=output)
    except ImportError:
        click.echo(
            "Error: Playwright is not installed.\n"
            "Run: pip install anticlaw[scraper] && playwright install chromium"
        )
        raise SystemExit(1)
    except RuntimeError as err:
        click.echo(f"Error: {err}")
        raise SystemExit(1)

    stats = scraper.summary()
    projects = scraper.projects

    click.echo(f"\nFound {stats['projects']} projects, collected chats:")
    for proj in projects:
        click.echo(f"  {proj.name}: {len(proj.chat_uuids)} chats")

    click.echo(
        f"\nMapping saved: {stats['mapped_chats']} chats "
        f"→ {stats['projects']} projects"
    )
    click.echo(f"Output: {output}")
    click.echo(
        f"\nNext step: aw import claude <export.zip> --mapping {output}"
    )
