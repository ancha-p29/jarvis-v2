"""The brain: conversation loop around a local Ollama chat model.

HTTP uses only the standard library, so the brain works anywhere Ollama runs.
Swap this class for another backend later without touching memory, persona,
or the audio modules.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request


class BrainError(RuntimeError):
    """Raised when the model backend cannot be reached or misbehaves."""


_DIRECTIVE_PATTERNS = {
    "remember": re.compile(r"\[remember:\s*(.+?)\]", re.IGNORECASE | re.DOTALL),
    "commitment": re.compile(r"\[commitment:\s*(.+?)\]", re.IGNORECASE | re.DOTALL),
    "done": re.compile(r"\[done:\s*(\d+)\]", re.IGNORECASE),
}

_EM_DASH = "\u2014"
_EN_DASH = "\u2013"


def sanitize_speech(text: str) -> str:
    """Make model output safe for speech synthesis.

    The persona prompt already forbids em dashes, but this is a backstop:
    replace them with commas so the TTS engine never trips over them.
    """
    text = text.replace(_EM_DASH, ", ").replace(_EN_DASH, " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(" ,\n")


class Brain:
    """Stateful chat client for Ollama with memory-backed directives."""

    def __init__(self, config: dict, memory, prompt_builder) -> None:
        brain_cfg = config.get("brain", {})
        self.ollama_url = brain_cfg.get("ollama_url", "http://localhost:11434").rstrip("/")
        self.model = brain_cfg.get("model", "llama3.1:8b")
        self.temperature = float(brain_cfg.get("temperature", 0.8))
        self.max_history_turns = int(brain_cfg.get("max_history_turns", 20))
        self.config = config
        self.memory = memory
        self.prompt_builder = prompt_builder
        self.history: list[dict] = []

    # ---------------- backend health ----------------

    def is_ollama_up(self, timeout: float = 3.0) -> bool:
        try:
            with urllib.request.urlopen(
                self.ollama_url + "/api/tags", timeout=timeout
            ) as resp:
                return resp.status == 200
        except Exception:
            return False

    # ---------------- chat ----------------

    def chat(self, user_text: str) -> tuple[str, list[str]]:
        """One conversational turn. Returns (spoken_reply, memory_notes)."""
        user_text = user_text.strip()
        if not user_text:
            return "", []
        self.history.append({"role": "user", "content": user_text})

        system = self.prompt_builder(self.config, self.memory.get_context())
        messages = [{"role": "system", "content": system}]
        messages.extend(self.history[-(self.max_history_turns * 2):])

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        try:
            raw = self._post("/api/chat", payload, timeout=180)
            reply_text = raw.get("message", {}).get("content", "")
        except Exception as exc:
            raise BrainError(
                f"Could not reach Ollama at {self.ollama_url}: {exc}"
            ) from exc

        clean, notes = self.apply_directives(reply_text)
        clean = sanitize_speech(clean)
        self.history.append({"role": "assistant", "content": clean})
        self.memory.journal(f"Praveen: {user_text}\nJARVIS: {clean}")
        return clean, notes

    # ---------------- directives ----------------

    def apply_directives(self, text: str) -> tuple[str, list[str]]:
        """Apply [remember:], [commitment:], [done:] tags to memory.

        Returns the tag-stripped text plus human readable notes about what
        was stored, so the terminal UI can show what JARVIS remembered.
        """
        notes: list[str] = []

        for match in _DIRECTIVE_PATTERNS["remember"].findall(text):
            fact = " ".join(match.split())
            if self.memory.remember(fact):
                notes.append(f"Remembered: {fact}")
            else:
                notes.append(f"Already knew: {fact}")

        for match in _DIRECTIVE_PATTERNS["commitment"].findall(text):
            item = " ".join(match.split())
            new_id = self.memory.add_commitment(item)
            notes.append(f"New commitment [{new_id}]: {item}")

        for match in _DIRECTIVE_PATTERNS["done"].findall(text):
            cid = int(match)
            if self.memory.complete_commitment(cid):
                notes.append(f"Commitment [{cid}] marked done.")
            else:
                notes.append(f"Commitment [{cid}] not found or already done.")

        for pattern in _DIRECTIVE_PATTERNS.values():
            text = pattern.sub("", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip(" \n"), notes

    # ---------------- http ----------------

    def _post(self, path: str, payload: dict, timeout: float) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.ollama_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise BrainError(f"Ollama returned HTTP {exc.code}: {detail}") from exc
