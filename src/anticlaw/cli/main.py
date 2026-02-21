"""CLI entry point for AnticLaw (aw command)."""

import click

from anticlaw import __version__
from anticlaw.cli.import_cmd import import_group


@click.group()
@click.version_option(version=__version__, prog_name="anticlaw")
def cli() -> None:
    """AnticLaw — local-first knowledge base for LLM conversations."""


cli.add_command(import_group)


if __name__ == "__main__":
    cli()
