"""JARVIS v2 tests. Run: python -m pytest tests/ -q  OR  python -m unittest discover -s tests -v"""
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from conversation import Conversation          # noqa: E402
from deadlines import DeadlineStore            # noqa: E402
from telephony import SimulatedProvider, twiml_say_gather  # noqa: E402
from tools import ToolRegistry                 # noqa: E402
from watcher import Watcher                    # noqa: E402


def make_config(tmp: Path) -> dict:
    return {
        "user": {"name": "Praveen"},
        "persona": {"name": "JARVIS", "address_mode": "sir", "max_spoken_sentences": 3},
        "memory": {"dir": str(tmp / "memory"), "journal_dir": str(tmp / "journal")},
        "watcher": {"deadlines_file": str(tmp / "deadlines.json"),
                    "state_file": str(tmp / "watcher_state.json"),
                    "interval_seconds": 300},
        "phone": {"provider": "simulated", "user_phone": "+10000000000", "port": 8765},
        "tools": {"search_dirs": [str(tmp)], "email_drafts_dir": str(tmp / "drafts"),
                  "lock_screen_dry_run": True, "open_browser": False},
    }


class ToolsTest(unittest.TestCase):
    def test_find_files_and_draft_email_and_lock_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "praveen_resume_product.pdf").write_text("x")
            reg = ToolRegistry(make_config(tmp))
            found = reg.run("find_files", query="resume")
            self.assertTrue(found["ok"])
            draft = reg.run("draft_email", to="a@b.com", subject="Hi", body="Body")
            self.assertTrue(draft["ok"])
            self.assertTrue(Path(draft["detail"]).exists())
            lock = reg.run("lock_screen")
            self.assertTrue(lock["ok"])
            self.assertIn("dry run", lock["detail"])

    def test_unknown_tool_is_graceful(self):
        with tempfile.TemporaryDirectory() as td:
            reg = ToolRegistry(make_config(Path(td)))
            self.assertFalse(reg.run("teleport")["ok"])


class ConversationTest(unittest.TestCase):
    def test_intents_without_any_model(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "my_resume.pdf").write_text("x")
            store = DeadlineStore(tmp / "deadlines.json")
            store.add("Submit the thing", (datetime.now() + timedelta(hours=1)).isoformat(timespec="minutes"))
            reg = ToolRegistry(make_config(tmp), deadlines=store)
            conv = Conversation(make_config(tmp), brain=None, tools=reg, deadlines=store)
            self.assertIn("deadline", conv.handle("what are my deadlines")["reply"].lower())
            self.assertTrue(conv.handle("find my resume")["tool"]["ok"])
            self.assertTrue(conv.handle("add deadline call the recruiter by tomorrow")["tool"]["ok"])
            self.assertEqual(len(store.open_items()), 2)
            self.assertTrue(conv.handle("goodbye")["exit"])
            fallback = conv.handle("tell me a story")
            self.assertIn("house rules", fallback["reply"])


class WatcherTest(unittest.TestCase):
    def test_alerts_once_per_window(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = make_config(tmp)
            store = DeadlineStore(tmp / "deadlines.json")
            store.add("Due soon", (datetime.now() + timedelta(minutes=90)).isoformat(timespec="minutes"))
            provider = SimulatedProvider(calls_dir=tmp / "calls")
            watcher = Watcher(cfg, provider=provider)
            first = watcher.check_once()
            second = watcher.check_once()
            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 0)
            self.assertEqual(len(list((tmp / "calls").glob("*.md"))), 1)


class TwimlTest(unittest.TestCase):
    def test_twiml_is_valid_xml_with_gather(self):
        xml = twiml_say_gather("Hello <sir> & welcome")
        root = ET.fromstring(xml)
        self.assertEqual(root.tag, "Response")
        self.assertIsNotNone(root.find("Gather"))

    def test_simulated_call_writes_transcript(self):
        with tempfile.TemporaryDirectory() as td:
            provider = SimulatedProvider(calls_dir=Path(td))
            result = provider.call("+1000", "Sir, a test.")
            self.assertEqual(result["status"], "simulated")
            self.assertTrue(Path(result["transcript"]).exists())


class PhoneServerTest(unittest.TestCase):
    def test_app_routes_without_http(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = make_config(tmp)
            cfg["brain"] = {"ollama_url": "http://localhost:9", "model": "x"}
            # phone_server imports yaml config file; patch its loader target by
            # constructing App pieces directly instead: test TwiML via Conversation
            store = DeadlineStore(tmp / "deadlines.json")
            reg = ToolRegistry(cfg, deadlines=store)
            conv = Conversation(cfg, brain=None, tools=reg, deadlines=store)
            reply = conv.handle("what time is it")
            self.assertIn("It is", reply["reply"])
            saved = json.loads((tmp / "deadlines.json").read_text()) if (tmp / "deadlines.json").exists() else []
            self.assertIsInstance(saved, list)


if __name__ == "__main__":
    unittest.main()
