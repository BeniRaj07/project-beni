"""Pydantic schemas for every JSON file in data/. Pydantic gives us three things for free:

* **parsing** — a `datetime` field accepts an ISO-8601 string from disk and becomes a real,
  timezone-aware `datetime` object in Python;
* **serialization** — writing it back out produces a clean ISO-8601 string again;
* **validation** — a field with the wrong type or a missing required value raises immediately,
  which is exactly what lets json_store.py detect a corrupted file and reset it safely.

Each `...File` model is the *whole contents* of one JSON file; a `JsonStore[XFile]` wraps it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["en", "ne"]
Recurrence = Literal["none", "daily", "weekly", "monthly"]


# ── conversations.json ──────────────────────────────────────────────────────

class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    language: Language = "en"
    timestamp: datetime


class Conversation(BaseModel):
    id: int
    title: str = "New chat"
    created_at: datetime
    updated_at: datetime
    language: Language = "en"          # last language used, so reopening guesses correctly
    last_city: Optional[str] = None    # last-discussed city, for weather follow-ups
    pending: Optional[dict] = None     # an in-flight follow-up question ("What time?"), if any
    messages: list[Message] = Field(default_factory=list)


class ConversationsFile(BaseModel):
    next_id: int = 1
    conversations: dict[str, Conversation] = Field(default_factory=dict)


# ── reminders.json ───────────────────────────────────────────────────────────

class Reminder(BaseModel):
    id: int
    title: str
    next_due_at: datetime          # UTC, timezone-aware
    timezone: str                  # IANA name, e.g. Asia/Kathmandu
    local_time: str                # HH:MM wall-clock time in that timezone
    recurrence: Recurrence = "none"
    anchor_day: Optional[int] = None       # day-of-month anchor for monthly reminders
    status: Literal["active", "done", "cancelled"] = "active"
    task_id: Optional[int] = None          # linked task, if any
    created_at: datetime
    updated_at: datetime
    last_notified_at: Optional[datetime] = None    # wall-clock time the last notification fired
    last_notified_due_at: Optional[datetime] = None  # which occurrence that was (dedupe recurring)

    @property
    def local_due(self) -> datetime:
        return self.next_due_at.astimezone(ZoneInfo(self.timezone))


class NotificationRecord(BaseModel):
    id: int
    reminder_id: int
    title: str
    due_at: datetime       # the occurrence that fired (UTC)
    fired_at: datetime
    seen: bool = False


class RemindersFile(BaseModel):
    next_id: int = 1
    next_notification_id: int = 1
    reminders: dict[str, Reminder] = Field(default_factory=dict)
    notifications: list[NotificationRecord] = Field(default_factory=list)


# ── tasks.json ───────────────────────────────────────────────────────────────

class TaskSeries(BaseModel):
    """A recurring-monthly task template; ensure_recurring_for_month() materialises one Task
    per month from each active series, without ever duplicating an existing month's instance."""
    id: int
    title: str
    description: Optional[str] = None
    day_of_month: Optional[int] = None
    start_month: str            # YYYY-MM
    active: bool = True
    created_at: datetime


class Task(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    month: str                              # YYYY-MM this instance belongs to
    due_date: Optional[str] = None          # YYYY-MM-DD (kept as a string: compared lexicographically)
    status: Literal["pending", "completed", "deleted"] = "pending"
    recurrence: Literal["none", "monthly"] = "none"    # mirrors series_id, for a readable JSON file
    series_id: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    @property
    def recurring(self) -> bool:
        return self.series_id is not None


class TasksFile(BaseModel):
    next_id: int = 1
    next_series_id: int = 1
    tasks: dict[str, Task] = Field(default_factory=dict)
    series: dict[str, TaskSeries] = Field(default_factory=dict)


# ── settings.json ────────────────────────────────────────────────────────────

class UserSettings(BaseModel):
    """User-editable preferences (a settings.json belt over .env's fixed defaults)."""
    model_config = ConfigDict(validate_assignment=True)

    default_language: Language = "en"
    timezone: str = "Asia/Kathmandu"
    voice_engine: Literal["elevenlabs", "gemini", "edge"] = "elevenlabs"
    auto_play: bool = True
    theme: Literal["dark", "light"] = "dark"
    briefing_on_open: bool = True
