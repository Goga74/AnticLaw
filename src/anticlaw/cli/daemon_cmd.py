"""CLI commands for daemon management: aw daemon start/stop/status/install/uninstall/logs."""

from __future__ import annotations

import json
import logging
import signal
import sys
import time
from pathlib import Path

import click

from anticlaw.core.config import load_config, resolve_home


@click.group("daemon")
def daemon_group() -> None:
    """Manage the AnticLaw background daemon."""


@daemon_group.command("start")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
@click.option("--no-tray", is_flag=True, help="Start without system tray icon.")
@click.option("--no-watch", is_flag=True, help="Start without file watcher.")
@click.option("--no-schedule", is_flag=True, help="Start without task scheduler.")
def daemon_start(home: Path | None, no_tray: bool, no_watch: bool, no_schedule: bool) -> None:
    """Start the daemon (foreground)."""
    home_path = home or resolve_home()
    config = load_config(home_path / ".acl" / "config.yaml")
    daemon_cfg = config.get("daemon", {})

    # Setup logging
    log_path = home_path / ".acl" / "daemon.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, daemon_cfg.get("log_level", "info").upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(str(log_path), encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    log = logging.getLogger("anticlaw.daemon")
    log.info("Daemon starting (home=%s)", home_path)

    # Write PID
    from anticlaw.daemon.service import write_pid, remove_pid

    write_pid(home_path)
    click.echo(f"Daemon started (home={home_path})")

    components = []

    # Start file watcher
    watcher = None
    if not no_watch and daemon_cfg.get("watch", {}).get("enabled", True):
        try:
            from anticlaw.daemon.watcher import FileWatcher

            watch_cfg = daemon_cfg.get("watch", {})
            watcher = FileWatcher(
                home=home_path,
                debounce_seconds=watch_cfg.get("debounce_seconds", 2.0),
                ignore_patterns=set(watch_cfg.get("ignore_patterns", [])) or None,
            )
            watcher.start()
            components.append("watcher")
            click.echo("  File watcher: active")
        except RuntimeError as e:
            click.echo(f"  File watcher: failed ({e})")

    # Start scheduler
    scheduler = None
    if not no_schedule:
        try:
            from anticlaw.daemon.scheduler import TaskScheduler

            scheduler = TaskScheduler(home_path, config)
            scheduler.start()
            components.append("scheduler")
            click.echo("  Scheduler: active")
        except RuntimeError as e:
            click.echo(f"  Scheduler: failed ({e})")

    # Start IPC server
    ipc_server = None
    try:
        from anticlaw.daemon.ipc import IPCServer

        def handle_ipc(command: dict) -> dict:
            action = command.get("action", "")
            if action == "ping":
                return {
                    "status": "ok",
                    "components": components,
                    "home": str(home_path),
                }
            elif action == "status":
                return {
                    "status": "ok",
                    "watcher": watcher.is_running if watcher else False,
                    "scheduler": scheduler.is_running if scheduler else False,
                    "components": components,
                    "home": str(home_path),
                }
            elif action == "force-backup":
                if scheduler:
                    ok, msg = scheduler.run_task_now("backup")
                    return {"status": "ok" if ok else "error", "message": msg}
                return {"status": "error", "message": "Scheduler not running"}
            elif action == "force-sync":
                if scheduler:
                    ok, msg = scheduler.run_task_now("sync")
                    return {"status": "ok" if ok else "error", "message": msg}
                return {"status": "error", "message": "Scheduler not running"}
            elif action == "pause":
                if watcher and watcher.is_running:
                    watcher.stop()
                    return {"status": "ok", "message": "Watcher paused"}
                return {"status": "ok", "message": "Watcher not running"}
            elif action == "resume":
                if watcher and not watcher.is_running:
                    watcher.start()
                    return {"status": "ok", "message": "Watcher resumed"}
                return {"status": "ok", "message": "Watcher already running"}
            elif action == "stop":
                return {"status": "ok", "message": "Shutting down"}
            elif action == "run-task":
                task_name = command.get("task", "")
                if scheduler:
                    ok, msg = scheduler.run_task_now(task_name)
                    return {"status": "ok" if ok else "error", "message": msg}
                return {"status": "error", "message": "Scheduler not running"}
            else:
                return {"status": "error", "message": f"Unknown action: {action}"}

        ipc_server = IPCServer(home_path, handler=handle_ipc)
        ipc_server.start()
        components.append("ipc")
        click.echo("  IPC server: active")
    except Exception as e:
        click.echo(f"  IPC server: failed ({e})")

    # Start tray icon
    tray = None
    if not no_tray and daemon_cfg.get("tray", {}).get("enabled", True):
        try:
            from anticlaw.daemon.tray import TrayIcon

            def on_quit():
                nonlocal _shutdown
                _shutdown = True

            tray = TrayIcon(
                home=home_path,
                on_force_backup=lambda: scheduler.run_task_now("backup") if scheduler else None,
                on_force_sync=lambda: scheduler.run_task_now("sync") if scheduler else None,
                on_pause=lambda: watcher.stop() if watcher else None,
                on_resume=lambda: watcher.start() if watcher else None,
                on_quit=on_quit,
            )
            tray.start()
            components.append("tray")
            click.echo("  Tray icon: active")
        except RuntimeError as e:
            click.echo(f"  Tray icon: skipped ({e})")

    click.echo(f"\nDaemon running with: {', '.join(components)}")
    click.echo("Press Ctrl+C to stop.")

    # Main loop — wait for shutdown signal
    _shutdown = False

    def signal_handler(sig, frame):
        nonlocal _shutdown
        _shutdown = True

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        while not _shutdown:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    # Cleanup
    click.echo("\nShutting down...")
    if tray:
        tray.stop()
    if ipc_server:
        ipc_server.stop()
    if scheduler:
        scheduler.stop()
    if watcher:
        watcher.stop()
    remove_pid(home_path)
    click.echo("Daemon stopped.")


@daemon_group.command("stop")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def daemon_stop(home: Path | None) -> None:
    """Stop the running daemon."""
    home_path = home or resolve_home()

    # Try IPC first
    from anticlaw.daemon.ipc import ipc_send

    resp = ipc_send(home_path, {"action": "stop"}, timeout=3.0)
    if resp.get("status") == "ok":
        click.echo("Daemon shutdown signal sent.")
        # Also kill the process
        from anticlaw.daemon.service import read_pid, is_process_running

        pid = read_pid(home_path)
        if pid and is_process_running(pid):
            import os
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        return

    # Fallback: try PID file
    from anticlaw.daemon.service import read_pid, is_process_running, remove_pid

    pid = read_pid(home_path)
    if pid and is_process_running(pid):
        import os
        try:
            os.kill(pid, signal.SIGTERM)
            click.echo(f"Sent SIGTERM to daemon (PID {pid}).")
        except OSError as e:
            click.echo(f"Failed to stop daemon: {e}")
    else:
        click.echo("Daemon is not running.")
        if pid:
            remove_pid(home_path)


@daemon_group.command("status")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def daemon_status(home: Path | None) -> None:
    """Check daemon status."""
    home_path = home or resolve_home()

    # Try IPC
    from anticlaw.daemon.ipc import ipc_send

    resp = ipc_send(home_path, {"action": "status"}, timeout=3.0)
    if resp.get("status") == "ok":
        click.echo("Daemon: running")
        click.echo(f"  Home: {resp.get('home', '?')}")
        click.echo(f"  Components: {', '.join(resp.get('components', []))}")
        click.echo(f"  Watcher: {'active' if resp.get('watcher') else 'inactive'}")
        click.echo(f"  Scheduler: {'active' if resp.get('scheduler') else 'inactive'}")
        return

    # Fallback: check PID
    from anticlaw.daemon.service import read_pid, is_process_running

    pid = read_pid(home_path)
    if pid and is_process_running(pid):
        click.echo(f"Daemon: running (PID {pid}, IPC unreachable)")
    else:
        click.echo("Daemon: not running")


@daemon_group.command("install")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def daemon_install(home: Path | None) -> None:
    """Register daemon as a system service (auto-start on boot)."""
    home_path = home or resolve_home()

    from anticlaw.daemon.service import install_service

    msg = install_service(home_path)
    click.echo(msg)


@daemon_group.command("uninstall")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def daemon_uninstall(home: Path | None) -> None:
    """Remove daemon system service."""
    home_path = home or resolve_home()

    from anticlaw.daemon.service import uninstall_service

    msg = uninstall_service(home_path)
    click.echo(msg)


@daemon_group.command("logs")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
@click.option("-n", "--lines", default=50, help="Number of lines to show.")
def daemon_logs(home: Path | None, lines: int) -> None:
    """Show daemon log (last N lines)."""
    home_path = home or resolve_home()
    log_path = home_path / ".acl" / "daemon.log"

    if not log_path.exists():
        click.echo("No daemon log found.")
        return

    content = log_path.read_text(encoding="utf-8")
    log_lines = content.splitlines()
    for line in log_lines[-lines:]:
        click.echo(line)
