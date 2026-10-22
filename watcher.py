#!/usr/bin/env python3
"""The watcher: J's superpower in the reel. It watches deadlines so
JARVIS can call YOU first, instead of waiting to be asked.

Run once:     python watcher.py --once
Run forever:  python watcher.py --loop        (checks every 5 minutes)

Deduping: each deadline alerts once per window (24h before, 2h before,
30 min before, overdue). State lives in data/watcher_state.json, so
restarting never re-spams you about the same window.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WINDOWS = [(1440, "24 hours"), (120, "2 hours"), (30, "30 minutes")]


def load_config() -> dict:
    import yaml
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


class Watcher:
    def __init__(self, config: dict, provider=None) -> None:
        from deadlines import DeadlineStore
        from telephony import get_provider
        w = config.get("watcher", {})
        self.store = DeadlineStore(resolve(w.get("deadlines_file", "data/deadlines.json")))
        self.state_path = resolve(w.get("state_file", "data/watcher_state.json"))
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state: dict = self._load_state()
        self.provider = provider or get_provider(config)
        self.user_phone = (config.get("phone", {}) or {}).get("user_phone", "")
        self.config = config

    def _load_state(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_state(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.state_path)

    def _alert_key(self, item: dict, now: datetime) -> str | None:
        from deadlines import parse_due
        delta_min = (parse_due(item["due"]) - now).total_seconds() / 60
        if delta_min < 0:
            return f"{item['id']}:overdue"
        for minutes, _label in WINDOWS:
            if delta_min <= minutes:
                return f"{item['id']}:{minutes}"
        return None

    def message_for(self, item: dict, now: datetime) -> str:
        from deadlines import DeadlineStore
        when = DeadlineStore.human_when(item, now)
        return (f"Sir, this is JARVIS. Your deadline, {item['title']}, is {when}. "
                f"It is still open. Shall I help you with it now? "
                f"You can ask me to find a file, draft an email, or mark it done.")

    def check_once(self, now: datetime | None = None, call: bool = True) -> list[dict]:
        now = now or datetime.now()
        fired = []
        for item in self.store.open_items():
            key = self._alert_key(item, now)
            if not key or self.state.get(key):
                continue
            message = self.message_for(item, now)
            result = {"deadline_id": item["id"], "title": item["title"],
                      "key": key, "message": message}
            if call:
                result["call"] = self.provider.call(self.user_phone, message,
                                                    reason=f"deadline:{key}")
            self.state[key] = datetime.now().isoformat(timespec="seconds")
            self._save_state()
            fired.append(result)
        return fired


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="JARVIS deadline watcher.")
    parser.add_argument("--once", action="store_true", help="Check once and exit.")
    parser.add_argument("--loop", action="store_true", help="Check forever.")
    parser.add_argument("--no-call", action="store_true",
                        help="Report alerts without placing calls.")
    args = parser.parse_args(argv)
    config = load_config()
    watcher = Watcher(config)
    interval = int((config.get("watcher", {}) or {}).get("interval_seconds", 300))
    if args.loop:
        print(f"Watcher running. Checking every {interval}s. Ctrl+C to stop.")
        try:
            while True:
                fired = watcher.check_once(call=not args.no_call)
                for f in fired:
                    print(f"[alert] {f['title']}: {f['message']}")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nWatcher stopped.")
        return 0
    fired = watcher.check_once(call=not args.no_call)
    if not fired:
        print("No new deadline alerts.")
    for f in fired:
        print(f"[alert] {f['title']}: {f['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
