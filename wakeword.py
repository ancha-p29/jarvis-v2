"""Wake word detection with openWakeWord (built-in 'hey_jarvis' model)."""

from __future__ import annotations

import time


class WakeWordListener:
    """Block until the wake word is heard, then hand control back."""

    def __init__(
        self,
        model_name: str = "hey_jarvis",
        sensitivity: float = 0.5,
        sample_rate: int = 16000,
    ) -> None:
        self.model_name = model_name
        self.sensitivity = float(sensitivity)
        self.sample_rate = sample_rate
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            import os
            from openwakeword.model import Model

            # Model files are bundled with JARVIS in models/, so voice mode
            # works fully offline. No downloads, nothing fetched at runtime.
            models_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "models"
            )
            wakeword_path = os.path.join(models_dir, f"{self.model_name}_v0.1.onnx")
            melspec_path = os.path.join(models_dir, "melspectrogram.onnx")
            embedding_path = os.path.join(models_dir, "embedding_model.onnx")
            missing = [p for p in (wakeword_path, melspec_path, embedding_path)
                       if not os.path.exists(p)]
            if missing:
                raise FileNotFoundError(
                    "Missing wake-word model files: " + ", ".join(missing)
                    + ". Copy the 'models' folder from the JARVIS zip next to wakeword.py."
                )
            self._model = Model(
                wakeword_models=[wakeword_path],
                inference_framework="onnx",
                melspec_model_path=melspec_path,
                embedding_model_path=embedding_path,
            )
        return self._model

    def wait(self, mic_device=None, timeout: float | None = None) -> bool:
        """Listen until the wake word is detected. True on detection."""
        import sounddevice as sd

        model = self._ensure_model()
        frame = 1280  # 80 ms at 16 kHz, the frame size openWakeWord expects
        start = time.time()
        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=frame,
            device=mic_device,
        ) as stream:
            while True:
                if timeout is not None and time.time() - start > timeout:
                    return False
                data, _overflow = stream.read(frame)
                prediction = model.predict(data[:, 0])
                score = max(prediction.values()) if prediction else 0.0
                if score >= self.sensitivity:
                    if hasattr(model, "reset"):
                        model.reset()
                    return True
