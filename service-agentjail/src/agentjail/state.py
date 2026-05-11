import json
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock

from agentjail.sandbox.models import StateFile


class StateManager:
    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self._lock = FileLock(str(state_path) + ".lock")

    @contextmanager
    def transaction(self) -> Generator[StateFile, None, None]:
        with self._lock:
            state = self._read()
            yield state
            self._write(state)

    def read(self) -> StateFile:
        with self._lock:
            return self._read()

    def _read(self) -> StateFile:
        if not self._path.exists():
            return StateFile()
        raw = self._path.read_text()
        if not raw.strip():
            return StateFile()
        return StateFile.model_validate(json.loads(raw))

    def _write(self, state: StateFile) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=self._path.parent, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(state.model_dump_json(indent=2))
            os.replace(tmp_path, self._path)
        except BaseException:
            os.unlink(tmp_path)
            raise
