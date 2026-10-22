"""Telephony: how JARVIS reaches a real phone, and how a call talks back.

Two providers:

1. SimulatedProvider (default, zero accounts, zero cost)
   "Calls" you in the terminal / writes a transcript file under
   data/calls/. Everything except the actual ringing phone works:
   watcher, message, conversation, tools. Use this to test safely.

2. TwilioProvider (the real thing)
   Uses Twilio's REST API directly over HTTPS with the standard library.
   No twilio SDK needed. Needs three environment variables (see
   .env.example) and a public URL for the phone_server (ngrok in dev).

Speech on real calls:
   Default path uses Twilio's built-in <Gather input="speech"> for
   listening and <Say> for speaking, so NO extra AI keys are needed.
   SarvamSpeech below is the optional Indian-language upgrade from the
   reel (Saaras STT, Bulbul TTS). If SARVAM_API_KEY is set you can wire
   it into a streaming deployment later; the phone flow in this repo
   deliberately does not depend on it.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent


# ---------------- TwiML helpers ----------------

def twiml_say_gather(text: str, action: str = "/voice/respond",
                     voice: str = "alice", end: bool = False) -> str:
    """TwiML: say something, then listen (or hang up if end=True)."""
    safe = escape(text)
    if end:
        body = f'<Say voice="{voice}">{safe}</Say><Hangup/>'
    else:
        body = (f'<Gather input="speech" speechTimeout="auto" timeout="6" '
                f'action="{escape(action, {chr(34): "&quot;"})}" method="POST">'
                f'<Say voice="{voice}">{safe}</Say></Gather>'
                f'<Say voice="{voice}">I heard nothing, sir. Goodbye for now.</Say><Hangup/>')
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'


# ---------------- providers ----------------

class SimulatedProvider:
    name = "simulated"

    def __init__(self, calls_dir: str | Path = "data/calls") -> None:
        self.calls_dir = ROOT / calls_dir if not Path(calls_dir).is_absolute() else Path(calls_dir)
        self.calls_dir.mkdir(parents=True, exist_ok=True)

    def call(self, to: str, message: str, reason: str = "") -> dict:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.calls_dir / f"call-{stamp}.md"
        path.write_text(
            f"# Simulated call\n\nTo: {to}\nWhen: {datetime.now().isoformat(timespec='seconds')}\n"
            f"Reason: {reason or 'proactive'}\n\nJARVIS: {message}\n",
            encoding="utf-8")
        print(f"\n[SIMULATED CALL] Calling {to} ...")
        print(f"JARVIS: {message}")
        print(f"(transcript saved to {path})\n")
        return {"provider": self.name, "status": "simulated", "to": to,
                "transcript": str(path)}


class TwilioProvider:
    name = "twilio"

    def __init__(self) -> None:
        self.account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        self.auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        self.from_number = os.environ.get("TWILIO_PHONE_NUMBER", "")
        self.public_base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

    def missing(self) -> list[str]:
        return [name for name, val in [
            ("TWILIO_ACCOUNT_SID", self.account_sid),
            ("TWILIO_AUTH_TOKEN", self.auth_token),
            ("TWILIO_PHONE_NUMBER", self.from_number),
            ("PUBLIC_BASE_URL", self.public_base_url)] if not val]

    def call(self, to: str, message: str, reason: str = "") -> dict:
        missing = self.missing()
        if missing:
            raise RuntimeError(
                "Twilio is not configured. Missing environment variables: "
                + ", ".join(missing) + ". See .env.example and PLAYBOOK.md.")
        query = urllib.parse.urlencode({"reason": reason or message})
        url = f"{self.public_base_url}/voice/outbound-answer?{query}"
        form = urllib.parse.urlencode(
            {"To": to, "From": self.from_number, "Url": url}).encode()
        req = urllib.request.Request(
            f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Calls.json",
            data=form, method="POST")
        auth = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode()).decode()
        req.add_header("Authorization", f"Basic {auth}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {"provider": self.name, "status": data.get("status", "queued"),
                "to": to, "call_sid": data.get("sid", "")}


def get_provider(config: dict):
    provider = (config.get("phone", {}) or {}).get("provider", "simulated")
    if provider == "twilio":
        return TwilioProvider()
    return SimulatedProvider()


# ---------------- optional Sarvam speech (from the reel) ----------------

class SarvamSpeech:
    """Thin client for Sarvam AI speech APIs (Saaras STT, Bulbul TTS).

    Optional. Requires SARVAM_API_KEY. The default Twilio Gather/Say
    flow works without it; use this when you want Indian language
    voices and transcription, as in the original hackathon build.
    """

    BASE = "https://api.sarvam.ai"

    def __init__(self) -> None:
        self.api_key = os.environ.get("SARVAM_API_KEY", "")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        return {"api-subscription-key": self.api_key}

    def synthesize(self, text: str, language_code: str = "en-IN",
                   speaker: str = "anushka") -> bytes | None:
        """Bulbul TTS. Returns WAV bytes, or None if not configured."""
        if not self.configured:
            return None
        payload = json.dumps({
            "text": text, "target_language_code": language_code,
            "speaker": speaker, "model": "bulbul:v2",
        }).encode()
        req = urllib.request.Request(self.BASE + "/text-to-speech", data=payload,
                                     headers={**self._headers(),
                                              "Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        audios = data.get("audios") or []
        if not audios:
            return None
        return base64.b64decode(audios[0])
