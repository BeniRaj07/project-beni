from datetime import date, datetime, time, timezone

import pytest

from services import reminders, tasks
from services.tasks import TaskError


def test_create_and_complete_monthly_task():
    t = tasks.create_task("Complete project report", month="2026-09")
    assert t.status == "pending" and t.month == "2026-09"
    done = tasks.complete_task(t.id)
    assert done.status == "completed" and done.completed_at
    assert [x.title for x in tasks.list_tasks("2026-09", "completed")] == ["Complete project report"]
    assert tasks.list_tasks("2026-09", "pending") == []


def test_due_date_decides_the_month():
    t = tasks.create_task("Renew passport", month="2026-09", due_date=date(2026, 11, 3))
    assert t.month == "2026-11" and t.due_date == "2026-11-03"


def test_recurring_monthly_task_is_never_duplicated():
    tasks.create_task("Pay electricity bill", month="2026-09", due_date=date(2026, 9, 15), recurring_monthly=True)
    for _ in range(3):   # viewing a month repeatedly must not create copies
        tasks.list_tasks("2026-10")
        tasks.ensure_recurring_for_month("2026-10")
    october = tasks.list_tasks("2026-10")
    assert [(x.title, x.due_date) for x in october] == [("Pay electricity bill", "2026-10-15")]
    assert len(tasks.list_tasks("2026-09")) == 1
    assert tasks.list_tasks("2026-08") == []   # series does not go back in time


def test_recurring_task_due_day_is_clamped():
    tasks.create_task("Month-end report", month="2026-01", due_date=date(2026, 1, 31), recurring_monthly=True)
    assert tasks.list_tasks("2026-02")[0].due_date == "2026-02-28"


def test_deleting_recurring_task_stops_future_months():
    t = tasks.create_task("Gym fee", month="2026-09", recurring_monthly=True)
    assert tasks.delete_task(t.id)
    assert tasks.list_tasks("2026-09") == [] and tasks.list_tasks("2026-10") == []


def test_overdue_and_progress():
    tasks.create_task("Old task", due_date=date(2026, 9, 10))
    tasks.create_task("Future task", due_date=date(2026, 9, 28))
    done = tasks.create_task("Done task", due_date=date(2026, 9, 5))
    tasks.complete_task(done.id)
    today = date(2026, 9, 24)
    assert [x.title for x in tasks.overdue_tasks(today)] == ["Old task"]
    p = tasks.month_progress("2026-09", today)
    assert (p.total, p.completed, p.pending, p.overdue, p.percent) == (3, 1, 2, 1, 33)


def test_find_update_and_invalid_input():
    t = tasks.create_task("Project report", month="2026-09")
    assert [x.id for x in tasks.find_tasks("report")] == [t.id]
    assert tasks.update_task(t.id, title="Final project report").title == "Final project report"
    with pytest.raises(TaskError):
        tasks.create_task("   ")
    with pytest.raises(TaskError):
        tasks.list_tasks("2026-13")
    with pytest.raises(TaskError):
        tasks.complete_task(999)


def test_task_with_reminder_is_separate_and_cancelled_on_completion():
    t = tasks.create_task("Submit thesis", due_date=date(2026, 9, 30))
    r = reminders.create_reminder(t.title, date(2026, 9, 30), time(9, 0), task_id=t.id,
                                  now=datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert reminders.get_reminder(r.id).task_id == t.id
    tasks.complete_task(t.id)
    assert reminders.get_reminder(r.id).status == "cancelled"
