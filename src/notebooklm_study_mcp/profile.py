"""Local study profile: your reading style, an example quiz, and learner context.

Stored as JSON at ``$NOTEBOOKLM_STUDY_HOME/study_profile.json`` (default
``~/.notebooklm-study/``). The directory is created 0700 and the file written 0600
via an atomic replace, so a crash never leaves a half-written profile. No
credentials are ever stored here.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

#: Hard caps keep a pasted example from bloating every tool response.
FIELD_LIMITS: dict[str, int] = {
    "reading_style": 4_000,
    "quiz_example": 20_000,
    "learner_context": 4_000,
    "quiz_preferences": 4_000,
}


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


def default_home() -> Path:
    env = os.environ.get("NOTEBOOKLM_STUDY_HOME")
    return Path(env).expanduser() if env else Path.home() / ".notebooklm-study"


class ProfileStore:
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or default_home()
        self.path = self.home / "study_profile.json"

    def load(self) -> StudyProfile:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return StudyProfile()
        except (OSError, json.JSONDecodeError):
            return StudyProfile()
        known = {f.name for f in fields(StudyProfile)}
        return StudyProfile(**{k: str(v) for k, v in raw.items() if k in known})

    def update(self, **changes: str | None) -> StudyProfile:
        """Merge non-None fields into the stored profile and save it."""
        profile = self.load()
        for name, value in changes.items():
            if value is None:
                continue
            if name not in FIELD_LIMITS:
                raise ValueError(f"Unknown profile field: {name}")
            value = value.strip()
            if len(value) > FIELD_LIMITS[name]:
                raise ValueError(
                    f"{name} is too long ({len(value)} chars; max {FIELD_LIMITS[name]})."
                )
            setattr(profile, name, value)
        self._save(profile)
        return profile

    def _save(self, profile: StudyProfile) -> None:
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.home.chmod(0o700)
        except OSError:
            pass  # e.g. Windows; directory still lives in the user profile
        fd, tmp = tempfile.mkstemp(dir=self.home, prefix=".profile-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(profile.to_dict(), fh, ensure_ascii=False, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
