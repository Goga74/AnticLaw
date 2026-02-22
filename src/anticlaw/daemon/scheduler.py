"""APScheduler-based cron task scheduler for the daemon."""

from __future__ import annotations

import contextlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Built-in action handlers
_BUILTIN_ACTIONS = {
    "reindex", "backup", "retention", "health",
    "sync", "summarize-inbox", "autotag", "shell",
}

# Default task definitions
DEFAULT_TASKS: list[dict] = [
    {
        "name": "reindex",
        "schedule": "0 2 * * *",
        "enabled": True,
        "action": "reindex",
    },
    {
        "name": "backup",
        "schedule": "0 3 * * *",
        "enabled": False,
        "action": "backup",
        "params": {"providers": ["local"]},
    },
    {
        "name": "retention",
        "schedule": "0 4 * * *",
        "enabled": True,
        "action": "retention",
    },
    {
        "name": "health",
        "schedule": "0 5 * * 1",
        "enabled": True,
        "action": "health",
    },
    {
        "name": "sync",
        "schedule": "0 */6 * * *",
        "enabled": False,
        "action": "sync",
        "params": {"providers": ["claude"], "direction": "pull"},
    },
    {
        "name": "summarize-inbox",
        "schedule": "0 6 * * *",
        "enabled": False,
        "action": "summarize-inbox",
        "params": {"auto_tag": True, "auto_summarize": True},
    },
]


class TaskScheduler:
    """Cron-style task scheduler using APScheduler.

    Loads task definitions from config.yaml daemon.tasks section.
    Executes built-in actions (reindex, backup, health, etc.)
    and logs results to .acl/cron.log.
    """

    def __init__(self, home: Path, config: dict | None = None) -> None:
        self.home = home
        self._config = config or {}
        self._scheduler = None
        self._state_path = home / ".acl" / "scheduler_state.json"
        self._log_path = home / ".acl" / "cron.log"
        self._state: dict = self._load_state()

    def _load_state(self) -> dict:
        """Load last-run timestamps from scheduler_state.json."""
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                log.warning("Failed to load scheduler state, starting fresh")
        return {}

    def _save_state(self) -> None:
        """Persist last-run timestamps."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(self._state, indent=2), encoding="utf-8",
        )

    def _log_execution(self, task_name: str, success: bool, message: str) -> None:
        """Append a line to cron.log."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        status = "OK" if success else "FAIL"
        line = f"[{ts}] [{status}] {task_name}: {message}\n"

        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(line)

    def get_tasks(self) -> list[dict]:
        """Get task definitions from config, falling back to defaults."""
        daemon_cfg = self._config.get("daemon", {})
        tasks = daemon_cfg.get("tasks")
        if not tasks:
            return DEFAULT_TASKS
        return tasks

    def start(self) -> None:
        """Start the scheduler with all enabled tasks."""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError as e:
            raise RuntimeError(
                f"APScheduler not installed: {e}. Install with: pip install anticlaw[daemon]"
            ) from e

        self._scheduler = BackgroundScheduler()

        for task in self.get_tasks():
            if not task.get("enabled", True):
                continue

            name = task["name"]
            schedule = task.get("schedule", "")
            action = task.get("action", "")
            params = task.get("params", {})

            if not schedule or not action:
                log.warning("Skipping task with missing schedule/action: %s", name)
                continue

            try:
                trigger = CronTrigger.from_crontab(schedule)
                self._scheduler.add_job(
                    self._run_task,
                    trigger=trigger,
                    args=[name, action, params],
                    id=name,
                    name=name,
                    replace_existing=True,
                )
                log.info("Scheduled task: %s (%s) -> %s", name, schedule, action)
            except Exception:
                log.warning("Failed to schedule task: %s", name, exc_info=True)

        self._scheduler.start()
        log.info("TaskScheduler started with %d jobs", len(self._scheduler.get_jobs()))

        # Run missed jobs
        self._run_missed_jobs()

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        log.info("TaskScheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._scheduler is not None and self._scheduler.running

    def run_task_now(self, task_name: str) -> tuple[bool, str]:
        """Execute a task immediately by name. Returns (success, message)."""
        for task in self.get_tasks():
            if task["name"] == task_name:
                action = task.get("action", "")
                params = task.get("params", {})
                return self._run_task(task_name, action, params)
        return False, f"Task not found: {task_name}"

    def _run_task(self, name: str, action: str, params: dict) -> tuple[bool, str]:
        """Execute a single task action."""
        start = time.monotonic()
        log.info("Running task: %s (action=%s)", name, action)

        try:
            if action == "reindex":
                msg = self._action_reindex()
            elif action == "backup":
                msg = self._action_backup(params)
            elif action == "retention":
                msg = self._action_retention()
            elif action == "health":
                msg = self._action_health()
            elif action == "sync":
                msg = self._action_sync(params)
            elif action == "summarize-inbox":
                msg = self._action_summarize_inbox(params)
            elif action == "autotag":
                msg = self._action_autotag(params)
            elif action == "shell":
                msg = self._action_shell(params)
            else:
                msg = f"Unknown action: {action}"
                self._log_execution(name, False, msg)
                return False, msg

            duration = time.monotonic() - start
            result_msg = f"{msg} ({duration:.1f}s)"
            self._log_execution(name, True, result_msg)

            # Update state
            self._state[name] = datetime.now(timezone.utc).isoformat()
            self._save_state()

            return True, result_msg

        except Exception as e:
            duration = time.monotonic() - start
            error_msg = f"Error: {e} ({duration:.1f}s)"
            self._log_execution(name, False, error_msg)
            log.warning("Task %s failed: %s", name, e, exc_info=True)
            return False, error_msg

    def _run_missed_jobs(self) -> None:
        """Run jobs that were missed while daemon was stopped."""
        for task in self.get_tasks():
            if not task.get("enabled", True):
                continue

            name = task["name"]
            last_run = self._state.get(name)
            if last_run is None:
                continue

            # Parse cron schedule to check if we missed a run
            # Simple heuristic: if last run was > 2x the period ago, run now
            try:
                last_dt = datetime.fromisoformat(last_run)
                now = datetime.now(timezone.utc)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                hours_since = (now - last_dt).total_seconds() / 3600

                # For daily tasks (most common), run if > 36 hours since last
                if hours_since > 36:
                    action = task.get("action", "")
                    params = task.get("params", {})
                    log.info("Running missed task: %s (last run: %s)", name, last_run)
                    self._run_task(name, action, params)
            except (ValueError, TypeError):
                pass

    # --- Built-in actions ---

    def _action_reindex(self) -> str:
        """Rebuild meta.db from filesystem."""
        from anticlaw.core.meta_db import MetaDB

        db = MetaDB(self.home / ".acl" / "meta.db")
        try:
            chats, projects = db.reindex_all(self.home)
            return f"Reindexed {chats} chats, {projects} projects"
        finally:
            db.close()

    def _action_backup(self, params: dict) -> str:
        """Run backup providers."""
        provider_names = params.get("providers", ["local"])
        results = []

        for pname in provider_names:
            try:
                result_msg = self._run_backup_provider(pname)
                results.append(f"{pname}: {result_msg}")
            except Exception as e:
                results.append(f"{pname}: error — {e}")

        return "; ".join(results)

    def _run_backup_provider(self, provider_name: str) -> str:
        """Run a single backup provider."""
        from anticlaw.core.config import load_config

        config = load_config(self.home / ".acl" / "config.yaml")
        backup_cfg = config.get("daemon", {}).get("backup", {})
        targets = backup_cfg.get("targets", [])

        # Find matching target config
        target_config = {}
        for t in targets:
            if t.get("type") == provider_name:
                target_config = t
                break

        # Also check providers.backup section
        providers_cfg = config.get("providers", {}).get("backup", {})
        if provider_name in providers_cfg:
            target_config.update(providers_cfg[provider_name])

        if provider_name == "local":
            from anticlaw.providers.backup.local import LocalBackupProvider

            provider = LocalBackupProvider(target_config)
        elif provider_name == "gdrive":
            from anticlaw.providers.backup.gdrive import GDriveBackupProvider

            provider = GDriveBackupProvider(target_config)
        else:
            return f"Unknown backup provider: {provider_name}"

        # Load manifest
        manifest_path = self.home / ".acl" / f"backup_manifest_{provider_name}.json"
        manifest = None
        if manifest_path.exists():
            with contextlib.suppress(json.JSONDecodeError, OSError):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        result, new_manifest = provider.backup(self.home, manifest)

        # Save updated manifest
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(new_manifest, indent=2), encoding="utf-8")

        if result.success:
            return f"{result.files_copied} copied, {result.files_skipped} skipped"
        return f"failed — {', '.join(result.errors)}"

    def _action_retention(self) -> str:
        """Run retention lifecycle (placeholder for future Phase 9)."""
        log.info("Retention action: not yet implemented (Phase 9)")
        return "retention not yet implemented"

    def _action_health(self) -> str:
        """Run health check."""
        from anticlaw.core.meta_db import MetaDB

        issues = []
        db = MetaDB(self.home / ".acl" / "meta.db")
        try:
            # Check for orphaned index entries (file no longer exists)
            rows = db.conn.execute("SELECT id, file_path FROM chats").fetchall()
            orphans = 0
            for row in rows:
                if not Path(row["file_path"]).exists():
                    orphans += 1

            if orphans:
                issues.append(f"{orphans} orphaned index entries")

            # Check for unindexed files
            from anticlaw.core.storage import _RESERVED_DIRS

            indexed_paths = {row["file_path"] for row in rows}
            unindexed = 0
            for entry in self.home.iterdir():
                if not entry.is_dir() or entry.name in _RESERVED_DIRS or entry.name.startswith("."):
                    continue
                for md in entry.glob("*.md"):
                    if str(md) not in indexed_paths and not md.name.startswith("_"):
                        unindexed += 1

            if unindexed:
                issues.append(f"{unindexed} unindexed .md files")

        finally:
            db.close()

        if issues:
            return f"Issues found: {'; '.join(issues)}"
        return "All healthy"

    def _action_sync(self, params: dict) -> str:
        """Run sync (placeholder for future Phase 17)."""
        log.info("Sync action: not yet implemented (Phase 17)")
        return "sync not yet implemented"

    def _action_summarize_inbox(self, params: dict) -> str:
        """Auto-summarize and auto-tag inbox chats."""
        inbox_dir = self.home / "_inbox"
        if not inbox_dir.exists():
            return "No inbox directory"

        md_files = list(inbox_dir.glob("*.md"))
        if not md_files:
            return "Inbox empty"

        processed = 0
        auto_tag = params.get("auto_tag", True)
        auto_summarize = params.get("auto_summarize", True)

        try:
            from anticlaw.core.config import load_config
            from anticlaw.core.storage import ChatStorage
            from anticlaw.llm.ollama_client import OllamaClient

            config = load_config(self.home / ".acl" / "config.yaml")
            llm_config = config.get("llm", {})
            client = OllamaClient(llm_config)

            if not client.is_available():
                return "Ollama not available"

            storage = ChatStorage(self.home)

            for md_file in md_files:
                if md_file.name.startswith("_"):
                    continue
                try:
                    chat = storage.read_chat(md_file, load_messages=True)

                    if auto_summarize and not chat.summary:
                        from anticlaw.llm.summarizer import summarize_chat

                        summary = summarize_chat(chat, client=client)
                        if summary:
                            chat.summary = summary

                    if auto_tag and not chat.tags:
                        from anticlaw.llm.tagger import auto_tag as do_auto_tag

                        tags = do_auto_tag(chat, client=client)
                        if tags:
                            chat.tags = tags

                    storage.write_chat(md_file, chat)
                    processed += 1
                except Exception:
                    log.warning("Failed to process inbox chat: %s", md_file, exc_info=True)

        except ImportError:
            return "LLM dependencies not available"

        return f"Processed {processed}/{len(md_files)} inbox chats"

    def _action_autotag(self, params: dict) -> str:
        """Auto-tag chats without tags."""
        return "autotag not yet implemented as standalone action"

    def _action_shell(self, params: dict) -> str:
        """Execute a shell command."""
        import subprocess

        command = params.get("command", "")
        if not command:
            return "No command specified"

        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            return f"Exit 0: {result.stdout[:200]}" if result.stdout else "Exit 0"
        return f"Exit {result.returncode}: {result.stderr[:200]}"

    def get_log_lines(self, n: int = 50) -> list[str]:
        """Read last N lines from cron.log."""
        if not self._log_path.exists():
            return []
        lines = self._log_path.read_text(encoding="utf-8").splitlines()
        return lines[-n:]
