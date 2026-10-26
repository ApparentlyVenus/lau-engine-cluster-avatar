"""Characters on disk: one tuning file per patient, all in one folder.

The file name (without .json) is the character's id. The web app lists,
edits, creates and deletes them through this module; a session loads its
character from disk when it starts, so edits apply to the next session
without restarting the server.
"""

import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from state_engine.validate import validate_tuning

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class CharacterError(Exception):
    def __init__(self, message: str, status: int = 400, errors: list[str] | None = None):
        super().__init__(message)
        self.status = status
        self.errors = errors or []


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:48]
    return slug or "patient"


def warnings_for(data: dict) -> list[str]:
    """Problems that do not stop the file from loading but matter in a session."""
    out = []
    scenario = data.get("scenario") if isinstance(data.get("scenario"), dict) else {}
    if not str(scenario.get("prompt", "")).strip():
        out.append("Scenario is empty: she will not know why she is here.")
    voice = data.get("voice") if isinstance(data.get("voice"), dict) else {}
    if not str(voice.get("voice_id", "")).strip():
        out.append("No voice_id: she cannot speak until one is set (sessions need --no-tts).")
    return out


class CharacterStore:
    def __init__(self, folder: str | Path, read_only: bool = False):
        self.folder = Path(folder)
        self.read_only = read_only
        if not read_only:
            self.folder.mkdir(parents=True, exist_ok=True)

    def _writable(self):
        if self.read_only:
            raise CharacterError(
                "Editing is turned off on this deployment (its files are read-only). "
                "Edit characters locally and redeploy, or use Export JSON.", 403)

    # --- paths --------------------------------------------------------------

    def path(self, char_id: str) -> Path:
        if not ID_RE.match(char_id or ""):
            raise CharacterError(f"Invalid character id: {char_id!r}", 400)
        return self.folder / f"{char_id}.json"

    def existing_path(self, char_id: str) -> Path:
        p = self.path(char_id)
        if not p.is_file():
            raise CharacterError(f"No character {char_id!r}", 404)
        return p

    # --- read ---------------------------------------------------------------

    def ids(self) -> list[str]:
        return sorted(p.stem for p in self.folder.glob("*.json") if ID_RE.match(p.stem))

    def get(self, char_id: str) -> dict:
        p = self.existing_path(char_id)
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError as e:
            raise CharacterError(f"{p.name} is not valid JSON: {e}", 422)

    def summary(self, char_id: str) -> dict:
        try:
            data = self.get(char_id)
        except CharacterError as e:
            return {"id": char_id, "name": char_id, "age": None, "errors": [str(e)], "warnings": []}
        scenario = data.get("scenario") if isinstance(data.get("scenario"), dict) else {}
        return {
            "id": char_id,
            "name": scenario.get("patient_name") or char_id,
            "age": scenario.get("age"),
            "errors": validate_tuning(data),
            "warnings": warnings_for(data),
        }

    def list(self) -> list[dict]:
        return [self.summary(i) for i in self.ids()]

    # --- write --------------------------------------------------------------

    def save(self, char_id: str, data: dict) -> dict:
        self._writable()
        errors = validate_tuning(data)
        if errors:
            raise CharacterError("Not saved: the character has errors", 422, errors)
        p = self.path(char_id)
        # Write to a temp file and rename, so a crash never leaves half a file.
        fd, tmp = tempfile.mkstemp(dir=self.folder, prefix=".tmp-", suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, p)
        return self.summary(char_id)

    def free_id(self, name: str) -> str:
        base = slugify(name)
        candidate, n = base, 2
        while self.path(candidate).exists():
            candidate, n = f"{base}_{n}", n + 1
        return candidate

    def create(self, data: dict) -> dict:
        name = (data.get("scenario") or {}).get("patient_name") or "patient"
        return self.save(self.free_id(name), data)

    def delete(self, char_id: str) -> None:
        """Moves the file into deleted/ rather than removing it."""
        self._writable()
        p = self.existing_path(char_id)
        if len(self.ids()) <= 1:
            raise CharacterError("Cannot delete the last character", 409)
        trash = self.folder / "deleted"
        trash.mkdir(exist_ok=True)
        shutil.move(str(p), trash / f"{char_id}-{time.strftime('%Y%m%d-%H%M%S')}.json")
