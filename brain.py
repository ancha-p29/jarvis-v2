"""The brain: fast open-source models over the cloud. NO Ollama.

JARVIS v1 ran llama3.1:8b locally through Ollama. It worked, but on a
normal laptop CPU a spoken reply took many seconds, and a phone call
cannot wait that long. So v2's brain is a thin client for hosted
inference of OPEN-SOURCE models, picked for speed:

  provider    default model                    why
  ----------  -------------------------------  -------------------------
  groq        openai/gpt-oss-20b               ~1,000 tokens/sec on
                                               Groq LPUs, free API key
  sarvam      sarvam-105b                      the reel's model family,
                                               best Indic languages
  openrouter  meta-llama/llama-3.3-70b...:free free open-model routing
  together    meta-llama/Llama-3.3-70B...Turbo fast hosted Llama
  huggingface meta-llama/Llama-3.1-8B-Instruct HF Inference router

All speak the OpenAI chat-completions format, so this module is pure
standard library, and switching brains is one line in config.yaml
(brain.provider) or which API key you set. provider "auto" (default)
uses the first provider whose key exists, in the order above.

Speed rules baked in: spoken replies are capped (brain.max_tokens,
default 300) and history is trimmed, because latency, not depth, is
what makes a voice agent feel alive.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


class BrainError(RuntimeError):
    """Raised when no provider is configured or the call fails."""


PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "env": "GROQ_API_KEY",
        "default_model": "openai/gpt-oss-20b",
        "key_url": "https://console.groq.com/keys",
    },
    "sarvam": {
        "base_url": "https://api.sarvam.ai/v1",
        "env": "SARVAM_API_KEY",
        "default_model": "sarvam-105b",
        "key_url": "https://dashboard.sarvam.ai",
        "subscription_header": True,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "env": "OPENROUTER_API_KEY",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "key_url": "https://openrouter.ai/keys",
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "env": "TOGETHER_API_KEY",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "key_url": "https://api.together.ai/settings/api-keys",
    },
    "huggingface": {
        "base_url": "https://router.huggingface.co/v1",
        "env": "HF_TOKEN",
        "default_model": "meta-llama/Llama-3.1-8B-Instruct",
        "key_url": "https://huggingface.co/settings/tokens",
    },
}
PROVIDER_ORDER = ["groq", "sarvam", "openrouter", "together", "huggingface"]

_DIRECTIVE_PATTERNS = {
    "remember": re.compile(r"\[remember:\s*(.+?)\]", re.IGNORECASE | re.DOTALL),
    "commitment": re.compile(r"\[commitment:\s*(.+?)\]", re.IGNORECASE | re.DOTALL),
    "done": re.compile(r"\[done:\s*(\d+)\]", re.IGNORECASE),
}

_EM_DASH = "\u2014"
_EN_DASH = "\u2013"


def sanitize_speech(text: str) -> str:
    text = text.replace(_EM_DASH, ", ").replace(_EN_DASH, " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(" ,\n")


def strip_reasoning(text: str) -> str:
    """Some open reasoning models wrap thoughts. Never speak those."""
    if "</think>" in text:
        text = text.split("</think>")[-1]
    return text.strip()


class Brain:
    """Stateful chat client with memory directives, provider-agnostic."""

    def __init__(self, config: dict, memory, prompt_builder) -> None:
        brain_cfg = config.get("brain", {}) or {}
        self.temperature = float(brain_cfg.get("temperature", 0.7))
        self.max_tokens = int(brain_cfg.get("max_tokens", 300))
        self.max_history_turns = int(brain_cfg.get("max_history_turns", 20))
        self.config = config
        self.memory = memory
        self.prompt_builder = prompt_builder
        self.history: list[dict] = []

        requested = str(brain_cfg.get("provider", "auto")).lower()
        models_cfg = brain_cfg.get("models", {}) or {}
        self.provider_name, self.provider = self._select_provider(requested)
        self.model = (brain_cfg.get("model")
                      or models_cfg.get(self.provider_name)
                      or self.provider["default_model"]) if self.provider else None
        self.base_url = self.provider["base_url"] if self.provider else None
        self.api_key = os.environ.get(self.provider["env"], "") if self.provider else ""

    # ---------------- provider selection ----------------

    @staticmethod
    def _select_provider(requested: str):
        if requested in PROVIDERS:
            return requested, PROVIDERS[requested]
        # "auto" (or anything unknown): first provider with a key set
        for name in PROVIDER_ORDER:
            if os.environ.get(PROVIDERS[name]["env"]):
                return name, PROVIDERS[name]
        return None, None

    def configured(self) -> bool:
        return bool(self.provider and self.api_key)

    def describe(self) -> str:
        if not self.provider:
            return "no brain provider configured"
        return f"{self.provider_name} / {self.model}"

    def missing_key_help(self) -> str:
        lines = ["No brain API key is set. JARVIS v2 uses fast hosted "
                 "open-source models, no local install. Get a free key "
                 "from ONE of these, set it as an environment variable, "
                 "and restart:"]
        for name in PROVIDER_ORDER:
            p = PROVIDERS[name]
            lines.append(f"  {p['env']}  ({name}, default {p['default_model']})  {p['key_url']}")
        return "\n".join(lines)

    # ---------------- backend health ----------------

    def is_up(self, timeout: float = 5.0) -> bool:
        """True when a provider is configured and its API answers."""
        if not self.configured():
            return False
        try:
            req = urllib.request.Request(self.base_url + "/models", method="GET")
            self._auth_headers(req)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    # Backwards-compatible alias (v1 name)
    is_ollama_up = is_up

    # ---------------- chat ----------------

    def chat(self, user_text: str) -> tuple[str, list[str]]:
        user_text = user_text.strip()
        if not user_text:
            return "", []
        if not self.configured():
            raise BrainError(self.missing_key_help())
        self.history.append({"role": "user", "content": user_text})
        system = self.prompt_builder(self.config, self.memory.get_context())
        messages = [{"role": "system", "content": system}]
        messages.extend(self.history[-(self.max_history_turns * 2):])
        try:
            reply_text = self._chat_completion(messages)
        except BrainError:
            raise
        except Exception as exc:
            raise BrainError(f"{self.provider_name} call failed: {exc}") from exc
        reply_text = strip_reasoning(reply_text)
        clean, notes = self.apply_directives(reply_text)
        clean = sanitize_speech(clean)
        self.history.append({"role": "assistant", "content": clean})
        self.memory.journal(f"Praveen: {user_text}\nJARVIS: {clean}")
        return clean, notes

    def _chat_completion(self, messages: list[dict]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        self._auth_headers(req)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise BrainError(
                f"{self.provider_name} returned HTTP {exc.code}: {detail}") from exc
        choices = raw.get("choices") or []
        if not choices:
            raise BrainError(f"{self.provider_name} returned no choices: {str(raw)[:200]}")
        return choices[0].get("message", {}).get("content", "") or ""

    def _auth_headers(self, req: urllib.request.Request) -> None:
        req.add_header("Authorization", f"Bearer {self.api_key}")
        if self.provider and self.provider.get("subscription_header"):
            # Sarvam accepts its key as a subscription header too
            req.add_header("api-subscription-key", self.api_key)

    # ---------------- directives (unchanged from v1) ----------------

    def apply_directives(self, text: str) -> tuple[str, list[str]]:
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
