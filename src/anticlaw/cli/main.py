"""CLI entry point for AnticLaw (aw command)."""

import click

from anticlaw import __version__
from anticlaw.cli.import_cmd import import_group
from anticlaw.cli.project_cmd import (
    create_group,
    list_cmd,
    move_cmd,
    reindex_cmd,
    show_cmd,
    tag_cmd,
)
from anticlaw.cli.mcp_cmd import mcp_group
from anticlaw.cli.search_cmd import search_cmd


@click.group()
@click.version_option(version=__version__, prog_name="anticlaw")
def cli() -> None:
    """AnticLaw — local-first knowledge base for LLM conversations."""


cli.add_command(import_group)
cli.add_command(search_cmd)
cli.add_command(list_cmd)
cli.add_command(show_cmd)
cli.add_command(move_cmd)
cli.add_command(tag_cmd)
cli.add_command(create_group)
cli.add_command(reindex_cmd)
cli.add_command(mcp_group)


if __name__ == "__main__":
    cli()
