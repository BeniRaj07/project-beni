"""Reminder storage and scheduling logic, backed by data/reminders.json (see database/json_store.py).

* Times are entered as local wall-clock time in the user's timezone (default Asia/Kathmandu)
  and stored as UTC, together with the timezone name.
* Recurring reminders keep their wall-clock time: a "monthly on the 31st" reminder fires on the
  last day of shorter months and returns to the 31st afterwards (anchor_day).
* fire_due_reminders() is idempotent: every occurrence records a NotificationRecord keyed by
  (reminder_id, due_at) before the reminder is advanced or closed, all inside one locked
  read-modify-write, so an occurrence can never be notified twice even if the scheduler thread and
  a chat request race each other.
"""
from __future__ import annotations

import calendar
import difflib
import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from config import settings
from database import stores
from database.models import NotificationRecord, Reminder

log = logging.getLogger(__name__)
RECURRENCES = ("none", "daily", "weekly", "monthly")
MAX_TITLE = 200


class ReminderError(ValueError):
    """Validation problem that should be shown to the user."""


def to_local(d: date, t: time, tz_name: str) -> datetime:
    return datetime.combine(d, t).replace(tzinfo=ZoneInfo(tz_name))


def add_months(local_dt: datetime, months: int, anchor_day: int) -> datetime:
    month_index = local_dt.month - 1 + months
    year, month = local_dt.year + month_index // 12, month_index % 12 + 1
    day = min(anchor_day, calendar.monthrange(year, month)[1])
    return local_dt.replace(year=year, month=month, day=day)


def next_occurrence(local_dt: datetime, recurrence: str, anchor_day: int | None = None) -> datetime:
    """The occurrence after local_dt, computed in local wall-clock time."""
    tz = local_dt.tzinfo
    naive = local_dt.replace(tzinfo=None)
    if recurrence == "daily":
        nxt = naive + timedelta(days=1)
    elif recurrence == "weekly":
        nxt = naive + timedelta(weeks=1)
    elif recurrence == "monthly":
        nxt = add_months(naive, 1, anchor_day or local_dt.day)
    else:
        raise ReminderError(f"'{recurrence}' reminders do not repeat")
    return nxt.replace(tzinfo=tz)


def _validate(title: str, recurrence: str, tz_name: str) -> str:
    title = (title or "").strip()
    if not title:
        raise ReminderError("the reminder needs a title")
    if len(title) > MAX_TITLE:
        raise ReminderError(f"the reminder title is too long (max {MAX_TITLE} characters)")
    if recurrence not in RECURRENCES:
        raise ReminderError(f"recurrence must be one of {', '.join(RECURRENCES)}")
    try:
        ZoneInfo(tz_name)
    except Exception as e:  # noqa: BLE001
        raise ReminderError(f"unknown timezone '{tz_name}'") from e
    return title


def _first_future(local_dt: datetime, recurrence: str, anchor_day: int | None, now: datetime) -> datetime:
    """For recurring reminders whose start is in the past, roll forward to the next future occurrence."""
    while local_dt <= now and recurrence != "none":
        local_dt = next_occurrence(local_dt, recurrence, anchor_day)
    return local_dt


def create_reminder(title: str, local_date: date, local_time: time, recurrence: str = "none",
                    tz_name: str | None = None, task_id: int | None = None,
                    now: datetime | None = None) -> Reminder:
    tz_name = tz_name or settings.timezone
    title = _validate(title, recurrence, tz_name)
    now = now or datetime.now(timezone.utc)
    local_dt = to_local(local_date, local_time, tz_name)
    anchor = local_date.day if recurrence == "monthly" else None
    if recurrence == "none" and local_dt <= now:
        raise ReminderError("that time is already in the past")
    local_dt = _first_future(local_dt, recurrence, anchor, now)
    stamp = datetime.now(timezone.utc)

    saved: dict[str, Reminder] = {}

    def mutate(data):
        rid = data.next_id
        data.next_id += 1
        r = Reminder(id=rid, title=title, next_due_at=local_dt, timezone=tz_name,
                     local_time=local_time.strftime("%H:%M"), recurrence=recurrence, anchor_day=anchor,
                     status="active", task_id=task_id, created_at=stamp, updated_at=stamp)
        data.reminders[str(rid)] = r
        saved["reminder"] = r

    stores.reminders.update(mutate)
    r = saved["reminder"]
    log.info("reminder_created", extra={"reminder_id": r.id, "recurrence": recurrence})
    return r


def get_reminder(reminder_id: int) -> Reminder | None:
    return stores.reminders.read().reminders.get(str(reminder_id))


def list_reminders(status: str | None = "active", on_local_date: date | None = None,
                   tz_name: str | None = None, limit: int = 100) -> list[Reminder]:
    items = list(stores.reminders.read().reminders.values())
    if status:
        items = [r for r in items if r.status == status]
    items.sort(key=lambda r: r.next_due_at)
    if on_local_date:
        tz = ZoneInfo(tz_name or settings.timezone)
        items = [r for r in items if r.next_due_at.astimezone(tz).date() == on_local_date]
    return items[:limit]


def find_reminders(query: str, status: str | None = "active") -> list[Reminder]:
    """Fuzzy title search used when the user says e.g. 'delete my assignment reminder'."""
    q = (query or "").strip().lower()
    if not q:
        return []
    candidates = list_reminders(status=status, limit=500)
    exact = [r for r in candidates if q in r.title.lower() or r.title.lower() in q]
    if exact:
        return exact
    words = {w for w in q.split() if len(w) > 2}
    by_word = [r for r in candidates if words & {w for w in r.title.lower().split() if len(w) > 2}]
    if by_word:
        return by_word
    titles = {r.title.lower(): r for r in candidates}
    return [titles[t] for t in difflib.get_close_matches(q, titles.keys(), n=3, cutoff=0.6)]


def update_reminder(reminder_id: int, *, title: str | None = None, local_date: date | None = None,
                    local_time: time | None = None, recurrence: str | None = None,
                    now: datetime | None = None) -> Reminder:
    current = get_reminder(reminder_id)
    if current is None:
        raise ReminderError(f"reminder #{reminder_id} does not exist")
    new_title = _validate(title if title is not None else current.title,
                          recurrence or current.recurrence, current.timezone)
    new_recurrence = recurrence or current.recurrence
    local = current.local_due
    new_date = local_date or local.date()
    new_time = local_time or local.time().replace(second=0, microsecond=0)
    now = now or datetime.now(timezone.utc)
    local_dt = to_local(new_date, new_time, current.timezone)
    anchor = new_date.day if new_recurrence == "monthly" else None
    if new_recurrence == "none" and local_dt <= now:
        raise ReminderError("the new time is already in the past")
    local_dt = _first_future(local_dt, new_recurrence, anchor, now)

    def mutate(data):
        r = data.reminders[str(reminder_id)]
        r.title, r.next_due_at, r.local_time = new_title, local_dt, new_time.strftime("%H:%M")
        r.recurrence, r.anchor_day, r.status = new_recurrence, anchor, "active"
        r.updated_at = datetime.now(timezone.utc)

    stores.reminders.update(mutate)
    log.info("reminder_updated", extra={"reminder_id": reminder_id})
    return get_reminder(reminder_id)  # type: ignore[return-value]


def set_reminder_status(reminder_id: int, status: str) -> Reminder:
    if status not in ("active", "done", "cancelled"):
        raise ReminderError("status must be active, done or cancelled")
    found = {"ok": False}

    def mutate(data):
        r = data.reminders.get(str(reminder_id))
        if r is not None:
            r.status, r.updated_at = status, datetime.now(timezone.utc)
            found["ok"] = True

    stores.reminders.update(mutate)
    if not found["ok"]:
        raise ReminderError(f"reminder #{reminder_id} does not exist")
    return get_reminder(reminder_id)  # type: ignore[return-value]


def delete_reminder(reminder_id: int) -> bool:
    removed = {"ok": False}

    def mutate(data):
        removed["ok"] = data.reminders.pop(str(reminder_id), None) is not None

    stores.reminders.update(mutate)
    log.info("reminder_deleted", extra={"reminder_id": reminder_id, "deleted": removed["ok"]})
    return removed["ok"]


def cancel_task_reminders(task_id: int) -> None:
    def mutate(data):
        for r in data.reminders.values():
            if r.task_id == task_id and r.status == "active":
                r.status, r.updated_at = "cancelled", datetime.now(timezone.utc)

    stores.reminders.update(mutate)


# ── scheduling ───────────────────────────────────────────────────────────────

def fire_due_reminders(now: datetime | None = None) -> list[NotificationRecord]:
    """Record a notification for every reminder that is due, then advance or close it.
    Safe to call repeatedly or concurrently: the whole check happens inside one locked
    read-modify-write, so each occurrence produces exactly one notification."""
    now = now or datetime.now(timezone.utc)
    fired: list[NotificationRecord] = []

    def mutate(data):
        due = sorted((r for r in data.reminders.values() if r.status == "active" and r.next_due_at <= now),
                    key=lambda r: r.next_due_at)
        for r in due:
            due_at = r.next_due_at
            # dedupe: skip if this exact occurrence already produced a notification
            if r.last_notified_due_at is not None and r.last_notified_due_at == due_at:
                continue
            nid = data.next_notification_id
            data.next_notification_id += 1
            note = NotificationRecord(id=nid, reminder_id=r.id, title=r.title, due_at=due_at, fired_at=now)
            data.notifications.append(note)
            fired.append(note)
            r.last_notified_at, r.last_notified_due_at = now, due_at
            if r.recurrence == "none":
                r.status = "done"
            else:
                # Skip occurrences missed while the app was closed: notify once, jump to the future
                r.next_due_at = _first_future(r.local_due, r.recurrence, r.anchor_day, now)
            r.updated_at = now

    stores.reminders.update(mutate)
    for n in fired:
        log.info("reminder_fired", extra={"reminder_id": n.reminder_id, "due_at": n.due_at.isoformat()})
    return fired


def pop_unseen_notifications() -> list[NotificationRecord]:
    """Notifications not yet shown in the UI; marks them as seen (so each pops up once)."""
    unseen: list[NotificationRecord] = []

    def mutate(data):
        for n in data.notifications:
            if not n.seen:
                n.seen = True
                unseen.append(n)

    stores.reminders.update(mutate)
    return unseen


def recent_notifications(limit: int = 10) -> list[NotificationRecord]:
    items = sorted(stores.reminders.read().notifications, key=lambda n: n.fired_at, reverse=True)
    return items[:limit]
