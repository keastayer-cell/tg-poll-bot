import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional


class StateLoadError(RuntimeError):
    """Raised when neither the main state file nor its backup can be read."""


class JsonStateRepository:
    def __init__(self, path: str):
        self.path = Path(path)
        self.backup_path = self.path.with_name(f"{self.path.name}.bak")
        self.recovered_from_backup = False

    @staticmethod
    def _read(path: Path) -> dict:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise ValueError("State root must be a JSON object")
        return data

    def load(self) -> Optional[dict]:
        self.recovered_from_backup = False
        if not self.path.exists():
            return None

        try:
            return self._read(self.path)
        except (OSError, ValueError, json.JSONDecodeError) as primary_error:
            if self.backup_path.exists():
                try:
                    data = self._read(self.backup_path)
                    self.recovered_from_backup = True
                    return data
                except (OSError, ValueError, json.JSONDecodeError) as backup_error:
                    raise StateLoadError(
                        f"Cannot read state or backup: {primary_error}; {backup_error}"
                    ) from backup_error
            raise StateLoadError(f"Cannot read state: {primary_error}") from primary_error

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        if self.path.exists():
            try:
                self._read(self.path)
            except (OSError, ValueError, json.JSONDecodeError):
                pass
            else:
                shutil.copy2(self.path, self.backup_path)
                os.chmod(self.backup_path, 0o600)

        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(data, temporary_file, ensure_ascii=False)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.path)
            temporary_path = None

            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
