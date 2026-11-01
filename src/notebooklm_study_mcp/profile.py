"""Local study profiles: reading style, example quiz and learner context, per subject.

One file, ``study_profile.json``, holds any number of named profiles (``default``,
``biology``, ``law`` ...) plus which notebook uses which profile. A notebook without an
assignment uses ``default``. Files written by v1.0 (a single flat profile) are migrated
transparently into ``default``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .storage import default_home, read_json, write_json

#: Hard caps keep a pasted example from bloating every tool response.
FIELD_LIMITS: dict[str, int] = {
    "reading_style": 4_000,
    "quiz_example": 20_000,
    "learner_context": 4_000,
    "quiz_preferences": 4_000,
}
DEFAULT = "default"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9 _-]{0,39}$")
MAX_PROFILES = 50


@dataclass
class StudyProfile:
    reading_style: str = ""
    """How you like material written, e.g. 'short sections, bullet points, bold key terms,
    one concrete example per concept, plain English, end with a 3-line recap'."""

    quiz_example: str = ""
    """A sample quiz (questions + answers) whose format, tone and difficulty to copy."""

    learner_context: str = ""
    """Who is studying and why: level, background, exam/goal, deadline."""

    quiz_preferences: str = ""
    """e.g. '10 questions, mix of MCQ and short answer, explain every answer'."""

    def is_empty(self) -> bool:
        return not any(getattr(self, f.name).strip() for f in fields(self))

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> StudyProfile:
        if not isinstance(raw, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: str(v) for k, v in raw.items() if k in known})


def normalize_name(name: str | None) -> str:
    name = (name or DEFAULT).strip().lower()
    if not _NAME_RE.match(name):
        raise ValueError(
            "Profile names are 1-40 characters: lowercase letters, digits, space, '_' or '-'."
        )
    return name


class ProfileStore:
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or default_home()
        self.path = self.home / "study_profile.json"

    # -- raw document -------------------------------------------------------
    def _doc(self) -> dict[str, Any]:
        raw = read_json(self.path)
        if "profiles" not in raw:  # v1 flat file -> migrate into "default"
            legacy = StudyProfile.from_dict(raw)
            raw = {"profiles": {} if legacy.is_empty() else {DEFAULT: legacy.to_dict()}}
        raw.setdefault("profiles", {})
        raw.setdefault("notebook_profiles", {})
        raw["version"] = 2
        return raw

    # -- queries ------------------------------------------------------------
    def load(self, name: str | None = None) -> StudyProfile:
        return StudyProfile.from_dict(self._doc()["profiles"].get(normalize_name(name)))

    def resolve(self, notebook_id: str | None) -> tuple[str, StudyProfile]:
        """Profile name and content used for a notebook (falls back to ``default``)."""
        doc = self._doc()
        name = doc["notebook_profiles"].get(notebook_id or "", DEFAULT)
        if name not in doc["profiles"]:
            name = DEFAULT
        return name, StudyProfile.from_dict(doc["profiles"].get(name))

    def names(self) -> list[str]:
        return sorted(self._doc()["profiles"])

    def assignments(self) -> dict[str, str]:
        return dict(self._doc()["notebook_profiles"])

    # -- updates ------------------------------------------------------------
    def update(
        self,
        profile: str | None = DEFAULT,
        *,
        assign_notebooks: list[str] | None = None,
        **changes: str | None,
    ) -> StudyProfile:
        """Merge non-None fields into a named profile, optionally assigning notebooks."""
        name = normalize_name(profile)
        doc = self._doc()
        if name not in doc["profiles"] and len(doc["profiles"]) >= MAX_PROFILES:
            raise ValueError(f"Too many profiles (max {MAX_PROFILES}).")
        current = StudyProfile.from_dict(doc["profiles"].get(name))
        for field_name, value in changes.items():
            if value is None:
                continue
            if field_name not in FIELD_LIMITS:
                raise ValueError(f"Unknown profile field: {field_name}")
            value = value.strip()
            if len(value) > FIELD_LIMITS[field_name]:
                raise ValueError(
                    f"{field_name} is too long ({len(value)} chars; "
                    f"max {FIELD_LIMITS[field_name]})."
                )
            setattr(current, field_name, value)
        doc["profiles"][name] = current.to_dict()
        for notebook_id in assign_notebooks or []:
            notebook_id = notebook_id.strip()
            if not notebook_id or len(notebook_id) > 200:
                raise ValueError("Invalid notebook ID in assign_to_notebooks.")
            doc["notebook_profiles"][notebook_id] = name
        write_json(self.path, doc)
        return current
