"""CLI scan command: aw scan."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from anticlaw.core.config import load_config, resolve_home
from anticlaw.core.meta_db import MetaDB
from anticlaw.providers.source.local_files import LocalFilesProvider

log = logging.getLogger(__name__)


@click.command("scan")
@click.argument("path", required=False, type=click.Path(path_type=Path))
@click.option("--watch", is_flag=True, help="Watch for changes after initial scan.")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def scan_cmd(path: Path | None, watch: bool, home: Path | None) -> None:
    """Index local files from configured paths or a specific path.

    Scans text, code, and PDF files and adds them to the search index.
    """
    home_path = home or resolve_home()
    config = load_config(home_path / ".acl" / "config.yaml")
    db_path = home_path / ".acl" / "meta.db"
    db = MetaDB(db_path)

    # Determine scan paths
    sources_config = config.get("sources", {}).get("local-files", {})
    if path:
        scan_paths = [path]
    else:
        configured_paths = sources_config.get("paths", [])
        if not configured_paths:
            click.echo(
                "No paths configured. Provide a path argument or configure "
                "'sources.local-files.paths' in config.yaml."
            )
            return
        scan_paths = [Path(p) for p in configured_paths]

    # Build provider from config
    extensions = sources_config.get("extensions")
    exclude = sources_config.get("exclude")
    max_size = sources_config.get("max_file_size_mb", 10)

    provider = LocalFilesProvider(
        extensions=extensions,
        exclude=exclude,
        max_file_size_mb=max_size,
    )

    click.echo(f"Scanning {len(scan_paths)} path(s)...")
    try:
        documents = provider.scan(scan_paths)

        indexed = 0
        skipped = 0
        for doc in documents:
            if not doc.content:
                skipped += 1
                continue
            # Check if file already indexed with same hash
            existing = db.get_source_file(doc.file_path)
            if existing and existing.get("hash") == doc.hash:
                skipped += 1
                continue
            # Use existing ID if re-indexing same file
            if existing:
                doc.id = existing["id"]
            db.index_source_file(doc)
            indexed += 1

        click.echo(f"Indexed: {indexed}, Skipped (unchanged): {skipped}")
        click.echo(f"Total source files in index: {db.count_source_files()}")

    finally:
        db.close()

    if watch:
        click.echo("Watching for changes... (press Ctrl+C to stop)")
        _watch_paths(scan_paths, provider, db_path)


def _watch_paths(
    paths: list[Path],
    provider: LocalFilesProvider,
    db_path: Path,
) -> None:
    """Watch directories for file changes and re-index."""
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        click.echo(
            "watchdog is required for --watch. "
            "Install with: pip install anticlaw[daemon]"
        )
        return

    class _Handler(FileSystemEventHandler):
        def __init__(self):
            self._extensions = provider._extensions

        def on_modified(self, event):
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.suffix.lower() not in self._extensions:
                return
            try:
                doc = provider.read(path)
                if doc.content:
                    db = MetaDB(db_path)
                    existing = db.get_source_file(doc.file_path)
                    if existing:
                        doc.id = existing["id"]
                    db.index_source_file(doc)
                    db.close()
                    click.echo(f"  Re-indexed: {path.name}")
            except Exception as e:
                log.debug("Watch handler error: %s", e)

        on_created = on_modified

    observer = Observer()
    handler = _Handler()
    for p in paths:
        p = p.expanduser().resolve()
        if p.is_dir():
            observer.schedule(handler, str(p), recursive=True)

    observer.start()
    try:
        import time

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
