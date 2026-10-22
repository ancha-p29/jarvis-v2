#!/usr/bin/env python3
"""Make JARVIS call you, right now.

Simulated (default when Twilio is not configured):
  python call_me.py --reason "Your interview prep deadline is in 2 hours"

Real call (Twilio configured, phone server running, PUBLIC_BASE_URL set):
  python call_me.py --twilio --reason "Sir, your deadline is due in 2 hours"
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_config() -> dict:
    import yaml
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Trigger a JARVIS phone call.")
    parser.add_argument("--reason", default="Sir, this is JARVIS calling as requested. "
                        "You asked me to call you. What shall we handle first?")
    parser.add_argument("--to", default=None, help="Override the destination number.")
    parser.add_argument("--twilio", action="store_true",
                        help="Force the real Twilio provider.")
    parser.add_argument("--simulate", action="store_true",
                        help="Force the simulated provider.")
    args = parser.parse_args(argv)

    config = load_config()
    if args.twilio:
        config.setdefault("phone", {})["provider"] = "twilio"
    if args.simulate:
        config.setdefault("phone", {})["provider"] = "simulated"

    from telephony import get_provider
    provider = get_provider(config)
    to = args.to or (config.get("phone", {}) or {}).get("user_phone", "")
    result = provider.call(to, args.reason, reason="manual:call_me")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
