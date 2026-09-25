"""Background reminder checking with APScheduler.

IMPORTANT (and stated in the UI): reminders only fire while this app is running. Reliable
notifications when the app is closed would need an always-on deployed scheduler plus an
external delivery channel (e-mail, SMS, push). Reminders that fell due while the app was closed
are announced once, as soon as it starts again.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from config import settings
from services import reminders
from services.text_to_speech import cleanup_old_audio

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def check_due_reminders() -> int:
    try:
        return len(reminders.fire_due_reminders())
    except Exception:  # noqa: BLE001 - a failed check must never kill the scheduler
        log.exception("reminder_check_failed")
        return 0


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC", job_defaults={"coalesce": True, "max_instances": 1})
    _scheduler.add_job(check_due_reminders, "interval", seconds=settings.reminder_check_seconds,
                       id="check_due_reminders")
    _scheduler.add_job(cleanup_old_audio, "interval", minutes=30, id="cleanup_audio")
    _scheduler.start()
    check_due_reminders()  # announce anything that fell due while the app was closed
    log.info("scheduler_started", extra={"interval_s": settings.reminder_check_seconds})
    return _scheduler


def stop_scheduler() -> None:
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
