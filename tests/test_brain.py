"""Brain tests: provider selection and chat parsing, all HTTP mocked.
Run: python -m unittest discover -s tests -v"""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import brain as brain_mod          # noqa: E402
import memory as memory_mod        # noqa: E402
import persona as persona_mod      # noqa: E402

KEY_VARS = ["GROQ_API_KEY", "SARVAM_API_KEY", "OPENROUTER_API_KEY",
            "TOGETHER_API_KEY", "HF_TOKEN"]


def clean_env(**overrides):
    env = {k: v for k, v in os.environ.items() if k not in KEY_VARS}
    env.update(overrides)
    return mock.patch.dict(os.environ, env, clear=True)


def make_brain(tmp: Path, cfg_extra=None):
    cfg = {"user": {"name": "Praveen"},
           "persona": {"name": "JARVIS", "address_mode": "sir",
                       "max_spoken_sentences": 3},
           "brain": cfg_extra or {"provider": "auto"}}
    mem = memory_mod.Memory(tmp / "memory", tmp / "journal")
    return brain_mod.Brain(cfg, mem, persona_mod.build_system_prompt), mem


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._data = json.dumps(payload).encode()
        self.status = status

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ProviderSelectionTest(unittest.TestCase):
    def test_auto_picks_groq_first(self):
        with tempfile.TemporaryDirectory() as td, clean_env(
                GROQ_API_KEY="g", SARVAM_API_KEY="s"):
            b, _ = make_brain(Path(td))
            self.assertEqual(b.provider_name, "groq")
            self.assertEqual(b.model, "openai/gpt-oss-20b")
            self.assertTrue(b.configured())

    def test_auto_falls_through_to_sarvam(self):
        with tempfile.TemporaryDirectory() as td, clean_env(SARVAM_API_KEY="s"):
            b, _ = make_brain(Path(td))
            self.assertEqual(b.provider_name, "sarvam")
            self.assertEqual(b.model, "sarvam-105b")

    def test_explicit_provider_and_model_override(self):
        with tempfile.TemporaryDirectory() as td, clean_env(GROQ_API_KEY="g"):
            b, _ = make_brain(Path(td), {"provider": "groq",
                                         "models": {"groq": "openai/gpt-oss-120b"}})
            self.assertEqual(b.model, "openai/gpt-oss-120b")

    def test_no_key_means_unconfigured_with_help(self):
        with tempfile.TemporaryDirectory() as td, clean_env():
            b, _ = make_brain(Path(td))
            self.assertFalse(b.configured())
            self.assertIn("GROQ_API_KEY", b.missing_key_help())
            with self.assertRaises(brain_mod.BrainError):
                b.chat("hello")


class ChatTest(unittest.TestCase):
    def test_chat_posts_openai_format_and_strips_directives(self):
        with tempfile.TemporaryDirectory() as td, clean_env(GROQ_API_KEY="g"):
            b, mem = make_brain(Path(td))
            seen = {}

            def fake_urlopen(req, timeout=0):
                seen["url"] = req.full_url
                seen["auth"] = req.headers.get("Authorization")
                body = json.loads(req.data.decode())
                seen["model"] = body["model"]
                return FakeResponse({"choices": [{"message": {
                    "content": "Very good, sir. [remember: Praveen likes filter coffee]"}}]})

            with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
                reply, notes = b.chat("remember that I like filter coffee")
            self.assertEqual(seen["url"], "https://api.groq.com/openai/v1/chat/completions")
            self.assertEqual(seen["auth"], "Bearer g")
            self.assertEqual(seen["model"], "openai/gpt-oss-20b")
            self.assertNotIn("[remember:", reply)
            self.assertIn("filter coffee", mem.facts()[0])

    def test_reasoning_blocks_are_never_spoken(self):
        cleaned = brain_mod.strip_reasoning("<think>secret plan</think>Spoken answer, sir.")
        self.assertEqual(cleaned, "Spoken answer, sir.")


if __name__ == "__main__":
    unittest.main()
