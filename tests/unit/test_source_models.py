"""Tests for SourceDocument model and SourceProvider Protocol."""

from anticlaw.core.models import SourceDocument
from anticlaw.providers.source.base import SourceInfo, SourceProvider
from anticlaw.providers.source.local_files import LocalFilesProvider


class TestSourceDocument:
    def test_defaults(self):
        doc = SourceDocument()
        assert doc.id  # UUID generated
        assert doc.file_path == ""
        assert doc.filename == ""
        assert doc.extension == ""
        assert doc.language == ""
        assert doc.content == ""
        assert doc.size == 0
        assert doc.hash == ""
        assert doc.project_id == ""
        assert doc.indexed_at is not None

    def test_custom_fields(self):
        doc = SourceDocument(
            id="src-001",
            file_path="/home/user/code/main.py",
            filename="main.py",
            extension=".py",
            language="python",
            content="print('hello')",
            size=14,
            hash="abc123",
            project_id="my-project",
        )
        assert doc.id == "src-001"
        assert doc.file_path == "/home/user/code/main.py"
        assert doc.filename == "main.py"
        assert doc.extension == ".py"
        assert doc.language == "python"
        assert doc.size == 14

    def test_independent_instances(self):
        d1 = SourceDocument(filename="a.py")
        d2 = SourceDocument(filename="b.py")
        assert d1.filename != d2.filename
        assert d1.id != d2.id


class TestSourceInfo:
    def test_defaults(self):
        info = SourceInfo(display_name="Test", version="1.0")
        assert info.display_name == "Test"
        assert info.supported_extensions == []
        assert info.is_local is True

    def test_custom(self):
        info = SourceInfo(
            display_name="PDF Reader",
            version="2.0",
            supported_extensions=[".pdf"],
            is_local=False,
        )
        assert info.supported_extensions == [".pdf"]
        assert info.is_local is False


class TestSourceProviderProtocol:
    def test_local_files_satisfies_protocol(self):
        """LocalFilesProvider should satisfy the SourceProvider Protocol."""
        provider = LocalFilesProvider()
        assert isinstance(provider, SourceProvider)
