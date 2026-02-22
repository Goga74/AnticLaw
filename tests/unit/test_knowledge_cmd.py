"""Tests for anticlaw.cli.knowledge_cmd (aw inbox, stale, duplicates, health, retention, stats)."""

import gzip
from datetime import datetime, timedelta, timezone
from pathlib import Path

from click.testing import CliRunner

from anticlaw.cli.main import cli
from anticlaw.core.meta_db import MetaDB
from anticlaw.core.models import Chat, ChatMessage
from anticlaw.core.storage import ChatStorage


def _setup_home(tmp_path: Path) -> Path:
    """Create a home with projects and chats for CLI testing."""
    home = tmp_path / "home"
    storage = ChatStorage(home)
    storage.init_home()

    # Project alpha
    project_dir = storage.create_project("alpha", "Test project")
    alpha_proj = storage.read_project(project_dir / "_project.yaml")
    alpha_proj.tags = ["auth", "security"]
    storage.write_project(project_dir / "_project.yaml", alpha_proj)

    recent = Chat(
        id="recent-001",
        title="Recent Chat",
        provider="claude",
        tags=["auth"],
        created=datetime.now(timezone.utc) - timedelta(days=2),
        updated=datetime.now(timezone.utc) - timedelta(days=2),
        messages=[ChatMessage(role="human", content="Hello world")],
        message_count=1,
    )
    storage.write_chat(project_dir / "2025-02-20_recent.md", recent)

    old = Chat(
        id="old-001",
        title="Old Chat",
        provider="claude",
        tags=["design"],
        created=datetime.now(timezone.utc) - timedelta(days=60),
        updated=datetime.now(timezone.utc) - timedelta(days=60),
        messages=[ChatMessage(role="human", content="Old content")],
        message_count=1,
    )
    storage.write_chat(project_dir / "2025-01-01_old.md", old)

    # Project beta — stale
    beta_dir = storage.create_project("beta", "Stale project")
    stale = Chat(
        id="stale-001",
        title="Stale Discussion",
        provider="claude",
        tags=["old"],
        created=datetime.now(timezone.utc) - timedelta(days=90),
        updated=datetime.now(timezone.utc) - timedelta(days=90),
        messages=[ChatMessage(role="human", content="Stale stuff")],
        message_count=1,
    )
    storage.write_chat(beta_dir / "2024-12-01_stale.md", stale)

    # Inbox chats
    inbox = Chat(
        id="inbox-001",
        title="Inbox Chat",
        provider="claude",
        tags=["auth", "security"],
        messages=[ChatMessage(role="human", content="Needs classification")],
        message_count=1,
    )
    storage.write_chat(home / "_inbox" / "2025-02-19_inbox.md", inbox)

    # Build index
    db = MetaDB(home / ".acl" / "meta.db")
    db.reindex_all(home)
    db.close()

    return home


# --- aw inbox ---


class TestInboxCmd:
    def test_inbox_shows_chats(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["inbox", "--home", str(home)])
        assert result.exit_code == 0, result.output
        assert "inbox-001" in result.output or "Inbox Chat" in result.output

    def test_inbox_empty(self, tmp_path: Path):
        home = tmp_path / "empty_inbox"
        storage = ChatStorage(home)
        storage.init_home()
        db = MetaDB(home / ".acl" / "meta.db")
        db.reindex_all(home)
        db.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["inbox", "--home", str(home)])
        assert result.exit_code == 0
        assert "empty" in result.output.lower()

    def test_inbox_no_index(self, tmp_path: Path):
        home = tmp_path / "noindex"
        home.mkdir()
        runner = CliRunner()
        result = runner.invoke(cli, ["inbox", "--home", str(home)])
        assert result.exit_code == 0
        assert "reindex" in result.output.lower()

    def test_inbox_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["inbox", "--help"])
        assert result.exit_code == 0
        assert "inbox" in result.output.lower()


# --- aw stale ---


class TestStaleCmd:
    def test_stale_default(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["stale", "--home", str(home)])
        assert result.exit_code == 0, result.output
        assert "beta" in result.output.lower() or "Stale" in result.output

    def test_stale_custom_days(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["stale", "--days", "1", "--home", str(home)])
        assert result.exit_code == 0

    def test_stale_high_threshold(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["stale", "--days", "9999", "--home", str(home)])
        assert result.exit_code == 0
        assert "no stale" in result.output.lower()

    def test_stale_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["stale", "--help"])
        assert result.exit_code == 0


# --- aw duplicates ---


class TestDuplicatesCmd:
    def test_duplicates_found(self, tmp_path: Path):
        home = tmp_path / "dupes"
        storage = ChatStorage(home)
        storage.init_home()
        project_dir = storage.create_project("test", "Test")

        for i in range(2):
            chat = Chat(
                id=f"dupe-{i:03d}",
                title="Same Title Here",
                provider="claude",
                messages=[ChatMessage(role="human", content=f"Content {i}")],
            )
            storage.write_chat(project_dir / f"2025-02-{18+i}_same-{i}.md", chat)

        db = MetaDB(home / ".acl" / "meta.db")
        db.reindex_all(home)
        db.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["duplicates", "--home", str(home)])
        assert result.exit_code == 0, result.output
        assert "Same Title" in result.output or "dupe-0" in result.output

    def test_no_duplicates(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["duplicates", "--home", str(home)])
        assert result.exit_code == 0
        assert "no duplicates" in result.output.lower() or "Potential" in result.output

    def test_duplicates_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["duplicates", "--help"])
        assert result.exit_code == 0


# --- aw health ---


class TestHealthCmd:
    def test_health_clean(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["health", "--home", str(home)])
        assert result.exit_code == 0, result.output
        assert "Health Report" in result.output

    def test_health_no_db(self, tmp_path: Path):
        home = tmp_path / "nodb"
        home.mkdir()
        runner = CliRunner()
        result = runner.invoke(cli, ["health", "--home", str(home)])
        assert result.exit_code == 0
        assert "meta.db" in result.output.lower() or "Issues" in result.output

    def test_health_with_orphan(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        # Create orphan file
        (home / "alpha" / "2025-02-20_orphan.md").write_text(
            "---\nid: orphan\ntitle: Orphan\n---\n## Human\nHi\n"
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["health", "--home", str(home)])
        assert result.exit_code == 0
        assert "orphan" in result.output.lower()

    def test_health_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["health", "--help"])
        assert result.exit_code == 0


# --- aw retention preview / run ---


class TestRetentionCmd:
    def test_retention_preview(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["retention", "preview", "--archive-days", "30", "--home", str(home)]
        )
        assert result.exit_code == 0, result.output
        # old-001 should be eligible
        assert "old-001" in result.output or "Old Chat" in result.output or "archive" in result.output.lower()

    def test_retention_preview_nothing(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["retention", "preview", "--archive-days", "9999", "--home", str(home)]
        )
        assert result.exit_code == 0
        assert "no chats" in result.output.lower()

    def test_retention_run(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["retention", "run", "--archive-days", "30", "--home", str(home)]
        )
        assert result.exit_code == 0, result.output
        assert "Archived" in result.output or "archived" in result.output.lower()

    def test_retention_run_nothing(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["retention", "run", "--archive-days", "9999", "--home", str(home)]
        )
        assert result.exit_code == 0
        assert "no chats" in result.output.lower()

    def test_retention_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["retention", "--help"])
        assert result.exit_code == 0
        assert "preview" in result.output
        assert "run" in result.output

    def test_retention_preview_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["retention", "preview", "--help"])
        assert result.exit_code == 0


# --- aw restore ---


class TestRestoreCmd:
    def test_restore_archived(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        # First archive
        runner.invoke(
            cli, ["retention", "run", "--archive-days", "30", "--home", str(home)]
        )
        # Then restore
        result = runner.invoke(cli, ["restore", "old-001", "--home", str(home)])
        assert result.exit_code == 0, result.output
        assert "Restored" in result.output or "restored" in result.output.lower()

    def test_restore_not_found(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["restore", "nonexistent", "--home", str(home)])
        assert result.exit_code == 0
        assert "could not" in result.output.lower()

    def test_restore_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["restore", "--help"])
        assert result.exit_code == 0


# --- aw stats ---


class TestStatsCmd:
    def test_stats_output(self, tmp_path: Path):
        home = _setup_home(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["stats", "--home", str(home)])
        assert result.exit_code == 0, result.output
        assert "Projects:" in result.output or "projects" in result.output.lower()
        assert "Chats:" in result.output or "chats" in result.output.lower()

    def test_stats_empty(self, tmp_path: Path):
        home = tmp_path / "empty_stats"
        storage = ChatStorage(home)
        storage.init_home()
        db = MetaDB(home / ".acl" / "meta.db")
        db.reindex_all(home)
        db.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["stats", "--home", str(home)])
        assert result.exit_code == 0
        assert "0" in result.output

    def test_stats_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["stats", "--help"])
        assert result.exit_code == 0
