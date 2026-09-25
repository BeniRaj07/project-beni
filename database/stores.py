"""The four JSON stores the app uses, and where they live on disk.

`init_stores()` creates data/*.json (with valid empty contents) the first time the app runs — call
it once at start-up. `set_data_dir()` repoints every store at a fresh folder; the tests use it to
get a clean, isolated data directory per test.
"""
from __future__ import annotations

from pathlib import Path

from config import settings
from database.json_store import JsonStore
from database.models import ConversationsFile, RemindersFile, TasksFile, UserSettings

conversations: JsonStore[ConversationsFile]
reminders: JsonStore[RemindersFile]
tasks: JsonStore[TasksFile]
user_settings: JsonStore[UserSettings]


def _build(data_dir: Path) -> None:
    global conversations, reminders, tasks, user_settings
    conversations = JsonStore(data_dir / "conversations.json", ConversationsFile)
    reminders = JsonStore(data_dir / "reminders.json", RemindersFile)
    tasks = JsonStore(data_dir / "tasks.json", TasksFile)
    user_settings = JsonStore(data_dir / "settings.json", UserSettings)


def set_data_dir(data_dir: str | Path) -> None:
    """Point every store at `data_dir`, creating the four JSON files there if missing."""
    _build(Path(data_dir))


def init_stores() -> None:
    """Idempotent: safe to call every time the app starts. The JsonStore constructor already
    creates its file if missing, so this just makes the intent explicit at the call site."""
    _build(settings.data_dir)


# Build the default (settings.data_dir) stores immediately, so `from database.stores import reminders`
# works without an explicit init_stores() call (handy for scripts and tests); init_stores()/
# set_data_dir() simply rebuild them, and every module that imported `stores` reads through the
# module's current globals via `stores.reminders` rather than caching the object directly.
_build(settings.data_dir)
