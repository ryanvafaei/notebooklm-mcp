"""Citation handling for documents assembled from many NotebookLM answers.

Each NotebookLM answer numbers its citations locally ([1], [2] ...), so answers to
different prompts can't simply be concatenated. The document workflow therefore uses
two deterministic steps instead of asking Claude to renumber by hand:

1. :func:`tokenize_answer` rewrites an answer's local ``[N]`` markers into stable
   source tokens ``[src:<8-char source-id prefix>]``. Tokens survive light editing
   and mean the same thing across sections and separate tool calls.
2. :func:`finalize` renumbers the tokens in a finished draft to ``[1]``, ``[2]`` ...
   in order of first appearance and builds the matching reference list.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

PREFIX_LEN = 8
TOKEN_RE = re.compile(r"\[src:([A-Za-z0-9_-]{4,64})\]")
# NotebookLM emits " [3]"; tolerate grouped forms like "[1, 2]" or "[1-3]" defensively.
_LOCAL_MARKER_RE = re.compile(r" ?\[(\d+(?:\s*[,–-]\s*\d+)*)\]")


def source_token(source_id: str) -> str:
    return f"[src:{source_id[:PREFIX_LEN]}]"


def _expand(group: str) -> list[int]:
    numbers: list[int] = []
    for part in re.split(r"\s*,\s*", group):
        bounds = re.split(r"\s*[–-]\s*", part)
        if len(bounds) == 2 and bounds[0].isdigit() and bounds[1].isdigit():
            lo, hi = int(bounds[0]), int(bounds[1])
            if 0 < lo <= hi and hi - lo <= 50:
                numbers.extend(range(lo, hi + 1))
                continue
        if part.isdigit():
            numbers.append(int(part))
    return numbers


def _resolve(references: Sequence[Any], number: int) -> str | None:
    """Find the source id behind local marker ``[number]`` (mirrors the library)."""
    for ref in references:
        if getattr(ref, "citation_number", None) == number and getattr(ref, "source_id", None):
            return ref.source_id
    index = number - 1
    if 0 <= index < len(references):
        ref = references[index]
        if getattr(ref, "citation_number", None) is None and getattr(ref, "source_id", None):
            return ref.source_id
    return None


def tokenize_answer(answer: str, references: Sequence[Any]) -> tuple[str, list[str], int]:
    """Replace local ``[N]`` markers with ``[src:...]`` tokens.

    Returns ``(text, cited_source_ids_in_order, unresolved_marker_count)``. Markers that
    can't be tied to a source are removed rather than left dangling.
    """
    cited: list[str] = []
    unresolved = 0

    max_number = max(
        [getattr(r, "citation_number", None) or 0 for r in references] + [len(references)]
    )

    def repl(match: re.Match[str]) -> str:
        nonlocal unresolved
        numbers = _expand(match.group(1))
        if not numbers or any(n > max_number for n in numbers):
            return match.group(0)  # not a citation (e.g. "[2024]"): leave text untouched
        tokens: list[str] = []
        for number in numbers:
            source_id = _resolve(references, number)
            if source_id is None:
                unresolved += 1
                continue
            token = source_token(source_id)
            if token not in tokens:
                tokens.append(token)
            if source_id not in cited:
                cited.append(source_id)
        return (" " + "".join(tokens)) if tokens else ""

    return _LOCAL_MARKER_RE.sub(repl, answer), cited, unresolved


def finalize(
    markdown: str,
    sources: Iterable[Any],
    *,
    heading: str = "References",
) -> dict[str, Any]:
    """Renumber ``[src:...]`` tokens to ``[1]..[n]`` and append a reference list."""
    by_prefix: dict[str, Any] = {}
    ambiguous: set[str] = set()
    for s in sources:
        sid = getattr(s, "id", "") or ""
        for length in range(4, min(len(sid), 64) + 1):
            key = sid[:length]
            if key in by_prefix and by_prefix[key] is not s:
                ambiguous.add(key)
            else:
                by_prefix[key] = s

    numbers: dict[str, int] = {}  # source id -> reference number
    ordered: list[Any] = []
    unresolved: list[str] = []

    def repl(match: re.Match[str]) -> str:
        prefix = match.group(1)
        source = by_prefix.get(prefix) if prefix not in ambiguous else None
        if source is None:
            if prefix not in unresolved:
                unresolved.append(prefix)
            return ""
        if source.id not in numbers:
            numbers[source.id] = len(numbers) + 1
            ordered.append(source)
        return f"[{numbers[source.id]}]"

    body = TOKEN_RE.sub(repl, markdown)
    body = re.sub(r"(\[\d+\])(?:\s*\1)+", r"\1", body)  # "[2][2]" -> "[2]"
    body = re.sub(r"[ \t]+(\[\d+\])", r" \1", body)

    references = [
        {
            "n": i,
            "source_id": s.id,
            "title": s.title or "Untitled source",
            "url": getattr(s, "url", None),
        }
        for i, s in enumerate(ordered, 1)
    ]
    if references:
        lines = [f"## {heading}", ""]
        for ref in references:
            line = f"{ref['n']}. {ref['title']}"
            if ref["url"]:
                line += f" — <{ref['url']}>"
            lines.append(line)
        body = body.rstrip() + "\n\n" + "\n".join(lines) + "\n"
    return {"markdown": body, "references": references, "unresolved_tokens": unresolved}
