"""CLI api command: aw api."""

from __future__ import annotations

from pathlib import Path

import click

from anticlaw.core.config import load_config, resolve_home


@click.group("api")
def api_group() -> None:
    """HTTP API server management."""


@api_group.command("start")
@click.option("--port", "-p", default=None, type=int, help="Port (default: 8420).")
@click.option("--host", default=None, help="Host (default: 127.0.0.1).")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def api_start(port: int | None, host: str | None, home: Path | None) -> None:
    """Start the HTTP API server."""
    try:
        import uvicorn
    except ImportError:
        click.echo(
            "FastAPI and uvicorn are required. "
            "Install with: pip install anticlaw[api]"
        )
        return

    home_path = home or resolve_home()
    config = load_config(home_path / ".acl" / "config.yaml")
    api_config = config.get("api", {})

    final_host = host or api_config.get("host", "127.0.0.1")
    final_port = port or api_config.get("port", 8420)
    cors_origins = api_config.get("cors_origins", [])

    # Resolve API key
    api_key_setting = api_config.get("api_key")
    api_key: str | None = None
    if api_key_setting == "keyring":
        try:
            import keyring

            api_key = keyring.get_password("anticlaw", "api_key")
        except Exception:
            pass
    elif api_key_setting:
        api_key = api_key_setting

    from anticlaw.api.server import create_app

    app = create_app(home=home_path, api_key=api_key, cors_origins=cors_origins)

    click.echo(f"Starting AnticLaw API at http://{final_host}:{final_port}")
    if api_key:
        click.echo("API key authentication enabled for remote access.")
    else:
        click.echo("No API key configured — localhost access only.")

    uvicorn.run(app, host=final_host, port=final_port, log_level="info")
