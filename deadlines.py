"""Deadlines: the thing J watches so JARVIS v2 can call you first.

Storage is a plain JSON file Praveen can edit by hand:
  data/deadlines.json
    [{"id": 1, "title": "Submit assignment", "due": "2026-10-23T17:00:00",
      "kind": "job", "notes": "", "done": false}]

Kinds are free text: job, interview, assignment, bill, personal, anything.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def parse_due(value: str) -> datetime:
    value = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M",
                "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(value)


class DeadlineStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._items, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def add(self, title: str, due: str, kind: str = "general",
            notes: str = "") -> dict:
        parse_due(due)  # validate early, raise on garbage
        new_id = max((d.get("id", 0) for d in self._items), default=0) + 1
        item = {"id": new_id, "title": " ".join(title.split()), "due": due,
                "kind": kind, "notes": notes, "done": False,
                "created": datetime.now().isoformat(timespec="seconds")}
        self._items.append(item)
        self._save()
        return item

    def complete(self, deadline_id: int) -> bool:
        for d in self._items:
            if d.get("id") == deadline_id and not d.get("done"):
                d["done"] = True
                self._save()
                return True
        return False

    def open_items(self) -> list[dict]:
        items = [d for d in self._items if not d.get("done")]
        return sorted(items, key=lambda d: parse_due(d["due"]))

    def classify(self, item: dict, now: datetime | None = None) -> str:
        """Return overdue, due_soon, or upcoming relative to now."""
        now = now or datetime.now()
        delta = parse_due(item["due"]) - now
        if delta.total_seconds() < 0:
            return "overdue"
        if delta.total_seconds() <= 2 * 3600:
            return "due_soon"
        return "upcoming"

    def due_within(self, hours: float,
                   now: datetime | None = None) -> list[dict]:
        now = now or datetime.now()
        out = []
        for item in self.open_items():
            delta = (parse_due(item["due"]) - now).total_seconds()
            if delta <= hours * 3600:
                out.append(item)
        return out

    @staticmethod
    def human_when(item: dict, now: datetime | None = None) -> str:
        now = now or datetime.now()
        due = parse_due(item["due"])
        delta_min = int((due - now).total_seconds() // 60)
        if delta_min < 0:
            overdue = -delta_min
            if overdue < 60:
                return f"overdue by {overdue} minutes"
            if overdue < 1440:
                return f"overdue by {overdue // 60} hours"
            return f"overdue by {overdue // 1440} days"
        if delta_min < 120:
            return f"due in {delta_min} minutes"
        if delta_min < 1440:
            return f"due in {delta_min // 60} hours"
        return f"due in {delta_min // 1440} days, on {due.strftime('%b %d at %I:%M %p')}"
