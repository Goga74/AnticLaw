"""CLI entry point for AnticLaw (aw command)."""

import click

from anticlaw import __version__


@click.group()
@click.version_option(version=__version__, prog_name="anticlaw")
def cli() -> None:
    """AnticLaw — local-first knowledge base for LLM conversations."""


if __name__ == "__main__":
    cli()
