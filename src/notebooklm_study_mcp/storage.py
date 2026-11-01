"""Private local JSON storage for study data (profiles, progress).

Files live in ``$NOTEBOOKLM_STUDY_HOME`` (default ``~/.notebooklm-study``): the
directory is 0700, files are 0600 and written atomically (temp file + replace), so a
crash never leaves a half-written file. No credentials are ever stored here.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def default_home() -> Path:
    env = os.environ.get("NOTEBOOKLM_STUDY_HOME")
    return Path(env).expanduser() if env else Path.home() / ".notebooklm-study"


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    home = path.parent
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        home.chmod(0o700)
    except OSError:
        pass  # e.g. Windows; the directory still lives in the user profile
    fd, tmp = tempfile.mkstemp(dir=home, prefix=f".{path.stem}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
