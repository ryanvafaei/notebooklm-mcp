"""Local quiz history and weak-spot tracking, per notebook.

Stored in ``progress.json`` next to the study profile (0600, atomic writes). Each quiz
result records the score and which topics were covered or missed; weak spots are the
topics you miss most often, weighted towards recent misses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .storage import default_home, read_json, write_json

MAX_SESSIONS = 200
MAX_TOPICS_PER_RESULT = 50
MAX_TOPIC_LEN = 120
MAX_TOPICS_PER_NOTEBOOK = 500


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _clean_topics(topics: list[str] | None, label: str) -> list[str]:
    out: list[str] = []
    for t in topics or []:
        t = " ".join(str(t).split())
        if not t:
            continue
        if len(t) > MAX_TOPIC_LEN:
            raise ValueError(f"A {label} entry is too long (max {MAX_TOPIC_LEN} chars).")
        if t.lower() not in (x.lower() for x in out):
            out.append(t)
    if len(out) > MAX_TOPICS_PER_RESULT:
        raise ValueError(f"Too many {label} (max {MAX_TOPICS_PER_RESULT}).")
    return out


class ProgressStore:
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or default_home()
        self.path = self.home / "progress.json"

    def record(
        self,
        notebook_id: str,
        *,
        score: int,
        total: int,
        topic: str = "",
        missed_topics: list[str] | None = None,
        covered_topics: list[str] | None = None,
        notebook_title: str | None = None,
    ) -> dict[str, Any]:
        if not notebook_id.strip() or len(notebook_id) > 200:
            raise ValueError("Invalid notebook ID.")
        if not (0 < total <= 500 and 0 <= score <= total):
            raise ValueError("Score must satisfy 0 <= score <= total and 0 < total <= 500.")
        missed = _clean_topics(missed_topics, "missed_topics")
        covered = _clean_topics(covered_topics, "covered_topics")
        topic = " ".join(topic.split())[:MAX_TOPIC_LEN]
        now = _now()

        doc = read_json(self.path)
        notebooks = doc.setdefault("notebooks", {})
        nb = notebooks.setdefault(notebook_id, {"sessions": [], "topics": {}})
        if notebook_title:
            nb["title"] = notebook_title[:200]
        nb["sessions"].append(
            {"at": now, "topic": topic, "score": score, "total": total, "missed": missed}
        )
        nb["sessions"] = nb["sessions"][-MAX_SESSIONS:]

        topics = nb["topics"]
        missed_keys = {m.lower() for m in missed}
        for label in [*missed, *[c for c in covered if c.lower() not in missed_keys]]:
            key = label.lower()
            entry = topics.setdefault(
                key, {"label": label, "seen": 0, "missed": 0, "last_missed": None}
            )
            entry["seen"] += 1
            entry["last_seen"] = now
            if key in missed_keys:
                entry["missed"] += 1
                entry["last_missed"] = now
        if len(topics) > MAX_TOPICS_PER_NOTEBOOK:  # forget the stalest topics
            keep = sorted(
                topics.items(), key=lambda kv: kv[1].get("last_seen") or "", reverse=True
            )[:MAX_TOPICS_PER_NOTEBOOK]
            nb["topics"] = dict(keep)
        write_json(self.path, doc)
        return self.summary(notebook_id)

    def summary(self, notebook_id: str, *, limit: int = 10) -> dict[str, Any]:
        nb = read_json(self.path).get("notebooks", {}).get(notebook_id)
        if not nb:
            return {"has_history": False, "sessions": 0, "weak_spots": [], "recent": []}
        sessions = nb.get("sessions", [])
        pct = [s["score"] / s["total"] for s in sessions if s.get("total")]
        topics = list(nb.get("topics", {}).values())
        weak = sorted(
            (t for t in topics if t.get("missed")),
            key=lambda t: (
                t["missed"] / max(t["seen"], 1),
                t["missed"],
                t.get("last_missed") or "",
            ),
            reverse=True,
        )[:limit]
        mastered = [t["label"] for t in topics if t.get("seen", 0) >= 3 and not t.get("missed")][
            :limit
        ]
        return {
            "has_history": True,
            "sessions": len(sessions),
            "average_score_pct": round(100 * sum(pct) / len(pct)) if pct else None,
            "recent": [
                {
                    "at": s["at"],
                    "topic": s.get("topic") or None,
                    "score": f"{s['score']}/{s['total']}",
                }
                for s in sessions[-5:]
            ],
            "weak_spots": [
                {
                    "topic": t["label"],
                    "missed": t["missed"],
                    "seen": t["seen"],
                    "last_missed": t.get("last_missed"),
                }
                for t in weak
            ],
            "mastered": mastered,
        }
