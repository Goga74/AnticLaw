"""Tests for anticlaw.core.fileutil."""

from pathlib import Path

from anticlaw.core.fileutil import atomic_write, ensure_dir, file_lock, safe_filename


class TestSafeFilename:
    def test_simple(self):
        assert safe_filename("Auth Discussion") == "auth-discussion"

    def test_special_chars(self):
        assert safe_filename("hello@world!#$%") == "helloworld"

    def test_path_traversal(self):
        result = safe_filename("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result
        assert "\\" not in result

    def test_slashes(self):
        assert safe_filename("foo/bar\\baz") == "foo-bar-baz"

    def test_empty(self):
        assert safe_filename("") == "untitled"

    def test_only_special_chars(self):
        assert safe_filename("@#$%^&*") == "untitled"

    def test_unicode(self):
        result = safe_filename("авторизация JWT")
        assert result  # Should produce something non-empty
        assert "/" not in result

    def test_long_name(self):
        long_name = "a" * 300
        result = safe_filename(long_name)
        assert len(result) <= 200

    def test_dots_stripped(self):
        assert safe_filename("...test...") == "test"

    def test_collapse_hyphens(self):
        assert safe_filename("foo - - bar") == "foo-bar"


class TestAtomicWrite:
    def test_creates_file(self, tmp_path: Path):
        target = tmp_path / "test.txt"
        atomic_write(target, "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_creates_parent_dirs(self, tmp_path: Path):
        target = tmp_path / "sub" / "deep" / "test.txt"
        atomic_write(target, "content")
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "content"

    def test_overwrites_existing(self, tmp_path: Path):
        target = tmp_path / "test.txt"
        atomic_write(target, "first")
        atomic_write(target, "second")
        assert target.read_text(encoding="utf-8") == "second"

    def test_unicode_content(self, tmp_path: Path):
        target = tmp_path / "test.txt"
        atomic_write(target, "Привет мир 你好世界")
        assert target.read_text(encoding="utf-8") == "Привет мир 你好世界"


class TestEnsureDir:
    def test_creates_dir(self, tmp_path: Path):
        target = tmp_path / "new_dir"
        ensure_dir(target)
        assert target.is_dir()

    def test_nested(self, tmp_path: Path):
        target = tmp_path / "a" / "b" / "c"
        ensure_dir(target)
        assert target.is_dir()

    def test_idempotent(self, tmp_path: Path):
        target = tmp_path / "dir"
        ensure_dir(target)
        ensure_dir(target)  # Should not raise
        assert target.is_dir()


class TestFileLock:
    def test_lock_unlock(self, tmp_path: Path):
        target = tmp_path / "data.txt"
        target.write_text("test")
        with file_lock(target):
            # Should be able to write while locked
            target.write_text("updated")
        assert target.read_text() == "updated"
