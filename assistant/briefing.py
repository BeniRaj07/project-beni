"""The daily briefing spoken when the app opens (and on "what's my update?").

Built only from real data: tasks due today, tasks completed today, overdue tasks, today's
reminders and the current weather. No LLM is involved, so nothing can be invented.
"""
from __future__ import annotations

from datetime import datetime

from assistant.response_generator import NE_WEEKDAYS, Reply, fmt_month
from services import reminders, tasks
from services.weather import WeatherReport, describe_code


def _names(items, limit: int = 4) -> str:
    names = [x.title for x in items[:limit]]
    extra = len(items) - limit
    return ", ".join(names) + (f" (+{extra})" if extra > 0 else "")


def _greeting(hour: int, language: str) -> str:
    if language == "ne":
        return "शुभ प्रभात" if hour < 12 else "नमस्कार" if hour < 17 else "शुभ सन्ध्या"
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"


def build_briefing(now: datetime, language: str = "en", report: WeatherReport | None = None,
                   weather_error: str | None = None, city: str = "") -> Reply:
    """`now` must be timezone-aware local time. Returns display markdown + a spoken version."""
    ne = language == "ne"
    today = now.date()
    due = tasks.tasks_due_on(today)
    done = tasks.tasks_completed_on(today, now.tzinfo)
    overdue = tasks.overdue_tasks(today)
    # other pending tasks this month (not due today, not already reported as overdue)
    month_pending = [t for t in tasks.list_tasks(tasks.month_key(today), "pending")
                     if not t.due_date or t.due_date > today.isoformat()]
    rems = [r for r in reminders.list_reminders(on_local_date=today, tz_name=str(now.tzinfo))
            if r.local_due > now]

    if ne:
        head = f"{_greeting(now.hour, 'ne')}! आज {NE_WEEKDAYS[today.weekday()]}, {today:%Y-%m-%d}। तपाईंको आजको अपडेट:"
    else:
        head = f"{_greeting(now.hour, 'en')}! Here's your update for {today:%A %d %B}."
    lines: list[tuple[str, str]] = []   # (icon, sentence)

    # weather
    if report is not None:
        cond = describe_code(report.weather_code, language)
        place = report.location.name
        if ne:
            s = f"{place} मा अहिले {report.temperature:.0f}°C छ, {cond}।"
            s += " अहिले पानी परिरहेको छ।" if report.raining_now else " अहिले पानी परिरहेको छैन।"
            if report.rest_of_today_rain_probability is not None:
                s += f" आज बाँकी समयमा पानी पर्ने सम्भावना {report.rest_of_today_rain_probability}% सम्म छ।"
        else:
            s = f"In {place} it's {report.temperature:.0f}°C with {cond}."
            s += " It is raining right now." if report.raining_now else " It isn't raining right now."
            if report.rest_of_today_rain_probability is not None:
                s += f" Up to {report.rest_of_today_rain_probability}% chance of rain later today."
        lines.append(("🌤️", s))
    else:
        reason = weather_error or ("unavailable" if not ne else "उपलब्ध छैन")
        lines.append(("🌤️", f"{city} को मौसम अहिले उपलब्ध छैन।" if ne
                      else f"Weather for {city or 'your city'} is unavailable right now ({reason.lower()})."))

    # tasks due today
    if due:
        lines.append(("📝", f"आज गर्नुपर्ने {len(due)} काम: {_names(due)}।" if ne
                      else f"{len(due)} task{'s' if len(due) > 1 else ''} due today: {_names(due)}."))
    else:
        lines.append(("📝", "आज म्याद पुग्ने कुनै काम छैन।" if ne else "No tasks are due today."))
    if month_pending:
        lines.append(("📋", f"{fmt_month(tasks.month_key(today), 'ne')} मा अरू {len(month_pending)} काम बाँकी छन्।" if ne
                      else f"{len(month_pending)} other task{'s' if len(month_pending) > 1 else ''} pending this month."))

    # completed today
    if done:
        lines.append(("✅", f"आज पूरा भएका काम: {_names(done)}। शाबास!" if ne
                      else f"Completed today: {_names(done)}. Well done!"))
    else:
        lines.append(("✅", "आज अहिलेसम्म कुनै काम पूरा भएको छैन।" if ne
                      else "You haven't completed any tasks yet today."))

    if overdue:
        lines.append(("⚠️", f"म्याद नाघेका {len(overdue)} काम: {_names(overdue)}।" if ne
                      else f"{len(overdue)} overdue: {_names(overdue)}."))

    if rems:
        rem_txt = ", ".join(f"{r.title} {r.local_due:%H:%M}" for r in rems[:4])
        lines.append(("⏰", f"आजका बाँकी रिमाइन्डर: {rem_txt}।" if ne else f"Reminders still to come today: {rem_txt}."))

    display = f"**{head}**\n\n" + "\n".join(f"- {icon} {text}" for icon, text in lines)
    spoken = head + " " + " ".join(text for _, text in lines)
    return Reply(display, language, "daily_briefing", speak_text=spoken)
