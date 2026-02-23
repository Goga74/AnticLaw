"""Tests for anticlaw.input.whisper_input — WhisperInputProvider."""

from unittest.mock import MagicMock, patch

from anticlaw.input.base import InputProvider


class TestWhisperInputProviderImport:
    """Test graceful import behavior."""

    def test_import_module(self):
        from anticlaw.input.whisper_input import WhisperInputProvider

        assert WhisperInputProvider is not None

    def test_default_config(self):
        from anticlaw.input.whisper_input import WhisperInputProvider

        p = WhisperInputProvider()
        assert p.name == "whisper"
        assert p._model_size == "base"
        assert p._language is None  # auto-detect
        assert p._push_to_talk is False
        assert p._sample_rate == 16000

    def test_custom_config(self):
        from anticlaw.input.whisper_input import WhisperInputProvider

        p = WhisperInputProvider({
            "model": "small",
            "language": "ru",
            "push_to_talk": True,
            "sample_rate": 22050,
            "silence_threshold": 0.02,
            "silence_duration": 2.0,
            "max_duration": 60.0,
        })
        assert p._model_size == "small"
        assert p._language == "ru"
        assert p._push_to_talk is True
        assert p._sample_rate == 22050
        assert p._silence_threshold == 0.02
        assert p._silence_duration == 2.0
        assert p._max_duration == 60.0

    def test_auto_language_becomes_none(self):
        from anticlaw.input.whisper_input import WhisperInputProvider

        p = WhisperInputProvider({"language": "auto"})
        assert p._language is None

    def test_invalid_model_falls_back(self):
        from anticlaw.input.whisper_input import WhisperInputProvider

        p = WhisperInputProvider({"model": "xxl"})
        assert p._model_size == "base"

    def test_model_path_config(self):
        from anticlaw.input.whisper_input import WhisperInputProvider

        p = WhisperInputProvider({"model_path": "/custom/model"})
        assert p._model_path == "/custom/model"


class TestWhisperInputProviderInfo:
    def test_name(self):
        from anticlaw.input.whisper_input import WhisperInputProvider

        p = WhisperInputProvider()
        assert p.name == "whisper"

    def test_info(self):
        from anticlaw.input.whisper_input import WhisperInputProvider

        info = WhisperInputProvider().info
        assert info.display_name == "Whisper (faster-whisper)"
        assert info.version == "1.0.0"
        assert "ru" in info.supported_languages
        assert "en" in info.supported_languages
        assert "auto" in info.supported_languages
        assert info.is_local is True
        assert info.requires_hardware is True


class TestWhisperAvailability:
    @patch("anticlaw.input.whisper_input._import_numpy")
    @patch("anticlaw.input.whisper_input._import_sounddevice")
    @patch("anticlaw.input.whisper_input._import_faster_whisper")
    def test_available_when_all_deps_present(self, mock_fw, mock_sd, mock_np):
        from anticlaw.input.whisper_input import WhisperInputProvider

        p = WhisperInputProvider()
        assert p.is_available() is True

    @patch(
        "anticlaw.input.whisper_input._import_faster_whisper",
        side_effect=ImportError("no faster_whisper"),
    )
    def test_not_available_without_faster_whisper(self, mock_fw):
        from anticlaw.input.whisper_input import WhisperInputProvider

        p = WhisperInputProvider()
        assert p.is_available() is False

    @patch("anticlaw.input.whisper_input._import_faster_whisper")
    @patch(
        "anticlaw.input.whisper_input._import_sounddevice",
        side_effect=ImportError("no sounddevice"),
    )
    def test_not_available_without_sounddevice(self, mock_sd, mock_fw):
        from anticlaw.input.whisper_input import WhisperInputProvider

        p = WhisperInputProvider()
        assert p.is_available() is False

    @patch("anticlaw.input.whisper_input._import_faster_whisper")
    @patch("anticlaw.input.whisper_input._import_sounddevice")
    @patch(
        "anticlaw.input.whisper_input._import_numpy",
        side_effect=ImportError("no numpy"),
    )
    def test_not_available_without_numpy(self, mock_np, mock_sd, mock_fw):
        from anticlaw.input.whisper_input import WhisperInputProvider

        p = WhisperInputProvider()
        assert p.is_available() is False


class TestWhisperTranscribe:
    @patch("anticlaw.input.whisper_input._import_numpy")
    @patch("anticlaw.input.whisper_input._import_faster_whisper")
    def test_transcribe_returns_text(self, mock_fw_import, mock_np_import):
        import numpy as np

        mock_np_import.return_value = np

        from anticlaw.input.whisper_input import WhisperInputProvider

        # Mock model
        mock_segment = MagicMock()
        mock_segment.text = " Hello world "
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.98

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)

        mock_fw_mod = MagicMock()
        mock_fw_mod.WhisperModel.return_value = mock_model
        mock_fw_import.return_value = mock_fw_mod

        p = WhisperInputProvider()
        p._model = mock_model  # Skip lazy loading

        audio = np.zeros(16000, dtype=np.float32)  # 1 second of silence
        text = p.transcribe(audio.tobytes())

        assert text == "Hello world"
        mock_model.transcribe.assert_called_once()

    @patch("anticlaw.input.whisper_input._import_numpy")
    @patch("anticlaw.input.whisper_input._import_faster_whisper")
    def test_transcribe_empty_audio(self, mock_fw_import, mock_np_import):
        import numpy as np

        mock_np_import.return_value = np

        from anticlaw.input.whisper_input import WhisperInputProvider

        p = WhisperInputProvider()
        text = p.transcribe(b"")
        assert text == ""

    @patch("anticlaw.input.whisper_input._import_numpy")
    @patch("anticlaw.input.whisper_input._import_faster_whisper")
    def test_transcribe_multiple_segments(self, mock_fw_import, mock_np_import):
        import numpy as np

        mock_np_import.return_value = np

        from anticlaw.input.whisper_input import WhisperInputProvider

        seg1 = MagicMock()
        seg1.text = " Hello "
        seg2 = MagicMock()
        seg2.text = " world "

        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.95

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([seg1, seg2], mock_info)

        p = WhisperInputProvider()
        p._model = mock_model

        audio = np.zeros(16000, dtype=np.float32)
        text = p.transcribe(audio.tobytes())
        assert text == "Hello world"

    @patch("anticlaw.input.whisper_input._import_numpy")
    @patch("anticlaw.input.whisper_input._import_faster_whisper")
    def test_transcribe_with_language_set(self, mock_fw_import, mock_np_import):
        import numpy as np

        mock_np_import.return_value = np

        from anticlaw.input.whisper_input import WhisperInputProvider

        mock_segment = MagicMock()
        mock_segment.text = "Привет мир"
        mock_info = MagicMock()
        mock_info.language = "ru"
        mock_info.language_probability = 0.99

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)

        p = WhisperInputProvider({"language": "ru"})
        p._model = mock_model

        audio = np.zeros(16000, dtype=np.float32)
        text = p.transcribe(audio.tobytes())

        assert text == "Привет мир"
        call_kwargs = mock_model.transcribe.call_args[1]
        assert call_kwargs["language"] == "ru"


class TestWhisperLoadModel:
    @patch("anticlaw.input.whisper_input._import_faster_whisper")
    def test_load_model_default(self, mock_fw_import):
        from anticlaw.input.whisper_input import WhisperInputProvider

        mock_fw_mod = MagicMock()
        mock_fw_import.return_value = mock_fw_mod

        p = WhisperInputProvider()
        model = p._load_model()

        mock_fw_mod.WhisperModel.assert_called_once_with("base", device="cpu", compute_type="int8")
        assert model == mock_fw_mod.WhisperModel.return_value

    @patch("anticlaw.input.whisper_input._import_faster_whisper")
    def test_load_model_custom_path(self, mock_fw_import):
        from anticlaw.input.whisper_input import WhisperInputProvider

        mock_fw_mod = MagicMock()
        mock_fw_import.return_value = mock_fw_mod

        p = WhisperInputProvider({"model_path": "/my/model"})
        p._load_model()

        mock_fw_mod.WhisperModel.assert_called_once_with(
            "/my/model", device="cpu", compute_type="int8"
        )

    @patch("anticlaw.input.whisper_input._import_faster_whisper")
    def test_load_model_cached(self, mock_fw_import):
        from anticlaw.input.whisper_input import WhisperInputProvider

        mock_fw_mod = MagicMock()
        mock_fw_import.return_value = mock_fw_mod

        p = WhisperInputProvider()
        p._load_model()
        p._load_model()

        # Should only create model once
        assert mock_fw_mod.WhisperModel.call_count == 1


class TestWhisperRecordAudio:
    @patch("anticlaw.input.whisper_input._import_numpy")
    @patch("anticlaw.input.whisper_input._import_sounddevice")
    def test_record_auto_stop_on_silence(self, mock_sd_import, mock_np_import):
        import numpy as np

        mock_np_import.return_value = np

        from anticlaw.input.whisper_input import WhisperInputProvider

        mock_sd = MagicMock()
        mock_sd_import.return_value = mock_sd

        # Return silence after some audio
        call_count = 0

        def fake_rec(frames, samplerate, channels, dtype):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                # Audible chunk
                return np.ones((frames, 1), dtype=np.float32) * 0.5
            else:
                # Silent chunk
                return np.zeros((frames, 1), dtype=np.float32)

        mock_sd.rec = fake_rec

        p = WhisperInputProvider({
            "silence_duration": 0.2,  # 2 chunks of 100ms
            "max_duration": 5.0,
        })

        audio_bytes = p.record_audio()
        assert len(audio_bytes) > 0

    @patch("anticlaw.input.whisper_input._import_numpy")
    @patch("anticlaw.input.whisper_input._import_sounddevice")
    def test_record_respects_max_duration(self, mock_sd_import, mock_np_import):
        import numpy as np

        mock_np_import.return_value = np

        from anticlaw.input.whisper_input import WhisperInputProvider

        mock_sd = MagicMock()
        mock_sd_import.return_value = mock_sd

        # Always return loud audio (no silence stop)
        mock_sd.rec = lambda frames, samplerate, channels, dtype: (
            np.ones((frames, 1), dtype=np.float32) * 0.5
        )

        p = WhisperInputProvider({"max_duration": 0.5})  # 5 chunks max

        audio_bytes = p.record_audio()
        assert len(audio_bytes) > 0


class TestWhisperListen:
    @patch("anticlaw.input.whisper_input._import_numpy")
    @patch("anticlaw.input.whisper_input._import_sounddevice")
    @patch("anticlaw.input.whisper_input._import_faster_whisper")
    def test_listen_integrates_record_and_transcribe(
        self, mock_fw_import, mock_sd_import, mock_np_import
    ):
        import numpy as np

        mock_np_import.return_value = np

        from anticlaw.input.whisper_input import WhisperInputProvider

        # Mock sounddevice
        mock_sd = MagicMock()
        mock_sd_import.return_value = mock_sd
        call_count = 0

        def fake_rec(frames, samplerate, channels, dtype):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return np.ones((frames, 1), dtype=np.float32) * 0.5
            return np.zeros((frames, 1), dtype=np.float32)

        mock_sd.rec = fake_rec

        # Mock whisper model
        mock_segment = MagicMock()
        mock_segment.text = "test query"
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.95
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)

        p = WhisperInputProvider({"silence_duration": 0.1})
        p._model = mock_model

        result = p.listen()
        assert result == "test query"

    def test_listen_empty_audio(self):
        from anticlaw.input.whisper_input import WhisperInputProvider

        p = WhisperInputProvider()
        p.record_audio = MagicMock(return_value=b"")

        result = p.listen()
        assert result == ""


class TestWhisperRespond:
    def test_respond_writes_to_stdout(self, capsys):
        from anticlaw.input.whisper_input import WhisperInputProvider

        p = WhisperInputProvider()
        p.respond("Hello from Whisper!")

        captured = capsys.readouterr()
        assert "Hello from Whisper!" in captured.out


class TestWhisperProtocol:
    def test_satisfies_input_provider(self):
        from anticlaw.input.whisper_input import WhisperInputProvider

        p = WhisperInputProvider()
        assert isinstance(p, InputProvider)


class TestWhisperModelsConstant:
    def test_supported_models(self):
        from anticlaw.input.whisper_input import WHISPER_MODELS

        assert "tiny" in WHISPER_MODELS
        assert "base" in WHISPER_MODELS
        assert "small" in WHISPER_MODELS
        assert "medium" in WHISPER_MODELS
