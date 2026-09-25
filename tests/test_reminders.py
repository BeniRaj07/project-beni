from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from scheduler.reminder_scheduler import check_due_reminders
from services import reminders
from services.reminders import ReminderError, add_months, next_occurrence

KTM = ZoneInfo("Asia/Kathmandu")
UTC = timezone.utc
JAN1 = datetime(2026, 1, 1, tzinfo=UTC)


def test_create_and_retrieve_reminder():
    r = reminders.create_reminder("Submit assignment", date(2026, 9, 25), time(20, 0), now=datetime(2026, 9, 24, tzinfo=UTC))
    saved = reminders.get_reminder(r.id)
    assert saved.title == "Submit assignment" and saved.status == "active" and saved.recurrence == "none"
    assert [x.id for x in reminders.list_reminders()] == [r.id]


def test_timezone_conversion_kathmandu_to_utc():
    # Kathmandu is UTC+05:45, so 08:00 local is 02:15 UTC
    r = reminders.create_reminder("Class", date(2026, 9, 25), time(8, 0), tz_name="Asia/Kathmandu", now=JAN1)
    assert r.next_due_at == datetime(2026, 9, 25, 2, 15, tzinfo=UTC)
    assert r.local_due.hour == 8 and r.local_due.utcoffset().total_seconds() == 5 * 3600 + 45 * 60


def test_other_timezone_is_respected():
    r = reminders.create_reminder("Call", date(2026, 9, 25), time(9, 0), tz_name="America/New_York", now=JAN1)
    assert r.next_due_at == datetime(2026, 9, 25, 13, 0, tzinfo=UTC)   # EDT = UTC-4


def test_one_time_reminder_in_the_past_is_rejected():
    with pytest.raises(ReminderError, match="past"):
        reminders.create_reminder("Too late", date(2026, 1, 1), time(0, 0), now=datetime(2026, 6, 1, tzinfo=UTC))


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_invalid_titles_are_rejected(title):
    with pytest.raises(ReminderError):
        reminders.create_reminder(title, date(2026, 9, 25), time(8, 0), now=JAN1)


def test_monthly_recurrence_clamps_to_month_end_and_returns_to_anchor():
    start = datetime(2026, 1, 31, 9, 0, tzinfo=KTM)
    feb = next_occurrence(start, "monthly", 31)
    mar = next_occurrence(feb, "monthly", 31)
    assert (feb.month, feb.day) == (2, 28) and (mar.month, mar.day) == (3, 31)
    assert add_months(datetime(2028, 1, 31), 1, 31).day == 29   # leap year


def test_daily_and_weekly_recurrence():
    start = datetime(2026, 9, 24, 7, 0, tzinfo=KTM)
    assert next_occurrence(start, "daily").day == 25
    assert next_occurrence(start, "weekly").day == 1 and next_occurrence(start, "weekly").month == 10


def test_monthly_rent_reminder_first_of_every_month():
    r = reminders.create_reminder("Pay rent", date(2026, 10, 1), time(9, 0), "monthly", now=datetime(2026, 9, 24, tzinfo=UTC))
    assert r.anchor_day == 1
    fired = reminders.fire_due_reminders(now=datetime(2026, 10, 1, 4, 0, tzinfo=UTC))   # 09:45 KTM
    assert len(fired) == 1
    after = reminders.get_reminder(r.id)
    assert after.status == "active" and (after.local_due.month, after.local_due.day, after.local_due.hour) == (11, 1, 9)


def test_recurring_start_in_the_past_rolls_forward():
    r = reminders.create_reminder("Standup", date(2026, 9, 1), time(9, 0), "daily",
                                  now=datetime(2026, 9, 24, 12, 0, tzinfo=UTC))
    assert r.local_due.date() == date(2026, 9, 25)


def test_due_reminder_fires_exactly_once():
    r = reminders.create_reminder("Exam", date(2026, 9, 25), time(8, 0), now=datetime(2026, 9, 24, tzinfo=UTC))
    due_time = datetime(2026, 9, 25, 3, 0, tzinfo=UTC)
    assert len(reminders.fire_due_reminders(now=due_time)) == 1
    assert reminders.fire_due_reminders(now=due_time) == []          # no duplicate
    assert reminders.get_reminder(r.id).status == "done"
    popped = reminders.pop_unseen_notifications()
    assert [n.title for n in popped] == ["Exam"]
    assert reminders.pop_unseen_notifications() == []                # shown in the UI only once


def test_not_yet_due_reminder_does_not_fire():
    reminders.create_reminder("Later", date(2026, 9, 25), time(20, 0), now=datetime(2026, 9, 24, tzinfo=UTC))
    assert reminders.fire_due_reminders(now=datetime(2026, 9, 25, 3, 0, tzinfo=UTC)) == []


def test_missed_recurring_occurrences_notify_once_then_jump_to_future():
    r = reminders.create_reminder("Water plants", date(2026, 9, 1), time(7, 0), "daily", now=datetime(2026, 8, 31, tzinfo=UTC))
    fired = reminders.fire_due_reminders(now=datetime(2026, 9, 10, 12, 0, tzinfo=UTC))   # app was closed 9 days
    assert len(fired) == 1
    assert reminders.get_reminder(r.id).local_due.date() == date(2026, 9, 11)


def test_scheduler_job_uses_same_logic(monkeypatch):
    monkeypatch.setattr(reminders, "fire_due_reminders", lambda: ["n1", "n2"])
    assert check_due_reminders() == 2


def test_scheduler_job_survives_errors(monkeypatch):
    def boom():
        raise RuntimeError("db locked")
    monkeypatch.setattr(reminders, "fire_due_reminders", boom)
    assert check_due_reminders() == 0


def test_find_update_complete_and_delete():
    r = reminders.create_reminder("Submit assignment", date(2026, 9, 25), time(20, 0), now=JAN1)
    reminders.create_reminder("Pay rent", date(2026, 10, 1), time(9, 0), "monthly", now=JAN1)
    assert [x.id for x in reminders.find_reminders("assignment")] == [r.id]
    moved = reminders.update_reminder(r.id, local_time=time(21, 30), now=JAN1)
    assert moved.local_due.hour == 21 and moved.local_due.minute == 30
    assert reminders.set_reminder_status(r.id, "done").status == "done"
    assert reminders.delete_reminder(r.id) and reminders.get_reminder(r.id) is None
    assert not reminders.delete_reminder(9999)


def test_list_reminders_for_a_specific_day():
    reminders.create_reminder("Today thing", date(2026, 9, 24), time(18, 0), now=datetime(2026, 9, 24, 1, 0, tzinfo=UTC))
    reminders.create_reminder("Tomorrow thing", date(2026, 9, 25), time(18, 0), now=datetime(2026, 9, 24, 1, 0, tzinfo=UTC))
    todays = reminders.list_reminders(on_local_date=date(2026, 9, 24), tz_name="Asia/Kathmandu")
    assert [x.title for x in todays] == ["Today thing"]
