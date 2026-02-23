"""WhisperInputProvider — offline speech-to-text via faster-whisper."""

from __future__ import annotations

import contextlib
import logging
import sys
import threading

from anticlaw.input.base import InputInfo

log = logging.getLogger(__name__)

# Lazy imports for optional deps
_faster_whisper = None
_sounddevice = None
_numpy = None


def _import_faster_whisper():
    global _faster_whisper
    if _faster_whisper is None:
        try:
            import faster_whisper

            _faster_whisper = faster_whisper
        except ImportError as err:
            raise ImportError(
                "faster-whisper is required for voice input. "
                "Install with: pip install anticlaw[voice]"
            ) from err
    return _faster_whisper


def _import_sounddevice():
    global _sounddevice
    if _sounddevice is None:
        try:
            import sounddevice

            _sounddevice = sounddevice
        except ImportError as err:
            raise ImportError(
                "sounddevice is required for voice input. "
                "Install with: pip install anticlaw[voice]"
            ) from err
    return _sounddevice


def _import_numpy():
    global _numpy
    if _numpy is None:
        try:
            import numpy

            _numpy = numpy
        except ImportError as err:
            raise ImportError(
                "numpy is required for voice input. "
                "Install with: pip install anticlaw[voice]"
            ) from err
    return _numpy


# Supported Whisper model sizes
WHISPER_MODELS = ("tiny", "base", "small", "medium")

# Default recording parameters
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1
DEFAULT_SILENCE_THRESHOLD = 0.01
DEFAULT_SILENCE_DURATION = 1.5  # seconds of silence before auto-stop
DEFAULT_MAX_DURATION = 30.0  # max recording seconds


class WhisperInputProvider:
    """Offline speech-to-text using faster-whisper (CTranslate2 backend).

    Supports models: tiny (~75 MB), base (~150 MB), small (~500 MB), medium (~1.5 GB).
    Whisper auto-detects language (Russian, English, and 97 others).
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self._model_size: str = cfg.get("model", "base")
        self._language: str | None = cfg.get("language")  # None = auto-detect
        self._push_to_talk: bool = cfg.get("push_to_talk", False)
        self._sample_rate: int = cfg.get("sample_rate", DEFAULT_SAMPLE_RATE)
        self._silence_threshold: float = cfg.get("silence_threshold", DEFAULT_SILENCE_THRESHOLD)
        self._silence_duration: float = cfg.get("silence_duration", DEFAULT_SILENCE_DURATION)
        self._max_duration: float = cfg.get("max_duration", DEFAULT_MAX_DURATION)
        self._model_path: str | None = cfg.get("model_path")
        self._model = None

        if self._language == "auto":
            self._language = None

        if self._model_size not in WHISPER_MODELS:
            log.warning(
                "Unknown whisper model %r, falling back to 'base'",
                self._model_size,
            )
            self._model_size = "base"

    @property
    def name(self) -> str:
        return "whisper"

    @property
    def info(self) -> InputInfo:
        return InputInfo(
            display_name="Whisper (faster-whisper)",
            version="1.0.0",
            supported_languages=["auto", "ru", "en", "de", "fr", "es", "zh", "ja", "ko"],
            is_local=True,
            requires_hardware=True,
        )

    def is_available(self) -> bool:
        """Check if faster-whisper, sounddevice, and numpy are importable."""
        try:
            _import_faster_whisper()
            _import_sounddevice()
            _import_numpy()
            return True
        except ImportError:
            return False

    def _load_model(self):
        """Lazy-load the Whisper model."""
        if self._model is not None:
            return self._model

        fw = _import_faster_whisper()
        model_id = self._model_path or self._model_size
        log.info("Loading Whisper model: %s", model_id)
        self._model = fw.WhisperModel(model_id, device="cpu", compute_type="int8")
        return self._model

    def record_audio(self) -> bytes:
        """Record audio from microphone until silence detected or max duration.

        Returns raw PCM float32 audio data as bytes.
        """
        sd = _import_sounddevice()
        np = _import_numpy()

        chunks: list = []
        silence_frames = 0
        frames_per_chunk = int(self._sample_rate * 0.1)  # 100ms chunks
        silence_chunks_needed = int(self._silence_duration / 0.1)
        max_chunks = int(self._max_duration / 0.1)

        if self._push_to_talk:
            return self._record_push_to_talk()

        log.debug(
            "Recording: sr=%d, silence_threshold=%.3f, max=%.1fs",
            self._sample_rate,
            self._silence_threshold,
            self._max_duration,
        )

        for _ in range(max_chunks):
            chunk = sd.rec(
                frames_per_chunk,
                samplerate=self._sample_rate,
                channels=DEFAULT_CHANNELS,
                dtype="float32",
            )
            sd.wait()
            chunks.append(chunk)

            # Check for silence (RMS amplitude)
            rms = float(np.sqrt(np.mean(chunk**2)))
            if rms < self._silence_threshold:
                silence_frames += 1
                if silence_frames >= silence_chunks_needed and len(chunks) > silence_chunks_needed:
                    log.debug("Silence detected after %d chunks", len(chunks))
                    break
            else:
                silence_frames = 0

        if not chunks:
            return b""

        audio = np.concatenate(chunks, axis=0)
        return audio.tobytes()

    def _record_push_to_talk(self) -> bytes:
        """Record while Enter key is held (simplified: record until Enter pressed)."""
        sd = _import_sounddevice()
        np = _import_numpy()

        chunks: list = []
        stop_event = threading.Event()
        frames_per_chunk = int(self._sample_rate * 0.1)
        max_chunks = int(self._max_duration / 0.1)

        def _wait_for_enter():
            with contextlib.suppress(EOFError):
                input()  # Block until Enter
            stop_event.set()

        thread = threading.Thread(target=_wait_for_enter, daemon=True)
        thread.start()

        for _ in range(max_chunks):
            if stop_event.is_set():
                break
            chunk = sd.rec(
                frames_per_chunk,
                samplerate=self._sample_rate,
                channels=DEFAULT_CHANNELS,
                dtype="float32",
            )
            sd.wait()
            chunks.append(chunk)

        if not chunks:
            return b""

        audio = np.concatenate(chunks, axis=0)
        return audio.tobytes()

    def transcribe(self, audio_bytes: bytes) -> str:
        """Transcribe raw PCM float32 audio bytes to text.

        Args:
            audio_bytes: Raw PCM float32 mono audio at configured sample rate.

        Returns:
            Transcribed text string.
        """
        np = _import_numpy()
        model = self._load_model()

        audio = np.frombuffer(audio_bytes, dtype=np.float32)

        if len(audio) == 0:
            return ""

        kwargs: dict = {"beam_size": 5}
        if self._language:
            kwargs["language"] = self._language

        segments, info = model.transcribe(audio, **kwargs)

        text_parts = []
        for segment in segments:
            text_parts.append(segment.text.strip())

        text = " ".join(text_parts).strip()

        if info.language:
            log.info("Detected language: %s (prob=%.2f)", info.language, info.language_probability)

        return text

    def listen(self) -> str:
        """Record audio from microphone and transcribe to text."""
        audio_bytes = self.record_audio()
        if not audio_bytes:
            return ""
        return self.transcribe(audio_bytes)

    def respond(self, text: str) -> None:
        """Display response text to terminal (voice TTS is future work)."""
        sys.stdout.write(text)
        sys.stdout.write("\n")
        sys.stdout.flush()
