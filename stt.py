"""Speech to text with faster-whisper.

Heavy third-party imports are lazy: importing this module never pulls in
ctranslate2, so text mode stays light and fast.
"""

from __future__ import annotations

# RMS below this counts as silence. Tune it if your mic is hot or quiet.
_SILENCE_RMS = 0.008


class SpeechToText:
    """Record from the mic and transcribe with a local Whisper model."""

    def __init__(
        self,
        model_name: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "en",
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            # First run downloads the model automatically (small is ~460 MB).
            self._model = WhisperModel(
                self.model_name, device=self.device, compute_type=self.compute_type
            )
        return self._model

    def transcribe(self, audio, sample_rate: int = 16000) -> str:
        """Transcribe a mono float32 numpy array."""
        model = self._ensure_model()
        segments, _info = model.transcribe(audio, language=self.language, beam_size=5)
        return " ".join(seg.text.strip() for seg in segments).strip()

    def record_utterance(
        self,
        sample_rate: int = 16000,
        silence_seconds: float = 1.2,
        max_seconds: float = 30.0,
        mic_device=None,
    ):
        """Record until the speaker pauses. Returns float32 mono audio."""
        import numpy as np
        import sounddevice as sd

        chunk = int(sample_rate * 0.1)  # 100 ms frames
        frames: list = []
        started = False
        silent_for = 0.0
        elapsed = 0.0

        with sd.InputStream(
            samplerate=sample_rate, channels=1, dtype="float32", device=mic_device
        ) as stream:
            while elapsed < max_seconds:
                data, _overflow = stream.read(chunk)
                mono = data[:, 0].astype(np.float32)
                rms = float(np.sqrt(np.mean(mono**2))) if mono.size else 0.0
                if rms > _SILENCE_RMS:
                    started = True
                    silent_for = 0.0
                elif started:
                    silent_for += 0.1
                frames.append(mono)
                elapsed += 0.1
                if started and silent_for >= silence_seconds:
                    break

        if not started:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(frames)

    def listen_once(self, sample_rate: int = 16000, mic_device=None) -> str:
        """Record one utterance and transcribe it. Empty string on silence."""
        audio = self.record_utterance(sample_rate=sample_rate, mic_device=mic_device)
        if audio.size == 0:
            return ""
        return self.transcribe(audio, sample_rate=sample_rate)
