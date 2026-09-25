"""Tests for the JSON storage engine itself: atomic writes, locking, and corruption recovery."""
from __future__ import annotations

import json
import threading

from pydantic import BaseModel

from database.json_store import JsonStore


class Counter(BaseModel):
    value: int = 0
    label: str = "fresh"


def test_creates_a_valid_default_file(tmp_path):
    path = tmp_path / "counter.json"
    assert not path.exists()
    store = JsonStore(path, Counter)
    assert path.exists()
    assert store.read() == Counter(value=0, label="fresh")
    # human-readable: indented, real JSON
    assert json.loads(path.read_text())["label"] == "fresh"


def test_update_mutates_and_persists(tmp_path):
    store = JsonStore(tmp_path / "c.json", Counter)
    store.update(lambda c: setattr(c, "value", c.value + 1))
    store.update(lambda c: setattr(c, "value", c.value + 1))
    assert store.read().value == 2
    # a brand-new JsonStore instance pointed at the same file sees the same data
    reopened = JsonStore(tmp_path / "c.json", Counter)
    assert reopened.read().value == 2


def test_atomic_write_leaves_no_temp_files_behind(tmp_path):
    store = JsonStore(tmp_path / "c.json", Counter)
    store.update(lambda c: setattr(c, "value", 5))
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".c.json.")]
    assert leftovers == []


def test_corrupted_file_resets_to_default_and_keeps_a_backup(tmp_path):
    path = tmp_path / "c.json"
    store = JsonStore(path, Counter)
    store.update(lambda c: setattr(c, "value", 42))
    path.write_text("{ this is not valid json")
    recovered = store.read()
    assert recovered == Counter()  # reset to a fresh, valid default rather than crashing
    assert (tmp_path / "c.json.bak").exists()
    assert "not valid json" in (tmp_path / "c.json.bak").read_text()


def test_schema_violation_also_resets_safely(tmp_path):
    path = tmp_path / "c.json"
    JsonStore(path, Counter)
    path.write_text(json.dumps({"value": "not-an-int", "label": "oops"}))
    store = JsonStore(path, Counter)
    assert store.read() == Counter()


def test_concurrent_updates_from_multiple_threads_never_lose_a_write(tmp_path):
    store = JsonStore(tmp_path / "c.json", Counter)
    n_threads, increments = 8, 25

    def worker():
        for _ in range(increments):
            store.update(lambda c: setattr(c, "value", c.value + 1))

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert store.read().value == n_threads * increments


def test_reset_returns_to_defaults(tmp_path):
    store = JsonStore(tmp_path / "c.json", Counter)
    store.update(lambda c: setattr(c, "value", 99))
    store.reset()
    assert store.read().value == 0
