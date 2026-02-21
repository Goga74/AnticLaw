"""CLI commands for MCP server management: aw mcp."""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.group("mcp")
def mcp_group() -> None:
    """Manage the AnticLaw MCP server."""


@mcp_group.command("start")
def mcp_start() -> None:
    """Start the MCP server (stdio transport).

    This runs the FastMCP server in stdio mode. Typically invoked by
    an MCP client (Claude Code, Cursor) rather than manually.
    """
    from anticlaw.mcp.server import mcp

    click.echo("Starting AnticLaw MCP server (stdio)...", err=True)
    mcp.run()


@mcp_group.command("install")
@click.argument("target", type=click.Choice(["claude-code", "cursor"]))
def mcp_install(target: str) -> None:
    """Register AnticLaw as an MCP server for a client.

    TARGET is the MCP client to configure: claude-code or cursor.
    """
    from anticlaw.mcp.hooks import install_claude_code, install_cursor

    python_exe = sys.executable

    if target == "claude-code":
        path = install_claude_code(python_exe)
        click.echo(f"Registered AnticLaw MCP server in {path}")
        click.echo(f"  Command: {python_exe} -m anticlaw.mcp")
        click.echo("Restart Claude Code to activate.")
    elif target == "cursor":
        path = install_cursor(python_exe)
        click.echo(f"Registered AnticLaw MCP server in {path}")
        click.echo(f"  Command: {python_exe} -m anticlaw.mcp")
        click.echo("Restart Cursor to activate.")
