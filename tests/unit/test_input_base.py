"""Tests for anticlaw.input.base — InputProvider Protocol and InputInfo."""

from anticlaw.input.base import InputInfo, InputProvider


class _MockInput:
    """Minimal implementation satisfying the InputProvider Protocol."""

    @property
    def name(self) -> str:
        return "mock"

    @property
    def info(self) -> InputInfo:
        return InputInfo(
            display_name="Mock Input",
            version="0.1.0",
            supported_languages=["en"],
            is_local=True,
            requires_hardware=False,
        )

    def listen(self) -> str:
        return "hello world"

    def respond(self, text: str) -> None:
        pass

    def is_available(self) -> bool:
        return True


class TestInputInfo:
    def test_defaults(self):
        info = InputInfo(display_name="Test", version="1.0")
        assert info.display_name == "Test"
        assert info.version == "1.0"
        assert info.supported_languages == []
        assert info.is_local is True
        assert info.requires_hardware is False

    def test_all_fields(self):
        info = InputInfo(
            display_name="Whisper",
            version="1.0.0",
            supported_languages=["ru", "en"],
            is_local=True,
            requires_hardware=True,
        )
        assert info.supported_languages == ["ru", "en"]
        assert info.requires_hardware is True


class TestInputProviderProtocol:
    def test_mock_implements_protocol(self):
        mock = _MockInput()
        assert isinstance(mock, InputProvider)

    def test_listen_returns_string(self):
        mock = _MockInput()
        assert mock.listen() == "hello world"

    def test_respond_accepts_text(self):
        mock = _MockInput()
        mock.respond("some text")  # Should not raise

    def test_is_available(self):
        mock = _MockInput()
        assert mock.is_available() is True

    def test_name_property(self):
        mock = _MockInput()
        assert mock.name == "mock"

    def test_info_property(self):
        mock = _MockInput()
        info = mock.info
        assert info.display_name == "Mock Input"
        assert info.version == "0.1.0"

    def test_non_implementing_class_fails_protocol(self):
        class _BadInput:
            pass

        assert not isinstance(_BadInput(), InputProvider)
