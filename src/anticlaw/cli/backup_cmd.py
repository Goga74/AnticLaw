"""CLI commands for backup management: aw backup now/list/restore/verify/status."""

from __future__ import annotations

import json
from pathlib import Path

import click

from anticlaw.core.config import load_config, resolve_home


def _get_backup_providers(home: Path, provider_filter: str | None = None) -> list[tuple[str, dict]]:
    """Load enabled backup provider configs. Returns [(name, config), ...]."""
    config = load_config(home / ".acl" / "config.yaml")

    # Check daemon.backup.targets first
    daemon_cfg = config.get("daemon", {}).get("backup", {})
    targets = daemon_cfg.get("targets", [])

    # Also check providers.backup section
    providers_cfg = config.get("providers", {}).get("backup", {})

    result = []

    for target in targets:
        name = target.get("type", "")
        if provider_filter and name != provider_filter:
            continue
        # Merge with providers section
        merged = dict(providers_cfg.get(name, {}))
        merged.update(target)
        result.append((name, merged))

    # Add providers not in targets
    for name, pcfg in providers_cfg.items():
        if provider_filter and name != provider_filter:
            continue
        if pcfg.get("enabled", False) and not any(n == name for n, _ in result):
            result.append((name, pcfg))

    return result


def _instantiate_provider(name: str, config: dict):
    """Create a backup provider instance."""
    if name == "local":
        from anticlaw.providers.backup.local import LocalBackupProvider
        return LocalBackupProvider(config)
    elif name == "gdrive":
        from anticlaw.providers.backup.gdrive import GDriveBackupProvider
        return GDriveBackupProvider(config)
    else:
        raise click.ClickException(f"Unknown backup provider: {name}")


def _load_manifest(home: Path, provider_name: str) -> dict | None:
    """Load backup manifest for a provider."""
    path = home / ".acl" / f"backup_manifest_{provider_name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_manifest(home: Path, provider_name: str, manifest: dict) -> None:
    """Save backup manifest for a provider."""
    path = home / ".acl" / f"backup_manifest_{provider_name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


@click.group("backup")
def backup_group() -> None:
    """Manage backups of the knowledge base."""


@backup_group.command("now")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
@click.option("--provider", default=None, help="Run specific provider only.")
def backup_now(home: Path | None, provider: str | None) -> None:
    """Run backup now (all enabled providers or a specific one)."""
    home_path = home or resolve_home()
    providers = _get_backup_providers(home_path, provider)

    if not providers:
        if provider:
            click.echo(f"Backup provider not configured: {provider}")
            click.echo("Configure in config.yaml under daemon.backup.targets or providers.backup.")
        else:
            click.echo("No backup providers configured.")
            click.echo("Configure in config.yaml under daemon.backup.targets or providers.backup.")
        return

    for name, cfg in providers:
        click.echo(f"Backing up with {name}...")
        try:
            bp = _instantiate_provider(name, cfg)
            manifest = _load_manifest(home_path, name)
            result, new_manifest = bp.backup(home_path, manifest)
            _save_manifest(home_path, name, new_manifest)

            if result.success:
                click.echo(
                    f"  OK: {result.files_copied} copied, "
                    f"{result.files_skipped} skipped, "
                    f"{result.bytes_transferred} bytes "
                    f"({result.duration_seconds:.1f}s)"
                )
            else:
                click.echo(f"  FAILED: {', '.join(result.errors)}")
        except Exception as e:
            click.echo(f"  Error: {e}")


@backup_group.command("list")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
@click.option("--provider", default=None, help="List snapshots for specific provider.")
def backup_list(home: Path | None, provider: str | None) -> None:
    """List available backup snapshots."""
    home_path = home or resolve_home()
    providers = _get_backup_providers(home_path, provider)

    if not providers:
        click.echo("No backup providers configured.")
        return

    for name, cfg in providers:
        click.echo(f"\n{name}:")
        try:
            bp = _instantiate_provider(name, cfg)
            snapshots = bp.list_snapshots()
            if not snapshots:
                click.echo("  No snapshots found.")
                continue
            for snap in snapshots:
                size = snap.get("size_bytes", "?")
                files = snap.get("files", "?")
                click.echo(f"  {snap['id']}  ({files} files, {size} bytes)")
        except Exception as e:
            click.echo(f"  Error: {e}")


@backup_group.command("restore")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
@click.option("--provider", required=True, help="Provider to restore from.")
@click.option("--snapshot", default=None, help="Specific snapshot ID (default: latest).")
@click.option("--target", type=click.Path(path_type=Path), default=None, help="Restore target directory.")
def backup_restore(
    home: Path | None, provider: str, snapshot: str | None, target: Path | None,
) -> None:
    """Restore from a backup snapshot."""
    home_path = home or resolve_home()
    target_path = target or home_path

    providers = _get_backup_providers(home_path, provider)
    if not providers:
        click.echo(f"Backup provider not configured: {provider}")
        return

    name, cfg = providers[0]
    click.echo(f"Restoring from {name}...")

    try:
        bp = _instantiate_provider(name, cfg)
        result = bp.restore(target_path, snapshot)

        if result.success:
            click.echo(
                f"Restored {result.files_copied} files, "
                f"{result.bytes_transferred} bytes "
                f"({result.duration_seconds:.1f}s)"
            )
        else:
            click.echo(f"Restore failed: {', '.join(result.errors)}")
    except Exception as e:
        click.echo(f"Error: {e}")


@backup_group.command("verify")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
@click.option("--provider", default=None, help="Verify specific provider only.")
def backup_verify(home: Path | None, provider: str | None) -> None:
    """Verify backup integrity."""
    home_path = home or resolve_home()
    providers = _get_backup_providers(home_path, provider)

    if not providers:
        click.echo("No backup providers configured.")
        return

    for name, cfg in providers:
        try:
            bp = _instantiate_provider(name, cfg)
            ok = bp.verify()
            status = "OK" if ok else "FAILED"
            click.echo(f"  {name}: {status}")
        except Exception as e:
            click.echo(f"  {name}: ERROR ({e})")


@backup_group.command("status")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def backup_status(home: Path | None) -> None:
    """Show last backup time per provider."""
    home_path = home or resolve_home()
    providers = _get_backup_providers(home_path)

    if not providers:
        click.echo("No backup providers configured.")
        return

    for name, _cfg in providers:
        manifest = _load_manifest(home_path, name)
        if manifest:
            last = manifest.get("last_backup", "unknown")
            click.echo(f"  {name}: last backup {last}")
        else:
            click.echo(f"  {name}: no backups yet")
