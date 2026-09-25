"""One handler per intent. Each returns a Reply; none of them lets an exception escape silently
(errors are caught centrally in conversation.py and turned into friendly messages)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable
from zoneinfo import ZoneInfo

from assistant.intent_classifier import IntentResult
from assistant.response_generator import (
    Reply, fmt_date, fmt_datetime, fmt_month, format_matches, format_reminder_line, format_sources,
    format_standings, format_task_line, format_weather, generate_greeting, recurrence_text,
    standings_speech, summarize_news, t,
)
from config import settings
from services import football, news, reminders, tasks, weather
from services.http import ServiceError
from services.reminders import ReminderError
from services.tasks import TaskError

if TYPE_CHECKING:
    from assistant.conversation import ConversationState

Handler = Callable[[IntentResult, str, "ConversationState", datetime], Reply]


def _ask(state: "ConversationState", intent: IntentResult, question: str, missing: str) -> Reply:
    """Ask a clarification question and remember what we are waiting for (follow-up support)."""
    state.pending = {"intent": intent.intent, "missing": missing, "question": question,
                     "fields": intent.model_dump(mode="json", exclude_none=True, exclude={"clarification"})}
    return Reply(question, intent.language, intent.intent)


def _supported_leagues(lang: str) -> str:
    return ", ".join(football.league_name(c, lang) for c in football.LEAGUES)


# ── small talk / weather ────────────────────────────────────────────────────

def handle_greeting(it: IntentResult, text: str, state, now: datetime) -> Reply:
    return Reply(generate_greeting(text, it.language, state.history), it.language, it.intent)


def handle_weather(it: IntentResult, text: str, state, now: datetime) -> Reply:
    city = it.city or state.last_city
    if not city:
        return _ask(state, it, t("ask_city", it.language), "city")
    report = weather.get_weather_report(city)
    if report is None:
        return Reply(t("city_not_found", it.language, city=city), it.language, it.intent)
    state.last_city = city
    target = it.date if it.weather_when != "current" else None
    display, spoken = format_weather(report, it.language, target, now.date())
    display += "\n\n_" + t("updated", it.language, when=f"{report.fetched_at:%Y-%m-%d %H:%M}") + " · Open-Meteo_"
    return Reply(display, it.language, it.intent, speak_text=spoken)


# ── football ────────────────────────────────────────────────────────────────

def handle_football_news(it: IntentResult, text: str, state, now: datetime) -> Reply:
    lang = it.language
    code = football.resolve_league(it.league)
    topic = it.team or (football.league_name(code) if code else it.league)
    articles = news.fetch_football_articles(topic)
    if not articles:
        about = (f" about {topic}" if lang == "en" else f"{topic} बारे ") if topic else ""
        return Reply(t("no_news", lang, about=about), lang, it.intent)
    summary = summarize_news(articles, lang, topic)
    display = "\n\n".join([t("news_label", lang), summary, format_sources(articles, lang),
                           "_" + t("updated", lang, when=f"{now:%Y-%m-%d %H:%M}") + " · NewsAPI_"])
    return Reply(display, lang, it.intent, speak_text=summary)


def _league_or_ask(it: IntentResult, state) -> tuple[str | None, Reply | None]:
    if not it.league:
        return None, _ask(state, it, t("ask_league", it.language, leagues=_supported_leagues(it.language)), "league")
    code = football.resolve_league(it.league)
    if not code:
        return None, Reply(t("unsupported_league", it.language, leagues=_supported_leagues(it.language)),
                           it.language, it.intent)
    return code, None


def handle_league_table(it: IntentResult, text: str, state, now: datetime) -> Reply:
    code, early = _league_or_ask(it, state)
    if early:
        return early
    lang = it.language
    groups = football.get_standings(code)
    what = football.league_name(code, lang)
    if not groups or not groups[0][1]:
        return Reply(t("no_results", lang, what=what), lang, it.intent)
    display = "\n\n".join([t("table_header", lang, what=what), format_standings(groups, lang),
                           t("free_tier_note", lang), "_" + t("updated", lang, when=f"{now:%Y-%m-%d %H:%M}") + "_"])
    return Reply(display, lang, it.intent, speak_text=standings_speech(groups, what, lang))


def _team_or_league_matches(it: IntentResult, state, now: datetime, upcoming: bool) -> Reply:
    lang = it.language
    tz = now.tzinfo
    if it.team:
        code = football.resolve_league(it.league) if it.league else None
        found = football.find_team(it.team, code)
        if not found:
            return Reply(t("team_not_found", lang, team=it.team), lang, it.intent)
        team_id, what = found
        matches = football.get_team_fixtures(team_id) if upcoming else football.get_team_results(team_id)
    else:
        code, early = _league_or_ask(it, state)
        if early:
            return early
        what = football.league_name(code, lang)
        matches = football.get_upcoming_fixtures(code) if upcoming else football.get_recent_results(code)
    if not matches:
        return Reply(t("no_fixtures" if upcoming else "no_results", lang, what=what), lang, it.intent)
    header = t("fixtures_header" if upcoming else "results_header", lang, what=what)
    body = format_matches(matches, tz, lang)
    display = "\n\n".join([header, body, t("free_tier_note", lang),
                           "_" + t("updated", lang, when=f"{now:%Y-%m-%d %H:%M}") + "_"])
    first = matches[0]
    if upcoming:
        speech = (f"{what}: next match {first.home} versus {first.away} on {first.utc_date.astimezone(tz):%d %B at %H:%M}."
                  if lang == "en" else f"{what}: अर्को खेल {first.home} विरुद्ध {first.away}, {first.utc_date.astimezone(tz):%Y-%m-%d %H:%M} मा।")
    else:
        scores = "; ".join(f"{m.home} {m.home_score}, {m.away} {m.away_score}" for m in matches[:3] if m.home_score is not None)
        speech = (f"Recent results for {what}: {scores}." if lang == "en" else f"{what} का हालका नतिजा: {scores}।")
    return Reply(display, lang, it.intent, speak_text=speech)


def handle_league_results(it, text, state, now):
    return _team_or_league_matches(it, state, now, upcoming=False)


def handle_football_fixtures(it, text, state, now):
    return _team_or_league_matches(it, state, now, upcoming=True)


# ── reminders ───────────────────────────────────────────────────────────────

def handle_create_reminder(it: IntentResult, text: str, state, now: datetime) -> Reply:
    lang = it.language
    if not it.title:
        return _ask(state, it, t("ask_reminder_title", lang), "title")
    if not it.time:
        return _ask(state, it, t("ask_reminder_time", lang, title=it.title), "time")
    tz_name = it.timezone or settings.timezone
    local_now = now.astimezone(ZoneInfo(tz_name))
    recurrence = it.recurrence or "none"
    day = it.date
    if day is None:  # time without a date: the next time that clock time comes round
        day = local_now.date() if it.time > local_now.time() else local_now.date() + timedelta(days=1)
    try:
        r = reminders.create_reminder(it.title, day, it.time, recurrence, tz_name, now=now)
    except ReminderError as e:
        if "past" in str(e):
            when = fmt_datetime(datetime.combine(day, it.time), lang)
            it.date = None
            it.time = None
            return _ask(state, it, t("reminder_past", lang, when=when), "time")
        return Reply(f"⚠️ {e}", lang, it.intent)
    msg = t("reminder_saved", lang, title=r.title, when=fmt_datetime(r.local_due, lang),
            repeat=recurrence_text(r.recurrence, lang)) + t("reminder_note", lang)
    return Reply(msg, lang, it.intent, speak_text=msg.split("\n\n")[0], data_changed=True)


def _resolve(it: IntentResult, state, kind: str):
    """Find the reminder/task the user means. Returns (item, early_reply)."""
    lang = it.language
    get_one = reminders.get_reminder if kind == "reminder" else tasks.get_task
    if it.target_id:
        item = get_one(it.target_id)
        if item:
            return item, None
    if not it.title:
        return None, _ask(state, it, t(f"which_{kind}", lang), "title")
    matches = (reminders.find_reminders(it.title) if kind == "reminder"
               else tasks.find_tasks(it.title, status=None if it.intent != "complete_task" else "pending"))
    if not matches:
        return None, Reply(t(f"{kind}_not_found", lang, title=it.title), lang, it.intent)
    if len(matches) > 1:
        options = "; ".join(f"#{m.id} {m.title}" for m in matches[:5])
        it.title = None
        return None, _ask(state, it, t("multiple_matches", lang, options=options), "target_id")
    return matches[0], None


def handle_list_reminders(it: IntentResult, text: str, state, now: datetime) -> Reply:
    lang = it.language
    items = reminders.list_reminders(on_local_date=it.date, tz_name=settings.timezone)
    scope = ""
    if it.date:
        scope = (" for " + ("today" if it.date == now.date() else fmt_date(it.date))) if lang == "en" \
            else (" (" + ("आज" if it.date == now.date() else fmt_date(it.date, "ne")) + ")")
    if not items:
        return Reply(t("no_reminders", lang, scope=scope), lang, it.intent)
    lines = [t("reminders_header", lang, scope=scope)] + [format_reminder_line(r, lang) for r in items[:15]]
    speech = lines[0] + " " + "; ".join(f"{r.title}, {fmt_datetime(r.local_due, lang)}" for r in items[:5])
    return Reply("\n".join(lines), lang, it.intent, speak_text=speech)


def handle_update_reminder(it: IntentResult, text: str, state, now: datetime) -> Reply:
    lang = it.language
    r, early = _resolve(it, state, "reminder")
    if early:
        return early
    try:
        if it.status in ("done", "completed"):
            r = reminders.set_reminder_status(r.id, "done")
            return Reply(t("reminder_done", lang, title=r.title), lang, it.intent, data_changed=True)
        if it.status == "cancelled":
            r = reminders.set_reminder_status(r.id, "cancelled")
            return Reply(t("reminder_cancelled", lang, title=r.title), lang, it.intent, data_changed=True)
        new_date = it.new_date or it.date
        new_time = it.new_time or it.time
        if not (it.new_title or new_date or new_time or it.recurrence):
            return _ask(state, it, "What should I change about it?" if lang == "en" else "के परिवर्तन गरूँ?", "new_time")
        r = reminders.update_reminder(r.id, title=it.new_title, local_date=new_date, local_time=new_time,
                                      recurrence=it.recurrence, now=now)
    except ReminderError as e:
        return Reply(f"⚠️ {e}", lang, it.intent)
    return Reply(t("reminder_updated", lang, title=r.title, when=fmt_datetime(r.local_due, lang),
                   repeat=recurrence_text(r.recurrence, lang)), lang, it.intent, data_changed=True)


def handle_delete_reminder(it: IntentResult, text: str, state, now: datetime) -> Reply:
    r, early = _resolve(it, state, "reminder")
    if early:
        return early
    reminders.delete_reminder(r.id)
    return Reply(t("reminder_deleted", it.language, title=r.title), it.language, it.intent, data_changed=True)


# ── tasks ───────────────────────────────────────────────────────────────────

def handle_create_task(it: IntentResult, text: str, state, now: datetime) -> Reply:
    lang = it.language
    if not it.title:
        return _ask(state, it, t("ask_task_title", lang), "title")
    recurring = it.recurrence == "monthly"
    try:
        task = tasks.create_task(it.title, month=it.month, due_date=it.date, description=it.description,
                                 recurring_monthly=recurring)
    except TaskError as e:
        return Reply(f"⚠️ {e}", lang, it.intent)
    due = f" ({'due' if lang == 'en' else 'म्याद'} {task.due_date})" if task.due_date else ""
    msg = t("task_added", lang, title=task.title, month=fmt_month(task.month, lang), due=due,
            repeat=recurrence_text("monthly", lang) if recurring else "")
    if it.with_reminder and it.time:
        day = it.date or now.date()
        try:
            r = reminders.create_reminder(task.title, day, it.time, "monthly" if recurring else "none",
                                          settings.timezone, task_id=task.id, now=now)
            msg += t("task_reminder_added", lang, when=fmt_datetime(r.local_due, lang))
        except ReminderError as e:
            msg += f" ⚠️ {e}"
    return Reply(msg, lang, it.intent, data_changed=True)


def handle_list_tasks(it: IntentResult, text: str, state, now: datetime) -> Reply:
    lang = it.language
    status = it.status if it.status in ("pending", "completed", "overdue") else None
    if status == "overdue":
        items = tasks.overdue_tasks(now.date())
        if not items:
            return Reply("🎉 No overdue tasks!" if lang == "en" else "🎉 म्याद नाघेको कुनै काम छैन!", lang, it.intent)
        head = "⚠️ Overdue tasks:" if lang == "en" else "⚠️ म्याद नाघेका कामहरू:"
        lines = [head] + [format_task_line(x, lang, now.date()) + f" _({fmt_month(x.month, lang)})_" for x in items]
        return Reply("\n".join(lines), lang, it.intent)
    month = it.month or (tasks.month_key(it.date) if it.date else tasks.month_key(now.date()))
    prog = tasks.month_progress(month, now.date())
    items = tasks.list_tasks(month, status)
    kind = {"pending": ("pending ", "बाँकी "), "completed": ("completed ", "पूरा भएका ")}.get(status, ("", ""))
    kind_txt = kind[1] if lang == "ne" else kind[0]
    if not items:
        return Reply(t("no_tasks", lang, kind=kind_txt, month=fmt_month(month, lang)), lang, it.intent)
    header = t("tasks_header", lang, kind=kind_txt.capitalize() if lang == "en" else kind_txt,
               month=fmt_month(month, lang), done=prog.completed, total=prog.total)
    lines = [header] + [format_task_line(x, lang, now.date()) for x in items]
    speech = header + " " + "; ".join(x.title for x in items[:6])
    return Reply("\n".join(lines), lang, it.intent, speak_text=speech)


def handle_complete_task(it: IntentResult, text: str, state, now: datetime) -> Reply:
    task, early = _resolve(it, state, "task")
    if early:
        return early
    task = tasks.complete_task(task.id)
    return Reply(t("task_completed", it.language, title=task.title), it.language, it.intent, data_changed=True)


def handle_update_task(it: IntentResult, text: str, state, now: datetime) -> Reply:
    lang = it.language
    task, early = _resolve(it, state, "task")
    if early:
        return early
    if it.status == "completed":
        return handle_complete_task(it, text, state, now)
    new_date = it.new_date or it.date
    if not (it.new_title or new_date or it.description):
        return _ask(state, it, "What should I change about it?" if lang == "en" else "के परिवर्तन गरूँ?", "new_title")
    try:
        task = tasks.update_task(task.id, title=it.new_title, description=it.description, due_date=new_date)
    except TaskError as e:
        return Reply(f"⚠️ {e}", lang, it.intent)
    due = f" ({'due' if lang == 'en' else 'म्याद'} {task.due_date})" if task.due_date else ""
    return Reply(t("task_updated", lang, title=task.title, due=due), lang, it.intent, data_changed=True)


def handle_delete_task(it: IntentResult, text: str, state, now: datetime) -> Reply:
    lang = it.language
    task, early = _resolve(it, state, "task")
    if early:
        return early
    tasks.delete_task(task.id)
    repeat = ("" if not task.recurring else
              (" and stopped it repeating" if lang == "en" else " र दोहोरिन बन्द गरियो"))
    return Reply(t("task_deleted", lang, title=task.title, repeat=repeat), lang, it.intent, data_changed=True)


def handle_daily_briefing(it: IntentResult, text: str, state, now: datetime) -> Reply:
    from assistant.briefing import build_briefing
    city = state.last_city or settings.default_city
    report, error = None, None
    try:
        report = weather.get_weather_report(city)
        if report is None:
            error = "city not found"
    except ServiceError as e:        # the rest of the briefing still works without weather
        error = e.user_message
    return build_briefing(now, it.language, report, error, city)


def handle_out_of_scope(it: IntentResult, text: str, state, now: datetime) -> Reply:
    if it.clarification:
        return Reply(it.clarification, it.language, "clarify")
    return Reply(t("out_of_scope", it.language), it.language, it.intent)


HANDLERS: dict[str, Handler] = {
    "greeting": handle_greeting, "weather": handle_weather,
    "football_news": handle_football_news, "league_table": handle_league_table,
    "league_results": handle_league_results, "football_fixtures": handle_football_fixtures,
    "create_reminder": handle_create_reminder, "list_reminders": handle_list_reminders,
    "update_reminder": handle_update_reminder, "delete_reminder": handle_delete_reminder,
    "create_task": handle_create_task, "list_tasks": handle_list_tasks, "update_task": handle_update_task,
    "complete_task": handle_complete_task, "delete_task": handle_delete_task,
    "daily_briefing": handle_daily_briefing,
    "out_of_scope": handle_out_of_scope,
}
