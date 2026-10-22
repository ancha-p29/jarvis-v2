#!/usr/bin/env python3
"""Phone server: the public end of JARVIS v2's phone number.

Pure standard library HTTP server (no Flask needed), so it runs the
same on Windows, Mac, and Linux the moment Python is installed.

Endpoints:
  GET  /health                 -> {"ok": true, ...}
  POST /voice                  -> Twilio webhook: someone called your
                                  Twilio number. Greets and listens.
  POST /voice/respond          -> Twilio webhook: what they said,
                                  answered by the shared Conversation.
  POST /voice/outbound-answer  -> Twilio webhook for proactive calls:
                                  says the reason, then listens.
  POST /api/call-me            -> JSON {"reason": "..."} triggers an
                                  outbound call via the configured
                                  provider. Protected by X-Jarvis-Secret
                                  when JARVIS_API_SECRET is set.

Run:  python phone_server.py            (port from config or $PORT)
Expose in dev:  ngrok http 8765         then set PUBLIC_BASE_URL and
point your Twilio number's voice webhook at <PUBLIC_BASE_URL>/voice
"""

from __future__ import annotations

import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_config() -> dict:
    import yaml
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def build_conversation(config: dict):
    """Wire memory, brain (if Ollama is up), tools and deadlines together."""
    import memory as memory_mod
    import persona as persona_mod
    from brain import Brain
    from conversation import Conversation
    from deadlines import DeadlineStore
    from tools import ToolRegistry

    mem = memory_mod.Memory(resolve(config["memory"]["dir"]),
                            resolve(config["memory"]["journal_dir"]))
    brain = Brain(config, mem, persona_mod.build_system_prompt)
    if not brain.configured():
        brain = None  # Conversation still answers with tools and house rules
    deadlines = DeadlineStore(resolve(
        (config.get("watcher", {}) or {}).get("deadlines_file", "data/deadlines.json")))
    tools = ToolRegistry(config, deadlines=deadlines, memory=mem)
    return Conversation(config, memory=mem, brain=brain, tools=tools,
                        deadlines=deadlines)


class App:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.conversation = build_conversation(config)
        self.sessions: dict[str, list] = {}

    # ---- route logic (unit-testable without HTTP) ----

    def inbound_twiml(self) -> str:
        from telephony import twiml_say_gather
        name = self.config.get("persona", {}).get("name", "JARVIS")
        return twiml_say_gather(
            f"{name} speaking. How may I help you, sir?")

    def respond_twiml(self, call_sid: str, speech: str) -> str:
        from telephony import twiml_say_gather
        result = self.conversation.handle(speech or "")
        self.sessions.setdefault(call_sid, []).append(
            {"user": speech, "jarvis": result["reply"]})
        return twiml_say_gather(result["reply"], end=result["exit"])

    def outbound_twiml(self, reason: str) -> str:
        from telephony import twiml_say_gather
        return twiml_say_gather(reason or "Sir, this is JARVIS calling with an update.")

    def trigger_call(self, reason: str) -> dict:
        from telephony import get_provider
        provider = get_provider(self.config)
        phone = (self.config.get("phone", {}) or {}).get("user_phone", "")
        return provider.call(phone, reason, reason="api:call-me")


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the console clean
            pass

        def _send(self, code: int, body: str, content_type: str) -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 (stdlib name)
            if self.path.startswith("/health"):
                self._send(200, json.dumps({"ok": True, "service": "jarvis-v2-phone"}),
                           "application/json")
            else:
                self._send(200, "JARVIS v2 phone server. See /health and README.md.",
                           "text/plain")

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            if path == "/api/call-me":
                secret = os.environ.get("JARVIS_API_SECRET", "")
                if secret and self.headers.get("X-Jarvis-Secret") != secret:
                    self._send(401, json.dumps({"ok": False, "error": "bad secret"}),
                               "application/json")
                    return
                try:
                    payload = json.loads(raw or "{}")
                except json.JSONDecodeError:
                    payload = {}
                reason = payload.get("reason") or "Sir, this is JARVIS calling as requested."
                try:
                    result = app.trigger_call(reason)
                    self._send(200, json.dumps({"ok": True, "result": result}),
                               "application/json")
                except Exception as exc:
                    self._send(502, json.dumps({"ok": False, "error": str(exc)}),
                               "application/json")
                return

            form = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
            if path == "/voice":
                self._send(200, app.inbound_twiml(), "text/xml")
            elif path == "/voice/respond":
                twiml = app.respond_twiml(form.get("CallSid", "unknown"),
                                          form.get("SpeechResult", ""))
                self._send(200, twiml, "text/xml")
            elif path == "/voice/outbound-answer":
                query = {k: v[0] for k, v in
                         urllib.parse.parse_qs(parsed.query).items()}
                self._send(200, app.outbound_twiml(query.get("reason", "")), "text/xml")
            else:
                self._send(404, "not found", "text/plain")

    return Handler


def main() -> int:
    config = load_config()
    port = int(os.environ.get("PORT") or
               (config.get("phone", {}) or {}).get("port", 8765))
    app = App(config)
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(app))
    print(f"JARVIS v2 phone server listening on http://localhost:{port}")
    print("Health:  GET  /health")
    print("Twilio voice webhook:  POST /voice")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPhone server stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
