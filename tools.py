"""Tool registry: things JARVIS can actually DO on your laptop.

This is the part that turns a chatbot into J from the reel. Every tool
returns {"ok": bool, "spoken": str, "detail": str} where "spoken" is short
enough to be read aloud on a phone call.

Add your own tool: write a function, decorate it, done. That is the whole
extensibility story, same as in the reel: "if she can't do something yet,
you add it as a custom tool."

Safety defaults:
- lock_screen is a DRY RUN unless tools.lock_screen_dry_run is false in
  config.yaml. A phone call should never lock you out by accident while
  you are still testing.
- draft_email only writes a local draft file. It never sends anything.
- open_whatsapp only builds a wa.me link / tries to open the app URL.
  It never sends a message.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class ToolRegistry:
    def __init__(self, config: dict, deadlines=None, memory=None) -> None:
        self.config = config
        self.tools_cfg = config.get("tools", {})
        self.deadlines = deadlines
        self.memory = memory
        self._tools: dict[str, dict] = {}
        self._register_defaults()

    # ---------- registry plumbing ----------

    def register(self, name: str, description: str):
        def wrap(fn):
            self._tools[name] = {"description": description, "fn": fn}
            return fn
        return wrap

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> str:
        return "\n".join(f"- {n}: {t['description']}"
                         for n, t in sorted(self._tools.items()))

    def run(self, name: str, **kwargs) -> dict:
        tool = self._tools.get(name)
        if not tool:
            return {"ok": False, "spoken": f"I do not have a tool called {name} yet, sir.",
                    "detail": f"unknown tool: {name}"}
        try:
            return tool["fn"](**kwargs)
        except Exception as exc:  # a broken tool must never kill a call
            return {"ok": False, "spoken": "That tool stumbled, sir.",
                    "detail": f"{name} failed: {exc}"}

    # ---------- helpers ----------

    def _search_dirs(self) -> list[Path]:
        dirs = self.tools_cfg.get("search_dirs") or ["~", "~/Downloads", "~/Documents"]
        out = []
        for d in dirs:
            p = Path(os.path.expanduser(str(d)))
            if p.exists():
                out.append(p)
        return out or [Path.home()]

    def _find(self, query: str, limit: int = 5) -> list[Path]:
        query = query.lower().strip()
        hits: list[Path] = []
        skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv",
                     "AppData", ".cache"}
        max_depth = int(self.tools_cfg.get("search_max_depth", 5))
        for base in self._search_dirs():
            for dirpath, dirnames, filenames in os.walk(base):
                depth = len(Path(dirpath).relative_to(base).parts) if dirpath != str(base) else 0
                if depth >= max_depth:
                    dirnames[:] = []
                dirnames[:] = [d for d in dirnames if d not in skip_dirs
                               and not d.startswith(".")]
                for name in filenames:
                    if query in name.lower():
                        hits.append(Path(dirpath) / name)
                if len(hits) >= limit * 8:
                    break
        def sort_key(p: Path):
            mtime = p.stat().st_mtime if p.exists() else 0
            penalty = 1 if "report" in p.name.lower() else 0
            return (penalty, -mtime)
        hits.sort(key=sort_key)
        return hits[:limit]

    # ---------- the tools ----------

    def _register_defaults(self) -> None:

        @self.register("find_files", "Find files on this computer by name. Args: query")
        def find_files(query: str = "") -> dict:
            hits = self._find(query)
            if not hits:
                return {"ok": False, "spoken": f"I found no file matching {query}, sir.",
                        "detail": "no matches"}
            names = ", ".join(p.name for p in hits[:3])
            detail = "\n".join(str(p) for p in hits)
            return {"ok": True, "spoken": f"Found {len(hits)} matching files. First: {names}.",
                    "detail": detail}

        @self.register("find_resume", "Find your newest resume PDF. Args: role (optional hint)")
        def find_resume(role: str = "") -> dict:
            query = role.strip() or "resume"
            hits = [p for p in self._find(query, limit=10) if p.suffix.lower() in (".pdf", ".docx")]
            if not hits:
                hits = [p for p in self._find("resume", limit=10)
                        if p.suffix.lower() in (".pdf", ".docx")]
            if not hits:
                return {"ok": False, "spoken": "I could not find a resume file, sir.",
                        "detail": "no resume found in search dirs"}
            return {"ok": True, "spoken": f"Your newest matching resume is {hits[0].name}.",
                    "detail": "\n".join(str(p) for p in hits)}

        @self.register("draft_email", "Draft an email to a local file. Never sends. Args: to, subject, body")
        def draft_email(to: str = "", subject: str = "", body: str = "") -> dict:
            drafts_dir = ROOT / self.tools_cfg.get("email_drafts_dir", "data/email_drafts")
            drafts_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            safe_subject = re.sub(r"[^A-Za-z0-9_-]+", "-", subject or "draft").strip("-")[:40]
            path = drafts_dir / f"{stamp}-{safe_subject}.md"
            path.write_text(f"To: {to}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
            return {"ok": True,
                    "spoken": f"Draft saved, sir. It is in your email drafts folder, addressed to {to or 'no one yet'}. Nothing was sent.",
                    "detail": str(path)}

        @self.register("open_whatsapp", "Build a WhatsApp chat link. Never sends. Args: phone, message")
        def open_whatsapp(phone: str = "", message: str = "") -> dict:
            digits = re.sub(r"\D", "", phone or "")
            url = "https://wa.me/" + (digits or "")
            if message:
                url += "?text=" + urllib.parse.quote(message)
            opened = False
            if self.tools_cfg.get("open_browser", False):
                opened = webbrowser.open(url)
            return {"ok": True,
                    "spoken": "I prepared the WhatsApp link, sir. It opens a chat, it does not send anything.",
                    "detail": url + (f" (opened in browser: {opened})" if opened else "")}

        @self.register("play_music", "Build a Spotify search link for a song or artist. Args: query")
        def play_music(query: str = "") -> dict:
            url = "https://open.spotify.com/search/" + urllib.parse.quote(query or "focus music")
            if self.tools_cfg.get("open_browser", False):
                webbrowser.open(url)
            return {"ok": True, "spoken": f"I queued up the search for {query or 'focus music'}, sir.",
                    "detail": url}

        @self.register("lock_screen", "Lock the screen. Dry run by default. Args: none")
        def lock_screen() -> dict:
            if self.tools_cfg.get("lock_screen_dry_run", True):
                return {"ok": True,
                        "spoken": "Lock screen is in dry run mode, sir, so I only pretended. Set lock_screen_dry_run to false in config when you trust me with it.",
                        "detail": "dry run, no lock performed"}
            system = platform.system()
            cmd = {"Windows": ["rundll32.exe", "user32.dll,LockWorkStation"],
                   "Darwin": ["/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession", "-suspend"],
                   "Linux": ["loginctl", "lock-session"]}.get(system)
            if not cmd:
                return {"ok": False, "spoken": "I do not know how to lock this system, sir.", "detail": system}
            subprocess.run(cmd, check=False)
            return {"ok": True, "spoken": "Screen locked, sir.", "detail": " ".join(cmd)}

        @self.register("list_deadlines", "List open deadlines, soonest first. Args: none")
        def list_deadlines() -> dict:
            if not self.deadlines:
                return {"ok": False, "spoken": "Deadlines are not wired up, sir.", "detail": "no store"}
            items = self.deadlines.open_items()
            if not items:
                return {"ok": True, "spoken": "No open deadlines, sir. A rare and beautiful sight.",
                        "detail": "none"}
            from deadlines import DeadlineStore
            spoken_parts = [f"{d['title']}, {DeadlineStore.human_when(d)}" for d in items[:3]]
            return {"ok": True,
                    "spoken": "Your next deadlines: " + "; ".join(spoken_parts) + ".",
                    "detail": "\n".join(f"[{d['id']}] {d['title']} due {d['due']}" for d in items)}

        @self.register("list_commitments", "List open commitments from memory. Args: none")
        def list_commitments() -> dict:
            if not self.memory:
                return {"ok": False, "spoken": "Memory is not wired up, sir.", "detail": "no memory"}
            items = self.memory.list_commitments()
            if not items:
                return {"ok": True, "spoken": "No open commitments, sir.", "detail": "none"}
            spoken = "; ".join(c["text"] for c in items[:3])
            return {"ok": True, "spoken": f"You have {len(items)} open commitments. Top of the list: {spoken}.",
                    "detail": "\n".join(f"[{c['id']}] {c['text']}" for c in items)}

        @self.register("current_time", "Say the current date and time. Args: none")
        def current_time() -> dict:
            now = datetime.now()
            return {"ok": True, "spoken": now.strftime("It is %A, %B %d, %I:%M %p, sir."),
                    "detail": now.isoformat()}
