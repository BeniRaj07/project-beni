"""Monthly task manager, backed by data/tasks.json (see database/json_store.py).

Tasks belong to a month (YYYY-MM). Recurring monthly tasks are stored once as a *series*;
ensure_recurring_for_month() materialises one task per month, skipping any (series_id, month)
pair that already exists, so viewing a month any number of times never creates duplicates.
Deleted tasks are soft-deleted (status='deleted') so a recurring instance is not re-created.
"""
from __future__ import annotations

import calendar
import difflib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from config import settings
from database import stores
from database.models import Task, TaskSeries

log = logging.getLogger(__name__)
MAX_TITLE = 200
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class TaskError(ValueError):
    """Validation problem that should be shown to the user."""


def today_local() -> date:
    return datetime.now(settings.tz).date()


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def validate_month(month: str | None) -> str:
    month = (month or "").strip() or month_key(today_local())
    if not _MONTH_RE.match(month):
        raise TaskError(f"'{month}' is not a valid month (expected YYYY-MM)")
    return month


def _clean_title(title: str) -> str:
    title = (title or "").strip()
    if not title:
        raise TaskError("the task needs a title")
    if len(title) > MAX_TITLE:
        raise TaskError(f"the task title is too long (max {MAX_TITLE} characters)")
    return title


def _due_in_month(month: str, day: int | None) -> str | None:
    if not day:
        return None
    y, m = map(int, month.split("-"))
    return date(y, m, min(day, calendar.monthrange(y, m)[1])).isoformat()


def get_task(task_id: int) -> Task | None:
    t = stores.tasks.read().tasks.get(str(task_id))
    return t if (t and t.status != "deleted") else None


def create_task(title: str, *, month: str | None = None, due_date: date | None = None,
                description: str | None = None, recurring_monthly: bool = False) -> Task:
    title = _clean_title(title)
    month = validate_month(month_key(due_date) if due_date else month)
    description = (description or "").strip() or None
    stamp = datetime.now(timezone.utc)
    saved: dict[str, Task] = {}

    def mutate(data):
        series_id = None
        if recurring_monthly:
            sid = data.next_series_id
            data.next_series_id += 1
            data.series[str(sid)] = TaskSeries(id=sid, title=title, description=description,
                                               day_of_month=due_date.day if due_date else None,
                                               start_month=month, active=True, created_at=stamp)
            series_id = sid
        tid = data.next_id
        data.next_id += 1
        task = Task(id=tid, title=title, description=description, month=month,
                   due_date=_due_in_month(month, due_date.day if due_date else None), status="pending",
                   recurrence="monthly" if recurring_monthly else "none", series_id=series_id,
                   created_at=stamp)
        data.tasks[str(tid)] = task
        saved["task"] = task

    stores.tasks.update(mutate)
    task = saved["task"]
    log.info("task_created", extra={"task_id": task.id, "recurring": recurring_monthly, "month": month})
    return task


def ensure_recurring_for_month(month: str) -> int:
    """Create this month's instance of every active recurring series (idempotent)."""
    month = validate_month(month)
    created = {"n": 0}

    def mutate(data):
        existing = {(t.series_id, t.month) for t in data.tasks.values() if t.series_id}
        for s in data.series.values():
            if not s.active or s.start_month > month or (s.id, month) in existing:
                continue
            tid = data.next_id
            data.next_id += 1
            data.tasks[str(tid)] = Task(
                id=tid, title=s.title, description=s.description, month=month,
                due_date=_due_in_month(month, s.day_of_month), status="pending", recurrence="monthly",
                series_id=s.id, created_at=datetime.now(timezone.utc))
            created["n"] += 1

    stores.tasks.update(mutate)
    return created["n"]


def list_tasks(month: str | None = None, status: str | None = None) -> list[Task]:
    """status: None/'all', 'pending', 'completed' or 'overdue'."""
    month = validate_month(month)
    ensure_recurring_for_month(month)
    if status == "overdue":
        return [t for t in overdue_tasks() if t.month == month]
    items = [t for t in stores.tasks.read().tasks.values() if t.month == month and t.status != "deleted"]
    if status in ("pending", "completed"):
        items = [t for t in items if t.status == status]
    items.sort(key=lambda t: (t.status, t.due_date or "9999", t.id))
    return items


def overdue_tasks(today: date | None = None) -> list[Task]:
    today = today or today_local()
    ensure_recurring_for_month(month_key(today))
    items = [t for t in stores.tasks.read().tasks.values()
            if t.status == "pending" and t.due_date is not None and t.due_date < today.isoformat()]
    items.sort(key=lambda t: t.due_date or "")
    return items


@dataclass
class Progress:
    month: str
    total: int
    completed: int
    pending: int
    overdue: int

    @property
    def percent(self) -> int:
        return round(100 * self.completed / self.total) if self.total else 0


def month_progress(month: str | None = None, today: date | None = None) -> Progress:
    month = validate_month(month)
    items = list_tasks(month)
    today = today or today_local()
    done = sum(t.status == "completed" for t in items)
    overdue = sum(t.status == "pending" and t.due_date is not None and t.due_date < today.isoformat() for t in items)
    return Progress(month=month, total=len(items), completed=done, pending=len(items) - done, overdue=overdue)


def find_tasks(query: str, month: str | None = None, status: str | None = "pending") -> list[Task]:
    q = (query or "").strip().lower()
    if not q:
        return []
    if month:
        candidates = list_tasks(month, status)
    else:
        candidates = [t for t in stores.tasks.read().tasks.values() if t.status != "deleted"]
        if status in ("pending", "completed"):
            candidates = [t for t in candidates if t.status == status]
        candidates.sort(key=lambda t: (t.month, t.id), reverse=True)
    exact = [t for t in candidates if q in t.title.lower() or t.title.lower() in q]
    if exact:
        return exact
    words = {w for w in q.split() if len(w) > 2}
    by_word = [t for t in candidates if words & {w for w in t.title.lower().split() if len(w) > 2}]
    if by_word:
        return by_word
    titles = {t.title.lower(): t for t in candidates}
    return [titles[x] for x in difflib.get_close_matches(q, titles.keys(), n=3, cutoff=0.6)]


def set_task_status(task_id: int, status: str) -> Task:
    if status not in ("pending", "completed"):
        raise TaskError("status must be pending or completed")
    found = {"ok": False}

    def mutate(data):
        t = data.tasks.get(str(task_id))
        if t is not None and t.status != "deleted":
            t.status = status
            t.completed_at = datetime.now(timezone.utc) if status == "completed" else None
            found["ok"] = True

    stores.tasks.update(mutate)
    if not found["ok"]:
        raise TaskError(f"task #{task_id} does not exist")
    if status == "completed":
        from services.reminders import cancel_task_reminders
        cancel_task_reminders(task_id)   # a finished task no longer needs its reminder
    log.info("task_status", extra={"task_id": task_id, "status": status})
    return get_task(task_id)  # type: ignore[return-value]


def complete_task(task_id: int) -> Task:
    return set_task_status(task_id, "completed")


def update_task(task_id: int, *, title: str | None = None, description: str | None = None,
                due_date: date | None = None) -> Task:
    task = get_task(task_id)
    if task is None:
        raise TaskError(f"task #{task_id} does not exist")
    new_title = _clean_title(title) if title is not None else task.title
    new_desc = (description.strip() or None) if description is not None else task.description
    new_due = due_date.isoformat() if due_date else task.due_date
    new_month = month_key(due_date) if due_date else task.month

    def mutate(data):
        t = data.tasks[str(task_id)]
        t.title, t.description, t.due_date, t.month = new_title, new_desc, new_due, new_month

    stores.tasks.update(mutate)
    return get_task(task_id)  # type: ignore[return-value]


def delete_task(task_id: int) -> bool:
    """Soft delete; for a recurring task this also stops future months."""
    task = get_task(task_id)
    if task is None:
        return False

    def mutate(data):
        data.tasks[str(task_id)].status = "deleted"
        if task.series_id is not None and str(task.series_id) in data.series:
            data.series[str(task.series_id)].active = False

    stores.tasks.update(mutate)
    from services.reminders import cancel_task_reminders
    cancel_task_reminders(task_id)
    log.info("task_deleted", extra={"task_id": task_id, "recurring": task.recurring})
    return True


# ── daily briefing helpers ───────────────────────────────────────────────────

def tasks_due_on(day: date) -> list[Task]:
    """Pending tasks whose due date is `day`."""
    ensure_recurring_for_month(month_key(day))
    items = [t for t in stores.tasks.read().tasks.values() if t.status == "pending" and t.due_date == day.isoformat()]
    items.sort(key=lambda t: t.id)
    return items


def tasks_completed_on(day: date, tz=None) -> list[Task]:
    """Tasks marked completed on `day` (in the user's local timezone)."""
    tz = tz or settings.tz
    items = [t for t in stores.tasks.read().tasks.values()
            if t.status == "completed" and t.completed_at is not None and t.completed_at.astimezone(tz).date() == day]
    items.sort(key=lambda t: t.completed_at)
    return items
