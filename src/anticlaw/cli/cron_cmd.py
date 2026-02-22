"""CLI commands for cron task management: aw cron list/add/run/logs/remove."""

from __future__ import annotations

from pathlib import Path

import click

from anticlaw.core.config import load_config, resolve_home


@click.group("cron")
def cron_group() -> None:
    """Manage scheduled cron tasks."""


@cron_group.command("list")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def cron_list(home: Path | None) -> None:
    """List all configured cron tasks."""
    home_path = home or resolve_home()
    config = load_config(home_path / ".acl" / "config.yaml")

    from anticlaw.daemon.scheduler import TaskScheduler

    sched = TaskScheduler(home_path, config)
    tasks = sched.get_tasks()

    if not tasks:
        click.echo("No cron tasks configured.")
        return

    click.echo(f"{'Name':<20} {'Schedule':<16} {'Action':<18} {'Enabled'}")
    click.echo("-" * 70)
    for task in tasks:
        name = task.get("name", "?")
        schedule = task.get("schedule", "?")
        action = task.get("action", "?")
        enabled = "yes" if task.get("enabled", True) else "no"
        click.echo(f"{name:<20} {schedule:<16} {action:<18} {enabled}")


@cron_group.command("add")
@click.argument("name")
@click.argument("schedule")
@click.argument("action")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
@click.option("--params", default=None, help="JSON params for the task.")
def cron_add(name: str, schedule: str, action: str, home: Path | None, params: str | None) -> None:
    """Add a new cron task.

    NAME is the task identifier.
    SCHEDULE is a cron expression (e.g. "0 3 * * *").
    ACTION is the task action (reindex, backup, health, shell, etc.).
    """
    import json

    import yaml

    home_path = home or resolve_home()
    config_path = home_path / ".acl" / "config.yaml"

    config = load_config(config_path)
    daemon_cfg = config.setdefault("daemon", {})
    tasks = daemon_cfg.setdefault("tasks", [])

    # Check for duplicate
    for t in tasks:
        if t.get("name") == name:
            click.echo(f"Task '{name}' already exists. Remove it first.")
            return

    new_task = {
        "name": name,
        "schedule": schedule,
        "action": action,
        "enabled": True,
    }
    if params:
        try:
            new_task["params"] = json.loads(params)
        except json.JSONDecodeError as e:
            click.echo(f"Invalid JSON params: {e}")
            return

    tasks.append(new_task)

    # Write back to config
    config_path.parent.mkdir(parents=True, exist_ok=True)
    # Only write the daemon section to avoid overwriting other config
    user_config: dict = {}
    if config_path.exists():
        try:
            user_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass

    user_config.setdefault("daemon", {})["tasks"] = tasks
    config_path.write_text(
        yaml.dump(user_config, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    click.echo(f"Added task: {name} ({schedule}) -> {action}")


@cron_group.command("run")
@click.argument("name")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def cron_run(name: str, home: Path | None) -> None:
    """Run a cron task immediately."""
    home_path = home or resolve_home()

    # Try via IPC first (if daemon is running)
    from anticlaw.daemon.ipc import ipc_send

    resp = ipc_send(home_path, {"action": "run-task", "task": name}, timeout=60.0)
    if resp.get("status") == "ok":
        click.echo(f"Task '{name}': {resp.get('message', 'done')}")
        return
    elif resp.get("status") == "error" and "Cannot connect" not in resp.get("message", ""):
        click.echo(f"Task '{name}' failed: {resp.get('message', '?')}")
        return

    # Fallback: run directly (daemon not running)
    config = load_config(home_path / ".acl" / "config.yaml")

    from anticlaw.daemon.scheduler import TaskScheduler

    sched = TaskScheduler(home_path, config)
    ok, msg = sched.run_task_now(name)

    if ok:
        click.echo(f"Task '{name}': {msg}")
    else:
        click.echo(f"Task '{name}' failed: {msg}")


@cron_group.command("logs")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
@click.option("-n", "--lines", default=50, help="Number of lines to show.")
def cron_logs(home: Path | None, lines: int) -> None:
    """Show cron execution log."""
    home_path = home or resolve_home()
    config = load_config(home_path / ".acl" / "config.yaml")

    from anticlaw.daemon.scheduler import TaskScheduler

    sched = TaskScheduler(home_path, config)
    log_lines = sched.get_log_lines(n=lines)

    if not log_lines:
        click.echo("No cron log entries.")
        return

    for line in log_lines:
        click.echo(line)


@cron_group.command("remove")
@click.argument("name")
@click.option(
    "--home",
    type=click.Path(path_type=Path),
    default=None,
    help="Override ACL_HOME path.",
)
def cron_remove(name: str, home: Path | None) -> None:
    """Remove a cron task by name."""
    import yaml

    home_path = home or resolve_home()
    config_path = home_path / ".acl" / "config.yaml"

    config = load_config(config_path)
    daemon_cfg = config.get("daemon", {})
    tasks = daemon_cfg.get("tasks", [])

    new_tasks = [t for t in tasks if t.get("name") != name]
    if len(new_tasks) == len(tasks):
        click.echo(f"Task '{name}' not found.")
        return

    # Write back
    user_config: dict = {}
    if config_path.exists():
        try:
            user_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass

    user_config.setdefault("daemon", {})["tasks"] = new_tasks
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.dump(user_config, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    click.echo(f"Removed task: {name}")
