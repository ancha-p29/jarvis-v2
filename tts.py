"""Text to speech with Piper: local neural voices, no cloud, no keys."""

from __future__ import annotations

from pathlib import Path


class TextToSpeech:
    """Synthesize speech with a Piper voice model and play it back."""

    def __init__(self, voice_model_path: str | Path) -> None:
        self.voice_model_path = Path(voice_model_path)
        self._voice = None

    def _ensure_voice(self):
        if self._voice is None:
            if not self.voice_model_path.exists():
                raise FileNotFoundError(
                    f"Piper voice model not found: {self.voice_model_path}. "
                    "Download a voice (see README, 'Piper voices') and point "
                    "tts.voice_model at the .onnx file in config.yaml."
                )
            from piper import PiperVoice

            # PiperVoice.load finds the matching .onnx.json config next to the model.
            self._voice = PiperVoice.load(str(self.voice_model_path))
        return self._voice

    def synthesize(self, text: str):
        """Return (audio_float32_mono, sample_rate)."""
        import numpy as np

        voice = self._ensure_voice()
        chunks = [
            np.asarray(c.audio_float_array, dtype=np.float32)
            for c in voice.synthesize(text)
        ]
        audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        return audio, voice.config.sample_rate

    def speak(self, text: str, speaker_device=None) -> None:
        """Synthesize and play through the speaker. Blocks until finished."""
        import sounddevice as sd

        audio, sample_rate = self.synthesize(text)
        if audio.size:
            sd.play(audio, sample_rate, device=speaker_device)
            sd.wait()
