"""Awaaz — a bilingual (नेपाली / English) voice & chat assistant with a sci-fi HUD dashboard.

Every feature (greetings, reminders, monthly tasks, weather, football) is still reached only
through conversation — typed or spoken — in the centre chat screen; nothing is created, edited or
deleted through a form. The Reminders and Tasks side panels, plus the clock and weather readouts,
are read-only live views of that same data, refreshed after every turn and periodically. The full
conversation history lives in an off-canvas drawer (☰ / ⚙ in the top bar). See README.md.

Run:  python app.py      then open http://127.0.0.1:7860
"""
from __future__ import annotations

import logging
import math
import time as _time
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

import gradio as gr
import psutil

import theme
from assistant.conversation import ConversationState, respond, state_from_conversation, sync_conversation
from assistant.response_generator import fmt_month
from config import settings, setup_logging
from database.stores import init_stores
from scheduler.reminder_scheduler import start_scheduler
from services import conversations as convo
from services import reminders, tasks, user_settings, weather
from services.http import ServiceError
from services.speech_to_text import STTError, transcribe
from services.text_to_speech import TTSError, synthesize

log = logging.getLogger("app")

REMINDER_POLL_SECONDS = 15
DASHBOARD_POLL_SECONDS = 30

# ── process-lifetime counters for the System Stats / Uptime dashboard cards ──
# Approximate on purpose: this is a single-user local app (see README §12), not a metrics
# service, so plain module-level counters (no lock) are the right amount of engineering here.
_APP_START_EPOCH_S = _time.time()
_session_count = 0
_command_count = 0
psutil.cpu_percent(interval=None)  # warm up: the first real reading needs a prior reference point


def _bump_session_count() -> None:
    global _session_count
    _session_count += 1


def _bump_command_count() -> None:
    global _command_count
    _command_count += 1


# ── shared turn logic (typed AND voice messages funnel through here) ────────

def _to_chat_messages(conv) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in conv.messages]


def _process_turn(user_text: str, chatbot_history: list, conv_id: int | None, state: ConversationState,
                  autoplay: bool, force_speak: bool, lang_hint: str | None = None):
    """One full turn: echo the user's message, get a reply, optionally speak it.
    Yields (chatbot, conv_id, state, textbox, status, audio, conv_list) every time, so this can be
    used directly as a Gradio generator callback."""
    _bump_command_count()
    if conv_id is None:
        conv = convo.new_conversation()
        conv_id = conv.id
        state = ConversationState()

    chatbot_history = list(chatbot_history or []) + [{"role": "user", "content": user_text}]
    yield chatbot_history, conv_id, state, "", "Awaaz is thinking…", gr.skip(), convo.list_conversations()

    convo.append_message(conv_id, "user", user_text, lang_hint or state.last_language)
    try:
        reply = respond(user_text, state, now=datetime.now(timezone.utc))
    except Exception:  # noqa: BLE001 - never let a bug take down the whole chat turn
        log.exception("turn_failed")
        reply_text, reply_lang, spoken = "⚠️ Something went wrong. Please try again.", state.last_language, None
    else:
        reply_text, reply_lang, spoken = reply.text, reply.language, reply.spoken
    convo.append_message(conv_id, "assistant", reply_text, reply_lang)
    sync_conversation(conv_id, state)

    chatbot_history = chatbot_history + [{"role": "assistant", "content": reply_text}]
    will_speak = bool(spoken and (force_speak or autoplay))
    # Show the text reply now instead of making the user wait through TTS (and its fallback
    # chain) before seeing anything — the audio player is filled in by the next yield.
    yield (chatbot_history, conv_id, state, "", "🔊 Generating voice reply…" if will_speak else "",
          gr.skip(), convo.list_conversations())

    audio_path = None
    if will_speak:
        try:
            audio_path = str(synthesize(spoken, reply_lang))
        except TTSError as e:
            log.warning("tts_failed", extra={"error": e.user_message})

    yield chatbot_history, conv_id, state, "", "", audio_path, convo.list_conversations()


def text_turn(text: str, chatbot_history: list, conv_id: int | None, state: ConversationState, autoplay: bool):
    text = (text or "").strip()
    if not text:
        yield chatbot_history, conv_id, state, "", "", gr.skip(), gr.skip()
        return
    yield from _process_turn(text, chatbot_history, conv_id, state, autoplay, force_speak=False)


def voice_turn(audio_path: str | None, chatbot_history: list, conv_id: int | None, state: ConversationState,
              autoplay: bool, lang_choice: str = "Auto"):
    """Same as text_turn, but the message comes from a recorded clip. Voice questions always get a
    spoken reply (autoplay only gates typed messages); transcription failures are shown, not spoken.
    lang_choice ("Auto"/"EN"/"ने") forces Whisper's language: auto-detection can mis-transcribe
    Nepali speech into an unrelated script entirely, not just mislabel it."""
    if not audio_path:
        yield chatbot_history, conv_id, state, "", "", gr.skip(), gr.skip(), None
        return
    yield chatbot_history, conv_id, state, gr.skip(), "🎧 Transcribing…", gr.skip(), gr.skip(), gr.skip()
    hint = {"EN": "en", "ने": "ne"}.get(lang_choice)
    try:
        tr = transcribe(audio_path, hint)
    except STTError as e:
        yield chatbot_history, conv_id, state, gr.skip(), f"⚠️ {e.user_message}", gr.skip(), gr.skip(), None
        return
    for out in _process_turn(tr.text, chatbot_history, conv_id, state, autoplay, force_speak=True,
                             lang_hint=tr.language):
        yield (*out, gr.skip())
    yield (*(gr.skip(),) * 7, None)  # clear the hidden upload so the next clip can trigger .upload again


# ── sidebar actions ──────────────────────────────────────────────────────────

def start_new_chat():
    return [], None, ConversationState(), ""


def open_conversation(conv_id: int):
    conv = convo.get_conversation(conv_id)
    if conv is None:
        return gr.skip(), gr.skip(), gr.skip()
    return _to_chat_messages(conv), conv.id, state_from_conversation(conv)


def begin_rename(conv_id: int):
    conv = convo.get_conversation(conv_id)
    title = conv.title if conv else ""
    return conv_id, gr.update(value=title, visible=True)


def cancel_rename():
    return None, gr.update(value="", visible=False)


def save_rename(conv_id: int | None, new_title: str):
    if conv_id is not None and (new_title or "").strip():
        convo.rename_conversation(conv_id, new_title)
    return None, gr.update(value="", visible=False), convo.list_conversations()


def delete_and_maybe_clear(conv_id: int, active_id_val: int | None, chatbot_history: list, state: ConversationState):
    convo.delete_conversation(conv_id)
    if conv_id == active_id_val:
        return [], None, ConversationState(), convo.list_conversations()
    return chatbot_history, active_id_val, state, convo.list_conversations()


# ── due-reminder chat notifications ─────────────────────────────────────────

def poll_due_reminders(chatbot_history: list, conv_id: int | None, state: ConversationState, autoplay: bool):
    fired = reminders.pop_unseen_notifications()
    if not fired:
        return (gr.skip(),) * 5
    if conv_id is None:
        conv = convo.new_conversation()
        conv_id, state = conv.id, ConversationState()
    lang = state.last_language
    if lang == "ne":
        text = "\n".join(f"🔔 सम्झना: **{n.title}** को समय भयो।" for n in fired)
    else:
        text = "\n".join(f"🔔 Reminder: **{n.title}** is due now." for n in fired)
    convo.append_message(conv_id, "assistant", text, lang)
    chatbot_history = list(chatbot_history or []) + [{"role": "assistant", "content": text}]
    audio_path = None
    if autoplay:
        try:
            audio_path = str(synthesize(text, lang))
        except TTSError:
            pass
    return chatbot_history, conv_id, state, audio_path, convo.list_conversations()


# ── settings ─────────────────────────────────────────────────────────────────

def on_autoplay_change(value: bool):
    user_settings.update_settings(auto_play=bool(value))


def stop_audio():
    return None


# ── dashboard panels: reminders, tasks, weather, all reached via conversation ─
# (read-only; every change still happens by talking to the assistant, never a form)

_weather_cache: dict = {"city": None, "at": 0.0, "report": None, "error": None}


def _cached_weather(city: str):
    """Weather for the dashboard card; after a failure, back off for a few minutes."""
    c = _weather_cache
    if c["city"] == city and _time.time() - c["at"] < (180 if c["error"] else 600):
        return c["report"], c["error"]
    try:
        report, error = weather.get_weather_report(city), None
        if report is None:
            error = "city not found"
    except ServiceError as e:
        report, error = None, e.user_message
    except Exception:  # noqa: BLE001 - a dashboard widget must never break the page
        log.warning("dashboard_weather_failed", exc_info=True)
        report, error = None, "unavailable"
    c.update(city=city, at=_time.time(), report=report, error=error)
    return report, error


def _task_due_label(t, today: date, now_local: datetime, month: str) -> str:
    """'in Xh' for anything due today (due_date carries no time of its own, so end-of-day stands in
    for the deadline), 'overdue' once past, else the plain date — or the month, if there's no due date."""
    if not t.due_date:
        return fmt_month(month)
    due = date.fromisoformat(t.due_date)
    if due < today:
        return "overdue"
    if due == today:
        end_of_day = datetime.combine(due, dtime(23, 59), tzinfo=now_local.tzinfo)
        hours_left = max(1, math.ceil((end_of_day - now_local).total_seconds() / 3600))
        return f"in {hours_left}h"
    return t.due_date


def _task_tag_class(t, today: date) -> str:
    if not t.due_date:
        return "due-later"
    due = date.fromisoformat(t.due_date)
    if due < today:
        return "overdue"
    if due == today:
        return "due-today"
    return "due-later"


def _reminder_day_label(d: date, today: date) -> str:
    if d == today:
        return "Today"
    if d == today + timedelta(days=1):
        return "Tomorrow"
    return d.strftime("%A")


def _reminder_time_12h(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def system_stats_html(cpu_pct: float) -> str:
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(str(Path(settings.data_dir).anchor or "/"))
    body = theme.system_stats_body(
        cpu_pct, vm.percent, vm.used / 1e9, vm.total / 1e9, disk.used / 1e9, disk.total / 1e9)
    return theme.panel("System Stats", body, icon_svg=theme.CPU_SVG)


def uptime_html(cpu_pct: float) -> str:
    elapsed = int(_time.time() - _APP_START_EPOCH_S)
    h, rem = divmod(elapsed, 3600)
    m, s = divmod(rem, 60)
    uptime_str = f"{h:02d}:{m:02d}:{s:02d}"
    load_label = "High" if cpu_pct >= 70 else ("Moderate" if cpu_pct >= 30 else "Low")
    body = theme.uptime_body(int(_APP_START_EPOCH_S * 1000), uptime_str, _session_count, _command_count,
                             cpu_pct, load_label)
    return theme.panel("System Uptime", body, icon_svg=theme.CLOCK_SVG)


def dashboard_panels(state: ConversationState | None):
    """Read-only HTML for the dashboard cards. Called on load, every DASHBOARD_POLL_SECONDS,
    and after any turn or reminder/task-affecting action so they stay live. Also builds the three
    card-detail modals' content (always kept fresh in the DOM even while closed - see
    theme.JS's awaazOpenModal), so opening one never shows a stale snapshot from whenever the
    page last polled before the click."""
    today = tasks.today_local()
    now_local = datetime.now(settings.tz)

    all_rems = reminders.list_reminders(limit=100)
    rem_rows = [(_reminder_time_12h(r.local_due), _reminder_day_label(r.local_due.date(), today), r.title,
                f"Repeats {r.recurrence}" if r.recurrence != "none" else "One-time",
                r.local_due.date() == today)
               for r in all_rems]
    reminders_html = theme.panel("Reminders", theme.reminder_list(rem_rows[:8], "No upcoming reminders"),
                                 len(all_rems), icon_svg=theme.BELL_SVG, onclick="awaazOpenModal('reminders')")
    reminders_modal_html = theme.modal_section("All Reminders", theme.BELL_SVG,
                                               theme.reminder_list(rem_rows, "No upcoming reminders"))

    month = tasks.month_key(today)
    all_items = tasks.list_tasks(month)
    prog = tasks.month_progress(month, today)
    task_rows = [(t.id, t.title, _task_due_label(t, today, now_local, month), _task_tag_class(t, today),
                 t.status == "completed")
                for t in all_items]
    progress_html = theme.progress_bar(prog.percent, f"{prog.completed}/{prog.total} · {fmt_month(month)}")
    tasks_body = theme.task_list(task_rows[:8], "No tasks this month") + progress_html
    tasks_html = theme.panel("Tasks", tasks_body, f"{prog.completed}/{prog.total}", icon_svg=theme.CHECKLIST_SVG,
                             onclick="awaazOpenModal('tasks')")
    tasks_modal_html = theme.modal_section(
        f"Tasks — {fmt_month(month)}", theme.CHECKLIST_SVG,
        theme.task_list(task_rows, "No tasks this month") + progress_html)

    city = (state.last_city if state and state.last_city else settings.default_city)
    report, error = _cached_weather(city)
    if report is not None:
        icon = theme.RAIN_SVG if report.raining_now else theme.CLOUD_SVG
        humidity = f"{report.humidity:.0f}%" if report.humidity is not None else "--"
        weather_html_body = theme.weather_body(
            f"{report.temperature:.0f}", weather.describe_code(report.weather_code), report.location.name, icon,
            humidity=humidity, wind=f"{report.wind_speed:.1f} km/h", feels_like=f"{report.apparent_temperature:.1f}°C")
        forecast_rows = "".join(
            theme.forecast_row(
                "Today" if d.day == today else d.day.strftime("%A"),
                theme.RAIN_SVG if d.rain_expected else theme.CLOUD_SVG,
                weather.describe_code(d.weather_code),
                f"{d.temp_max:.0f}" if d.temp_max is not None else "--",
                f"{d.temp_min:.0f}" if d.temp_min is not None else "--",
                f"{d.precipitation_probability}%" if d.precipitation_probability is not None else "--",
            )
            for d in report.daily[:7]
        )
        weather_modal_body = weather_html_body + f'<div class="forecast-list">{forecast_rows}</div>'
    else:
        weather_html_body = theme.weather_body("--", error or "unavailable", city, theme.CLOUD_SVG)
        weather_modal_body = weather_html_body
    weather_html = theme.panel("Weather", weather_html_body, icon_svg=theme.CLOUD_SVG,
                               onclick="awaazOpenModal('weather')")
    weather_modal_html = theme.modal_section("7-Day Forecast", theme.CLOUD_SVG, weather_modal_body)

    # One shared reading: psutil.cpu_percent(interval=None) measures usage since its OWN last
    # call, so calling it twice back-to-back would make the second reading measure almost no
    # elapsed time and always come back near 0%.
    cpu_pct = psutil.cpu_percent(interval=None)
    return (reminders_html, tasks_html, weather_html, system_stats_html(cpu_pct), uptime_html(cpu_pct),
           weather_modal_html, tasks_modal_html, reminders_modal_html)


def toggle_task_status(trigger_value: str, state: ConversationState | None):
    """Fired by the hidden #task-toggle-trigger textbox (see theme.JS's awaazToggleTask) when the
    user clicks a task's checkbox directly on the dashboard. Flips pending<->completed via the
    exact same tasks.set_task_status() call voice/text completion already uses, so a task checked
    off from the UI behaves identically - including cancelling its linked reminder, if any."""
    task_id_str = trigger_value.split(":", 1)[0] if trigger_value else ""
    if task_id_str.isdigit():
        task = tasks.get_task(int(task_id_str))
        if task is not None and task.status in ("pending", "completed"):
            next_status = "pending" if task.status == "completed" else "completed"
            try:
                tasks.set_task_status(task.id, next_status)
            except tasks.TaskError:
                log.warning("task_toggle_failed", extra={"task_id": task.id})
    return dashboard_panels(state)


def extract_conversation(conv_id: int | None, chatbot_history: list) -> str | None:
    """Write the current transcript to a text file and hand its path to the DownloadButton that
    triggered this — Gradio downloads a DownloadButton's new value automatically once its own
    click handler returns it, so this doubles as both "build" and "download" in one click."""
    if not chatbot_history:
        return None
    lines = [f"{'You' if m['role'] == 'user' else 'Awaaz'}: {m['content']}" for m in chatbot_history]
    out_dir = settings.data_dir / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"conversation_{conv_id if conv_id is not None else 'draft'}.txt"
    path.write_text("\n\n".join(lines), encoding="utf-8")
    return str(path)


# ── layout ───────────────────────────────────────────────────────────────────

def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Awaaz") as demo:
        conv_list = gr.State([])
        active_id = gr.State(None)
        convo_state = gr.State(ConversationState())
        rename_id = gr.State(None)
        search_q = gr.State("")

        # Created here (not yet placed) so the sidebar's event handlers, defined below, can target
        # them; `.render()` places each one in the dashboard further down.
        chatbot = gr.Chatbot(elem_id="chatbot", show_label=False, buttons=["copy"],
                             placeholder=theme.conversation_welcome_html(), render=False)
        status_line = gr.Markdown("", elem_id="status-line", render=False)
        audio_out = gr.Audio(autoplay=True, show_label=False, interactive=False,
                            elem_classes="audio-container", render=False)
        stop_audio_btn = gr.Button("⏹ Stop", elem_id="stop-audio-btn", visible=False, size="sm", render=False)
        text_in = gr.Textbox(placeholder="Type a message…", show_label=False, elem_id="composer-input",
                             container=False, scale=8, lines=1, max_lines=6, render=False)
        send_btn = gr.Button("➤", elem_id="send-btn", scale=0, render=False)
        # No file_types filter: the browser's extension→MIME lookup classifies
        # ".webm" as video, so an "audio"-only filter rejects our own recordings.
        mic_upload = gr.File(elem_id="mic-upload", render=False)
        # Hidden relay for task checkbox clicks (see theme.JS's awaazToggleTask). visible=False
        # (rather than hidden by CSS, as done here) would drop the <textarea>/<button> from the
        # DOM entirely, leaving nothing for the JS to find - same off-screen-CSS trick as
        # #mic-upload above. The button (not the textbox's own change/input event) is what
        # actually triggers the server call - see its js= wiring below for why.
        task_toggle_trigger = gr.Textbox(elem_id="task-toggle-trigger", render=False)
        task_toggle_btn = gr.Button(elem_id="task-toggle-btn", render=False)
        reminders_panel = gr.HTML(render=False)
        tasks_panel = gr.HTML(render=False)
        weather_panel = gr.HTML(elem_id="weather-card", render=False)
        sys_stats_panel = gr.HTML(render=False)
        uptime_panel = gr.HTML(render=False)
        weather_modal_panel = gr.HTML(elem_id="modal-weather-content", elem_classes="modal-section", render=False)
        tasks_modal_panel = gr.HTML(elem_id="modal-tasks-content", elem_classes="modal-section", render=False)
        reminders_modal_panel = gr.HTML(elem_id="modal-reminders-content", elem_classes="modal-section", render=False)

        with gr.Column(elem_id="app-root"):
            gr.HTML(theme.topbar_html())

            # off-canvas conversation drawer (opened by the ☰ / ⚙ buttons in the top bar)
            gr.HTML('<div id="scrim" onclick="awaazToggleSidebar()"></div>')

            # card detail modals (Weather / Tasks / Reminders) - hidden by default, toggled by
            # awaazOpenModal/awaazCloseModal in theme.JS; content stays populated even while
            # closed so it's never stale on open (see dashboard_panels in app.py).
            gr.HTML(theme.modal_shell_html())
            with gr.Column(elem_id="modal-panel"):
                gr.HTML('<button class="modal-close" onclick="awaazCloseModal()" title="Close">✕</button>')
                with gr.Column(elem_id="modal-body"):
                    weather_modal_panel.render()
                    tasks_modal_panel.render()
                    reminders_modal_panel.render()

            with gr.Column(elem_id="sidebar"):
                gr.HTML(theme.sidebar_header_html())
                new_chat_btn = gr.Button("＋ New chat", elem_id="new-chat-btn")
                search_box = gr.Textbox(placeholder="🔍 Search conversations", show_label=False,
                                        elem_id="search-box", container=False)
                with gr.Row(elem_id="rename-bar", visible=False) as rename_row:
                    rename_box = gr.Textbox(show_label=False, container=False, scale=3)
                    rename_save = gr.Button("Save", scale=1, size="sm", variant="primary")
                    rename_cancel = gr.Button("✕", scale=0, size="sm", min_width=32)

                with gr.Column(elem_id="sidebar-scroll"):
                    @gr.render(inputs=[conv_list, search_q, active_id])
                    def render_sidebar_list(items, query, active):
                        filtered = convo.search_conversations(query) if query else items
                        groups = convo.group_conversations(filtered)
                        if not groups:
                            gr.Markdown("_No conversations yet — say hello!_", elem_classes="note")
                            return
                        for label, convs in groups.items():
                            gr.HTML(f'<div class="conv-group-label">{label}</div>')
                            for c in convs:
                                row_classes = ["conv-row"] + (["active"] if c.id == active else [])
                                with gr.Row(elem_classes=row_classes, equal_height=True):
                                    title_btn = gr.Button(c.title, elem_classes="conv-title-btn", size="sm")
                                    rename_btn = gr.Button("✏️", elem_classes="conv-icon-btn", size="sm", min_width=26)
                                    delete_btn = gr.Button("🗑️", elem_classes="conv-icon-btn", size="sm", min_width=26)
                                    title_btn.click(open_conversation, gr.State(c.id),
                                                    [chatbot, active_id, convo_state])
                                    rename_btn.click(begin_rename, gr.State(c.id), [rename_id, rename_box])
                                    delete_btn.click(delete_and_maybe_clear,
                                                     [gr.State(c.id), active_id, chatbot, convo_state],
                                                     [chatbot, active_id, convo_state, conv_list])

                with gr.Row(elem_id="sidebar-footer"):
                    gr.HTML('<button id="theme-toggle" onclick="awaazToggleTheme()" title="Toggle theme">🌓</button>')
                    autoplay_cb = gr.Checkbox(value=lambda: user_settings.get_settings().auto_play,
                                              label="🔊 Auto-play replies", container=False)
                    mic_lang = gr.Radio(["Auto", "EN", "ने"], value="Auto", show_label=False,
                                        container=False, elem_id="mic-lang",
                                        info="🎤 Speech language (fixes mis-transcribed Nepali)")

            # ── dashboard: live cards | voice orb | conversation ──────────
            with gr.Row(elem_id="dashboard"):
                with gr.Column(elem_id="left-rail"):
                    sys_stats_panel.render()
                    weather_panel.render()
                    tasks_panel.render()
                    reminders_panel.render()
                    uptime_panel.render()

                with gr.Column(elem_id="center-screen"):
                    gr.HTML(theme.voice_orb_html())
                    with gr.Row(elem_id="audio-row"):
                        audio_out.render()
                        stop_audio_btn.render()
                    mic_upload.render()
                    task_toggle_trigger.render()
                    task_toggle_btn.render()

                with gr.Column(elem_id="right-rail"):
                    with gr.Row(elem_id="convo-head"):
                        gr.HTML("<h2>Conversation</h2>")
                        with gr.Row(elem_id="convo-actions"):
                            clear_btn = gr.Button("🗑 Clear", elem_classes="chip-btn", size="sm")
                            extract_btn = gr.DownloadButton("⬇ Extract Conversation", elem_id="extract-btn",
                                                            elem_classes="chip-btn", size="sm")
                    chatbot.render()
                    status_line.render()
                    with gr.Column(elem_id="composer-wrap"):
                        with gr.Row(elem_id="composer"):
                            text_in.render()
                            send_btn.render()

        # ── events ───────────────────────────────────────────────────────
        turn_outputs = [chatbot, active_id, convo_state, text_in, status_line, audio_out, conv_list]
        dashboard_outputs = [reminders_panel, tasks_panel, weather_panel, sys_stats_panel, uptime_panel,
                            weather_modal_panel, tasks_modal_panel, reminders_modal_panel]

        text_in.submit(text_turn, [text_in, chatbot, active_id, convo_state, autoplay_cb], turn_outputs
                       ).then(dashboard_panels, convo_state, dashboard_outputs)
        send_btn.click(text_turn, [text_in, chatbot, active_id, convo_state, autoplay_cb], turn_outputs
                      ).then(dashboard_panels, convo_state, dashboard_outputs)
        mic_upload.upload(voice_turn, [mic_upload, chatbot, active_id, convo_state, autoplay_cb, mic_lang],
                          [*turn_outputs, mic_upload]
                         ).then(dashboard_panels, convo_state, dashboard_outputs)
        # js= reads #task-toggle-trigger's live DOM value directly at click time, bypassing
        # Gradio's own reactive tracking for that textbox entirely (which a synthetic input event
        # on the textbox itself does not update - confirmed empirically, see theme.JS's comment
        # on awaazToggleTask). The button click is real (native .click()), which Gradio handles
        # exactly like a user-initiated click regardless of how it was triggered.
        task_toggle_btn.click(
            toggle_task_status, [task_toggle_trigger, convo_state], dashboard_outputs,
            js="(triggerVal, state) => { const el = document.querySelector("
              "'#task-toggle-trigger textarea, #task-toggle-trigger input'); "
              "return [el ? el.value : triggerVal, state]; }")

        new_chat_btn.click(start_new_chat, outputs=[chatbot, active_id, convo_state, text_in])
        clear_btn.click(start_new_chat, outputs=[chatbot, active_id, convo_state, text_in])
        extract_btn.click(extract_conversation, [active_id, chatbot], extract_btn)
        search_box.input(lambda q: q, search_box, search_q)

        rename_save.click(save_rename, [rename_id, rename_box], [rename_id, rename_box, conv_list]
                          ).then(lambda: gr.update(visible=False), outputs=rename_row)
        rename_cancel.click(cancel_rename, outputs=[rename_id, rename_box]
                            ).then(lambda: gr.update(visible=False), outputs=rename_row)
        rename_id.change(lambda rid: gr.update(visible=rid is not None), rename_id, rename_row)

        autoplay_cb.change(on_autoplay_change, autoplay_cb)
        audio_out.change(lambda a: gr.update(visible=a is not None), audio_out, stop_audio_btn)
        stop_audio_btn.click(stop_audio, outputs=audio_out)

        gr.Timer(REMINDER_POLL_SECONDS).tick(
            poll_due_reminders, [chatbot, active_id, convo_state, autoplay_cb],
            [chatbot, active_id, convo_state, audio_out, conv_list]
        ).then(dashboard_panels, convo_state, dashboard_outputs)
        gr.Timer(DASHBOARD_POLL_SECONDS).tick(dashboard_panels, convo_state, dashboard_outputs)

        demo.load(lambda: convo.list_conversations(), outputs=conv_list
                 ).then(_bump_session_count
                 ).then(dashboard_panels, convo_state, dashboard_outputs)
    return demo


def main() -> None:
    setup_logging()
    init_stores()
    user_settings.seed_from_env()
    start_scheduler()
    log.info("starting", extra={"host": settings.server_host, "port": settings.server_port, "tz": settings.timezone})
    auth = tuple(settings.app_auth.split(":", 1)) if ":" in settings.app_auth else None
    initial_theme = user_settings.get_settings().theme
    build_ui().queue().launch(
        server_name=settings.server_host, server_port=settings.server_port, auth=auth,
        theme=theme.THEME, css=theme.CSS, head=theme.head(initial_theme),
    )


if __name__ == "__main__":
    main()
