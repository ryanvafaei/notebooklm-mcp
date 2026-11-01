"""Read generated NotebookLM artifacts back as inline content, without keeping files.

notebooklm-py only exposes artifact export as "download to a path". To honour the
"no downloads" requirement, content is written to a private temporary directory
(0700, unique per call), read back with a size cap, and the directory is deleted
before the tool returns. Nothing persists on disk.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

#: Kinds whose content can be returned as text, and the export format used.
TEXT_KINDS: dict[str, tuple[str, str]] = {
    # kind: (download method, file extension)
    "quiz": ("download_quiz", "json"),
    "flashcards": ("download_flashcards", "json"),
    "report": ("download_report", "md"),
    "mind_map": ("download_mind_map", "json"),
    "data_table": ("download_data_table", "csv"),
}

#: Kinds that are media and can only be opened in NotebookLM itself.
MEDIA_KINDS = {"audio", "video", "slide_deck", "infographic"}

MAX_INLINE_CHARS = 60_000


def normalize_quiz(data: dict[str, Any]) -> dict[str, Any]:
    questions = []
    for q in data.get("questions", []) or []:
        options = [
            {
                "text": o.get("text", ""),
                "correct": bool(o.get("isCorrect")),
                **({"rationale": o["rationale"]} if o.get("rationale") else {}),
            }
            for o in q.get("answerOptions", []) or []
        ]
        item: dict[str, Any] = {"question": q.get("question", ""), "options": options}
        if q.get("hint"):
            item["hint"] = q["hint"]
        questions.append(item)
    return {"title": data.get("title", ""), "questions": questions}


def _read_inside(tmp: Path, written: str | None, fallback: Path) -> str:
    """Read the exported file, but only ever from inside our own temp dir."""
    path = Path(written) if written else fallback
    if tmp.resolve() not in path.resolve().parents:
        path = fallback
    return path.read_text(encoding="utf-8", errors="replace")


async def read_text_artifact(
    client: Any, notebook_id: str, kind: str, artifact_id: str | None
) -> dict[str, Any]:
    """Export a text-like artifact to a throwaway temp dir and return its content."""
    method_name, ext = TEXT_KINDS[kind]
    method = getattr(client.artifacts, method_name)
    with tempfile.TemporaryDirectory(prefix="nlm-study-") as tmp:
        out = Path(tmp) / f"artifact.{ext}"
        kwargs: dict[str, Any] = {"artifact_id": artifact_id}
        if kind in ("quiz", "flashcards"):
            kwargs["output_format"] = "json"
        written = await method(notebook_id, str(out), **kwargs)
        text = await asyncio.to_thread(_read_inside, Path(tmp), written, out)

    truncated = len(text) > MAX_INLINE_CHARS
    if ext == "json" and not truncated:
        data = json.loads(text)
        if kind == "quiz":
            data = normalize_quiz(data)
        return {"format": "json", "content": data}
    return {
        "format": "markdown" if ext == "md" else ext,
        "content": text[:MAX_INLINE_CHARS],
        "truncated": truncated,
    }
