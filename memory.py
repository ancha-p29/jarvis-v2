"""Persistent memory for JARVIS.

Storage is deliberately boring and human readable:
  data/memory/facts.json        long lived facts about Praveen
  data/memory/commitments.json  numbered goals and promises, open or done
  data/journal/YYYY-MM-DD.md    daily log of conversations

Praveen can open any of these in a text editor. Nothing is hidden.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path


class Memory:
    """JSON-backed facts and commitments plus a daily markdown journal."""

    def __init__(self, memory_dir: str | Path, journal_dir: str | Path) -> None:
        self.memory_dir = Path(memory_dir)
        self.journal_dir = Path(journal_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.facts_path = self.memory_dir / "facts.json"
        self.commitments_path = self.memory_dir / "commitments.json"
        self._facts: list[dict] = self._load(self.facts_path, [])
        self._commitments: list[dict] = self._load(self.commitments_path, [])

    # ---------------- persistence helpers ----------------

    @staticmethod
    def _load(path: Path, default):
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return default
        return default

    @staticmethod
    def _save(path: Path, data) -> None:
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        tmp.replace(path)

    # ---------------- facts ----------------

    def remember(self, fact: str) -> bool:
        """Store a durable fact. Returns False if it was already known."""
        fact = " ".join(fact.split())
        if not fact:
            return False
        known = {f["fact"].strip().lower() for f in self._facts if "fact" in f}
        if fact.lower() in known:
            return False
        self._facts.append(
            {"fact": fact, "added": datetime.now().isoformat(timespec="seconds")}
        )
        self._save(self.facts_path, self._facts)
        return True

    def facts(self) -> list[str]:
        return [f["fact"] for f in self._facts if "fact" in f]

    # ---------------- commitments ----------------

    def add_commitment(self, text: str) -> int:
        """Add a goal or promise. Returns its numeric id."""
        text = " ".join(text.split())
        if not text:
            raise ValueError("Commitment text must not be empty.")
        used = {c.get("id", 0) for c in self._commitments}
        new_id = max(used, default=0) + 1
        self._commitments.append(
            {
                "id": new_id,
                "text": text,
                "created": datetime.now().isoformat(timespec="seconds"),
                "done": False,
                "done_at": None,
            }
        )
        self._save(self.commitments_path, self._commitments)
        return new_id

    def complete_commitment(self, commitment_id: int) -> bool:
        """Mark a commitment done. False if the id is unknown or already done."""
        for c in self._commitments:
            if c.get("id") == commitment_id:
                if c.get("done"):
                    return False
                c["done"] = True
                c["done_at"] = datetime.now().isoformat(timespec="seconds")
                self._save(self.commitments_path, self._commitments)
                return True
        return False

    def list_commitments(self, open_only: bool = True) -> list[dict]:
        if open_only:
            items = [c for c in self._commitments if not c.get("done")]
        else:
            items = list(self._commitments)
        return sorted(items, key=lambda c: c.get("id", 0))

    # ---------------- journal ----------------

    def journal(self, entry: str) -> Path:
        """Append a timestamped entry to today's journal file."""
        entry = entry.strip()
        path = self.journal_dir / f"{date.today().isoformat()}.md"
        stamp = datetime.now().strftime("%H:%M")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n## {stamp}\n{entry}\n")
        return path

    def read_journal(self, day: str | None = None) -> str:
        """Read a journal file (default: today). Empty string if none exists."""
        path = self.journal_dir / f"{day or date.today().isoformat()}.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    # ---------------- context for the brain ----------------

    def get_context(self) -> str:
        """Render everything the model needs to know before a turn."""
        lines = [f"Today is {date.today().isoformat()}."]
        facts = self.facts()
        if facts:
            lines.append("Known facts about Praveen:")
            lines += [f"- {f}" for f in facts]
        open_items = self.list_commitments()
        if open_items:
            lines.append("Open commitments (referenced by id):")
            lines += [f"- [{c['id']}] {c['text']}" for c in open_items]
        today = self.read_journal().strip()
        if today:
            tail = "\n".join(today.splitlines()[-12:])
            lines.append("Earlier today:")
            lines.append(tail)
        return "\n".join(lines)
