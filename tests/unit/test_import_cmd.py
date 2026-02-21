"""Tests for anticlaw.cli.import_cmd (aw import claude)."""

import json
import zipfile
from pathlib import Path

from click.testing import CliRunner

from anticlaw.cli.main import cli


SAMPLE_CONVERSATIONS = [
    {
        "uuid": "chat-001",
        "name": "First Chat",
        "created_at": "2025-02-18T14:30:00.000Z",
        "updated_at": "2025-02-18T15:00:00.000Z",
        "chat_messages": [
            {"sender": "human", "text": "Hello!", "created_at": "2025-02-18T14:30:00.000Z"},
            {"sender": "assistant", "text": "Hi there!", "created_at": "2025-02-18T14:31:00.000Z"},
        ],
    },
    {
        "uuid": "chat-002",
        "name": "Second Chat",
        "created_at": "2025-02-19T10:00:00.000Z",
        "chat_messages": [
            {"sender": "human", "text": "Question.", "created_at": "2025-02-19T10:00:00.000Z"},
            {"sender": "assistant", "text": "Answer.", "created_at": "2025-02-19T10:01:00.000Z"},
        ],
    },
]

MAPPING = {
    "chat-001": "Project Alpha",
}


def _make_zip(tmp_path: Path) -> Path:
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("conversations.json", json.dumps(SAMPLE_CONVERSATIONS))
    return zip_path


def _make_mapping(tmp_path: Path) -> Path:
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(MAPPING), encoding="utf-8")
    return path


class TestImportClaude:
    def test_import_to_inbox(self, tmp_path: Path):
        zip_path = _make_zip(tmp_path)
        home = tmp_path / "anticlaw_home"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "import", "claude", str(zip_path), "--home", str(home),
        ])

        assert result.exit_code == 0, result.output
        assert "Imported: 2" in result.output
        assert "_inbox" in result.output

        # Check files were created in _inbox
        inbox = home / "_inbox"
        md_files = list(inbox.glob("*.md"))
        assert len(md_files) == 2

    def test_import_with_mapping(self, tmp_path: Path):
        zip_path = _make_zip(tmp_path)
        mapping_path = _make_mapping(tmp_path)
        home = tmp_path / "anticlaw_home"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "import", "claude", str(zip_path),
            "--mapping", str(mapping_path),
            "--home", str(home),
        ])

        assert result.exit_code == 0, result.output
        assert "Imported: 2" in result.output

        # chat-001 should be in project-alpha, chat-002 in _inbox
        project_dir = home / "project-alpha"
        assert project_dir.exists()
        project_files = list(project_dir.glob("*.md"))
        assert len(project_files) == 1

        inbox_files = list((home / "_inbox").glob("*.md"))
        assert len(inbox_files) == 1

    def test_import_with_scrub(self, tmp_path: Path):
        conversations = [
            {
                "uuid": "secret-chat",
                "name": "Secrets",
                "created_at": "2025-02-18T14:30:00.000Z",
                "chat_messages": [
                    {
                        "sender": "human",
                        "text": "My key is sk-ant-XXXXXXXXXXXXXXXXXXXXXXXX_longkey",
                        "created_at": "2025-02-18T14:30:00.000Z",
                    },
                ],
            },
        ]
        zip_path = tmp_path / "secrets.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("conversations.json", json.dumps(conversations))

        home = tmp_path / "anticlaw_home"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "import", "claude", str(zip_path), "--scrub", "--home", str(home),
        ])

        assert result.exit_code == 0, result.output
        assert "scrubbing: enabled" in result.output

        # Read the imported file and verify scrubbing
        md_files = list((home / "_inbox").glob("*.md"))
        assert len(md_files) == 1
        content = md_files[0].read_text(encoding="utf-8")
        assert "sk-ant-" not in content
        assert "[REDACTED" in content

    def test_import_skips_duplicates(self, tmp_path: Path):
        zip_path = _make_zip(tmp_path)
        home = tmp_path / "anticlaw_home"

        runner = CliRunner()
        # First import
        result1 = runner.invoke(cli, [
            "import", "claude", str(zip_path), "--home", str(home),
        ])
        assert result1.exit_code == 0
        assert "Imported: 2" in result1.output

        # Second import — should skip
        result2 = runner.invoke(cli, [
            "import", "claude", str(zip_path), "--home", str(home),
        ])
        assert result2.exit_code == 0
        assert "Imported: 0" in result2.output
        assert "Skipped" in result2.output

    def test_import_empty_zip(self, tmp_path: Path):
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("conversations.json", "[]")

        home = tmp_path / "anticlaw_home"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "import", "claude", str(zip_path), "--home", str(home),
        ])
        assert result.exit_code == 0
        assert "No conversations found" in result.output

    def test_import_creates_home_structure(self, tmp_path: Path):
        zip_path = _make_zip(tmp_path)
        home = tmp_path / "fresh_home"

        runner = CliRunner()
        result = runner.invoke(cli, [
            "import", "claude", str(zip_path), "--home", str(home),
        ])
        assert result.exit_code == 0
        assert (home / ".acl").is_dir()
        assert (home / "_inbox").is_dir()
        assert (home / "_archive").is_dir()

    def test_help_text(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["import", "claude", "--help"])
        assert result.exit_code == 0
        assert "Claude.ai" in result.output
