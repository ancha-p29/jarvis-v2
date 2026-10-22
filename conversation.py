"""One conversation brain for every surface: terminal, laptop mic, phone.

Order of handling for each utterance:
  1. Tool intents (deterministic, work with NO model at all). This is what
     makes "upload it", "find my resume", "lock the screen" reliable on a
     phone call, where you do not want the model improvising.
  2. The cloud brain (fast open-source models, see brain.py), if a
     provider key is configured.
  3. A graceful fallback that still answers with deadlines and commitments.

The model can also request a tool by ending its reply with:
  [tool: find_resume {"role": "product"}]
which this module executes and reports, exactly like the v1 memory
directives.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

EXIT_PHRASES = ("goodbye", "good night", "hang up", "that is all", "thats all")

_TOOL_TAG = re.compile(r"\[tool:\s*(\w+)\s*(\{.*?\})?\]", re.IGNORECASE | re.DOTALL)


class Conversation:
    def __init__(self, config: dict, memory=None, brain=None, tools=None,
                 deadlines=None) -> None:
        self.config = config
        self.memory = memory
        self.brain = brain
        self.tools = tools
        self.deadlines = deadlines

    # ---------------- public ----------------

    def handle(self, text: str) -> dict:
        """Returns {"reply": str, "notes": [str], "tool": dict|None, "exit": bool}."""
        text = (text or "").strip()
        if not text:
            return {"reply": "I did not catch that, sir.", "notes": [], "tool": None, "exit": False}
        lowered = text.lower()
        if any(p in lowered for p in EXIT_PHRASES):
            return {"reply": "Very good, sir. I will be here when you need me.",
                    "notes": [], "tool": None, "exit": True}

        tool_result = self._tool_intent(text, lowered)
        if tool_result is not None:
            return {"reply": tool_result["spoken"], "notes": [tool_result["detail"]],
                    "tool": tool_result, "exit": False}

        if self.brain is not None:
            try:
                reply, notes = self.brain.chat(text)
                reply, tool_result = self._run_tool_tags(reply)
                if tool_result is not None:
                    notes = notes + [tool_result["detail"]]
                    if tool_result["spoken"]:
                        reply = (reply + " " + tool_result["spoken"]).strip()
                return {"reply": reply, "notes": notes, "tool": tool_result, "exit": False}
            except Exception:
                pass  # fall through to the no-model fallback

        return {"reply": self._fallback(text), "notes": [], "tool": None, "exit": False}

    # ---------------- tool tags from the model ----------------

    def _run_tool_tags(self, reply: str):
        if not self.tools:
            return reply, None
        match = _TOOL_TAG.search(reply)
        if not match:
            return reply, None
        name = match.group(1)
        args = {}
        if match.group(2):
            try:
                args = json.loads(match.group(2))
            except json.JSONDecodeError:
                args = {}
        result = self.tools.run(name, **args)
        return _TOOL_TAG.sub("", reply).strip(), result

    # ---------------- deterministic intents ----------------

    def _tool_intent(self, text: str, lowered: str):
        if not self.tools:
            return None
        t = self.tools

        m = re.search(r"find (?:my |the |a )?(?:file|files)(?: called| named)?\s+(.+)", lowered)
        if m:
            return t.run("find_files", query=m.group(1).strip(" ."))
        m = re.search(r"find (?:my |the )?(.+?)\s*(?:file|resume|pdf|document)\b", lowered)
        if "resume" in lowered:
            role = re.sub(r".*find (?:my |the )?", "", lowered)
            role = role.replace("resume", "").strip(" .")
            return t.run("find_resume", role=role)
        if lowered.startswith("find "):
            return t.run("find_files", query=lowered[5:].strip(" ."))

        if "deadline" in lowered or "what is due" in lowered or "what's due" in lowered:
            if lowered.startswith(("add", "new", "set")) or " add " in lowered:
                parsed = self._parse_add_deadline(text)
                if parsed:
                    return parsed
            return t.run("list_deadlines")

        if "commitment" in lowered or "what did i promise" in lowered or "what do i have to do" in lowered:
            return t.run("list_commitments")

        m = re.search(r"draft (?:an? )?email to ([^,]+?)(?: about (.+))?$", text, re.IGNORECASE)
        if m:
            subject = (m.group(2) or "Follow up").strip()
            return t.run("draft_email", to=m.group(1).strip(), subject=subject,
                         body=f"Hi,\n\nFollowing up on: {subject}.\n\nBest,\nPraveen")

        if "whatsapp" in lowered:
            return t.run("open_whatsapp", phone="", message="")

        if lowered.startswith("play ") or "play music" in lowered or "play some music" in lowered:
            query = re.sub(r"^.*play\s+", "", lowered).strip(" .")
            return t.run("play_music", query="" if query in ("music", "some music") else query)

        if "lock" in lowered and ("screen" in lowered or "laptop" in lowered or "computer" in lowered):
            return t.run("lock_screen")

        if "what time" in lowered or "what day" in lowered or lowered.strip() in ("time", "date"):
            return t.run("current_time")

        if self.deadlines:
            m = re.search(r"mark deadline (\d+) done", lowered)
            if m and self.deadlines.complete(int(m.group(1))):
                return {"ok": True, "spoken": f"Deadline {m.group(1)} marked done, sir. Well handled.",
                        "detail": f"deadline {m.group(1)} completed"}
        return None

    def _parse_add_deadline(self, text: str):
        """Handles: add deadline <title> by tomorrow / by 2026-10-25 / by friday."""
        m = re.search(r"add (?:a )?deadline (.+?) by (.+)$", text, re.IGNORECASE)
        if not m or not self.deadlines:
            return None
        title, when = m.group(1).strip(), m.group(2).strip(" .").lower()
        now = datetime.now()
        due = None
        if when == "tomorrow":
            due = (now + timedelta(days=1)).replace(hour=17, minute=0, second=0)
        elif when == "today":
            due = now.replace(hour=17, minute=0, second=0)
        else:
            days = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                    "friday": 4, "saturday": 5, "sunday": 6}
            if when in days:
                delta = (days[when] - now.weekday()) % 7 or 7
                due = (now + timedelta(days=delta)).replace(hour=17, minute=0, second=0)
            else:
                try:
                    due = datetime.strptime(when, "%Y-%m-%d")
                except ValueError:
                    return {"ok": False,
                            "spoken": "I need a clearer date for that deadline, sir. Try tomorrow, Friday, or a date like 2026-10-25.",
                            "detail": f"unparsed date: {when}"}
        item = self.deadlines.add(title, due.isoformat(timespec="minutes"))
        return {"ok": True,
                "spoken": f"Deadline added, sir: {title}, due {due.strftime('%A %B %d at %I:%M %p')}. I will watch it and call you before it bites.",
                "detail": f"deadline [{item['id']}] {title} due {item['due']}"}

    # ---------------- no-model fallback ----------------

    def _fallback(self, text: str) -> str:
        parts = ["My full brain is offline right now, sir, so I am running on house rules."]
        if self.tools:
            deadlines = self.tools.run("list_deadlines")
            parts.append(deadlines["spoken"])
        parts.append("Ask me to find a file, draft an email, list deadlines, play music, or lock the screen, and I can still do it.")
        return " ".join(parts)
