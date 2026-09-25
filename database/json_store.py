"""A small, safe JSON file store: one file per collection (reminders, tasks, conversations, settings).

Why JSON instead of SQLite? This is a single-user university project; plain JSON files are easy to
open, read and demonstrate, and plenty robust for a database this size. Correctness is guarded by:

* **Atomic writes** — every write goes to a temp file in the same directory, fsync'd, then swapped
  into place with os.replace(), which is atomic on POSIX and Windows. A crash mid-write can never
  leave a half-written file.
* **Two-level locking** — an in-process threading.RLock (Gradio runs handlers in a thread pool, and
  the reminder scheduler runs in its own background thread) plus a cross-process file lock via
  `filelock`, so a second process (e.g. `scripts/check_setup.py` running at the same time) cannot
  interleave with the running app.
* **Schema validation** — every read is parsed through a Pydantic model (see database/models.py).
  A corrupted or hand-edited file that fails validation is logged and the store resets to a fresh,
  valid default rather than crashing the app.
* **Pretty, human-readable output** — indent=2, UTF-8, so the files are easy to inspect for a demo.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Callable, Generic, TypeVar

from filelock import FileLock
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class JsonStore(Generic[T]):
    """A JSON file whose contents are always a validated instance of `model`."""

    def __init__(self, path: Path, model: type[T]):
        self.path = Path(path)
        self.model = model
        self._lock = threading.RLock()                       # same-process (threads) safety
        self._file_lock = FileLock(str(self.path) + ".lock")  # cross-process safety
        self._ensure_file()

    # ── low-level file access (always call under self._lock) ───────────────

    def _default(self) -> T:
        return self.model()  # every field has a default, so an empty file is always valid

    def _atomic_write(self, data: T) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), prefix=f".{self.path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data.model_dump_json(indent=2))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, self.path)  # atomic on POSIX and Windows
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _ensure_file(self) -> None:
        with self._lock, self._file_lock:
            if not self.path.exists():
                self._atomic_write(self._default())

    def _read_locked(self) -> T:
        """Read + validate. Called while both locks are already held."""
        try:
            raw = self.path.read_text(encoding="utf-8")
            return self.model.model_validate_json(raw)
        except FileNotFoundError:
            data = self._default()
            self._atomic_write(data)
            return data
        except (json.JSONDecodeError, ValidationError) as e:
            # Never crash the app over a corrupted file: log it, keep a .bak copy, start fresh.
            log.error("json_store_corrupt", extra={"path": str(self.path), "error": str(e)})
            try:
                self.path.replace(self.path.with_suffix(self.path.suffix + ".bak"))
            except OSError:
                pass
            data = self._default()
            self._atomic_write(data)
            return data

    # ── public API ───────────────────────────────────────────────────────

    def read(self) -> T:
        """Return a validated copy of the current contents."""
        with self._lock, self._file_lock:
            return self._read_locked()

    def update(self, mutator: Callable[[T], None]) -> T:
        """Read-modify-write under lock: `mutator` mutates the model in place. Returns the saved model.
        This is the ONLY safe way to change a store — it prevents the scheduler thread and a chat
        request from ever interleaving a lost update."""
        with self._lock, self._file_lock:
            data = self._read_locked()
            mutator(data)
            self._atomic_write(data)
            return data

    def reset(self) -> None:
        """Used by tests to point at a clean slate."""
        with self._lock, self._file_lock:
            self._atomic_write(self._default())
