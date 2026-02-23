"""CLI entry point for AnticLaw (aw command)."""

import click

from anticlaw import __version__
from anticlaw.cli.api_cmd import api_group, ui_cmd
from anticlaw.cli.backup_cmd import backup_group
from anticlaw.cli.cron_cmd import cron_group
from anticlaw.cli.daemon_cmd import daemon_group
from anticlaw.cli.graph_cmd import related_cmd, timeline_cmd, why_cmd
from anticlaw.cli.import_cmd import import_group
from anticlaw.cli.init_cmd import init_cmd
from anticlaw.cli.knowledge_cmd import (
    duplicates_cmd,
    health_cmd,
    inbox_cmd,
    restore_cmd,
    retention_group,
    stale_cmd,
    stats_cmd,
)
from anticlaw.cli.llm_cmd import ask_cmd, autotag_cmd, summarize_cmd
from anticlaw.cli.mcp_cmd import mcp_group
from anticlaw.cli.project_cmd import (
    create_group,
    list_cmd,
    move_cmd,
    reindex_cmd,
    show_cmd,
    tag_cmd,
)
from anticlaw.cli.scan_cmd import scan_cmd
from anticlaw.cli.search_cmd import search_cmd


@click.group()
@click.version_option(version=__version__, prog_name="anticlaw")
def cli() -> None:
    """AnticLaw — local-first knowledge base for LLM conversations."""


cli.add_command(init_cmd)
cli.add_command(import_group)
cli.add_command(search_cmd)
cli.add_command(list_cmd)
cli.add_command(show_cmd)
cli.add_command(move_cmd)
cli.add_command(tag_cmd)
cli.add_command(create_group)
cli.add_command(reindex_cmd)
cli.add_command(mcp_group)
cli.add_command(related_cmd)
cli.add_command(why_cmd)
cli.add_command(timeline_cmd)
cli.add_command(summarize_cmd)
cli.add_command(autotag_cmd)
cli.add_command(ask_cmd)
cli.add_command(daemon_group)
cli.add_command(backup_group)
cli.add_command(cron_group)
cli.add_command(inbox_cmd)
cli.add_command(stale_cmd)
cli.add_command(duplicates_cmd)
cli.add_command(health_cmd)
cli.add_command(retention_group)
cli.add_command(restore_cmd)
cli.add_command(stats_cmd)
cli.add_command(scan_cmd)
cli.add_command(api_group)
cli.add_command(ui_cmd)


if __name__ == "__main__":
    cli()
