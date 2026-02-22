"""Tests for anticlaw.cli.backup_cmd — aw backup CLI commands."""

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from anticlaw.cli.backup_cmd import backup_group


def _setup_backup_config(home: Path, target_dir: Path) -> None:
    """Create a config with local backup provider."""
    acl = home / ".acl"
    acl.mkdir(parents=True, exist_ok=True)

    config = {
        "daemon": {
            "backup": {
                "targets": [
                    {"type": "local", "path": str(target_dir)},
                ],
            },
        },
    }
    (acl / "config.yaml").write_text(
        yaml.dump(config, default_flow_style=False), encoding="utf-8",
    )


class TestBackupNow:
    def test_backup_no_providers(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        (home / ".acl").mkdir()

        runner = CliRunner()
        result = runner.invoke(backup_group, ["now", "--home", str(home)])

        assert result.exit_code == 0
        assert "no backup providers" in result.output.lower()

    def test_backup_local(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        target = tmp_path / "backups"
        target.mkdir()

        # Create a chat file
        proj = home / "test-project"
        proj.mkdir()
        (proj / "chat.md").write_text("# Test", encoding="utf-8")

        _setup_backup_config(home, target)

        runner = CliRunner()
        result = runner.invoke(backup_group, ["now", "--home", str(home)])

        assert result.exit_code == 0
        assert "OK" in result.output or "copied" in result.output

    def test_backup_specific_provider(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        target = tmp_path / "backups"
        target.mkdir()
        (home / "proj").mkdir()
        (home / "proj" / "c.md").write_text("data", encoding="utf-8")

        _setup_backup_config(home, target)

        runner = CliRunner()
        result = runner.invoke(backup_group, ["now", "--home", str(home), "--provider", "local"])

        assert result.exit_code == 0
        assert "local" in result.output.lower()


class TestBackupList:
    def test_list_no_providers(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        (home / ".acl").mkdir()

        runner = CliRunner()
        result = runner.invoke(backup_group, ["list", "--home", str(home)])

        assert result.exit_code == 0
        assert "no backup providers" in result.output.lower()

    def test_list_local_snapshots(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        target = tmp_path / "backups"
        target.mkdir()
        (home / "proj").mkdir()
        (home / "proj" / "c.md").write_text("data", encoding="utf-8")

        _setup_backup_config(home, target)

        # Do a backup first
        from anticlaw.providers.backup.local import LocalBackupProvider

        p = LocalBackupProvider({"path": str(target)})
        p.backup(home, None)

        runner = CliRunner()
        result = runner.invoke(backup_group, ["list", "--home", str(home)])

        assert result.exit_code == 0
        assert "local" in result.output.lower()


class TestBackupStatus:
    def test_status_no_backups(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        target = tmp_path / "backups"
        target.mkdir()
        _setup_backup_config(home, target)

        runner = CliRunner()
        result = runner.invoke(backup_group, ["status", "--home", str(home)])

        assert result.exit_code == 0
        assert "no backups" in result.output.lower()

    def test_status_with_manifest(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        target = tmp_path / "backups"
        target.mkdir()
        acl = home / ".acl"
        acl.mkdir(parents=True, exist_ok=True)

        _setup_backup_config(home, target)

        # Create a manifest
        manifest = {"provider": "local", "last_backup": "2025-02-20T03-00-00"}
        (acl / "backup_manifest_local.json").write_text(
            json.dumps(manifest), encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(backup_group, ["status", "--home", str(home)])

        assert result.exit_code == 0
        assert "2025-02-20" in result.output


class TestBackupVerify:
    def test_verify_local(self, tmp_path: Path):
        home = tmp_path / "home"
        home.mkdir()
        target = tmp_path / "backups"
        target.mkdir()

        _setup_backup_config(home, target)

        runner = CliRunner()
        result = runner.invoke(backup_group, ["verify", "--home", str(home)])

        assert result.exit_code == 0
        assert "OK" in result.output
