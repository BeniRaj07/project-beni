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
import time as _time
from datetime import datetime, timezone

import gradio as gr

import theme
from assistant.conversation import ConversationState, respond, state_from_conversation, sync_conversation
from assistant.response_generator import fmt_datetime, fmt_month
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


# ── shared turn logic (typed AND voice messages funnel through here) ────────

def _to_chat_messages(conv) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in conv.messages]


def _process_turn(user_text: str, chatbot_history: list, conv_id: int | None, state: ConversationState,
                  autoplay: bool, force_speak: bool, lang_hint: str | None = None):
    """One full turn: echo the user's message, get a reply, optionally speak it.
    Yields (chatbot, conv_id, state, textbox, status, audio, conv_list) every time, so this can be
    used directly as a Gradio generator callback."""
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
    audio_path = None
    if spoken and (force_speak or autoplay):
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
              autoplay: bool):
    """Same as text_turn, but the message comes from a recorded clip. Voice questions always get a
    spoken reply (autoplay only gates typed messages); transcription failures are shown, not spoken."""
    if not audio_path:
        yield chatbot_history, conv_id, state, "", "", gr.skip(), gr.skip(), None
        return
    yield chatbot_history, conv_id, state, gr.skip(), "🎧 Transcribing…", gr.skip(), gr.skip(), gr.skip()
    try:
        tr = transcribe(audio_path)
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


def dashboard_panels(state: ConversationState | None):
    """Read-only HTML for the two side panels. Called on load, every DASHBOARD_POLL_SECONDS,
    and after any turn or reminder/task-affecting action so they stay live."""
    today = tasks.today_local()
    rems = reminders.list_reminders()[:8]
    rem_rows = [(r.title, fmt_datetime(r.local_due) + (f" · repeats {r.recurrence}" if r.recurrence != "none" else ""),
                "due" if r.local_due.date() == today else "")
               for r in rems]
    reminders_html = theme.panel("Reminders", theme.list_items(rem_rows, "No upcoming reminders"), len(rems))

    month = tasks.month_key(today)
    items = tasks.list_tasks(month)[:8]
    prog = tasks.month_progress(month, today)
    task_rows = [(t.title, ("due " + t.due_date if t.due_date else fmt_month(month)),
                 "done" if t.status == "completed" else ("due" if t.due_date and t.due_date < today.isoformat() else ""))
                for t in items]
    tasks_body = theme.list_items(task_rows, "No tasks this month") + theme.progress_bar(fmt_month(month), prog.percent)

    city = (state.last_city if state and state.last_city else settings.default_city)
    report, error = _cached_weather(city)
    if report is not None:
        icon = "🌧️" if report.raining_now else "🌤️"
        weather_html = theme.weather_card(f"{report.temperature:.0f}", weather.describe_code(report.weather_code),
                                          report.location.name, icon)
    else:
        weather_html = theme.weather_card("--", error or "unavailable", city, "⚠️")
    tasks_html = theme.panel("Tasks", tasks_body + weather_html, f"{prog.completed}/{prog.total}")

    return reminders_html, tasks_html


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
                             placeholder=theme.welcome_html(), render=False)
        status_line = gr.Markdown("", elem_id="status-line", render=False)
        audio_out = gr.Audio(autoplay=True, show_label=False, interactive=False,
                            elem_classes="audio-container", render=False)
        stop_audio_btn = gr.Button("⏹ Stop", elem_id="stop-audio-btn", visible=False, size="sm", render=False)
        text_in = gr.Textbox(placeholder="Message Awaaz…", show_label=False, elem_id="composer-input",
                             container=False, scale=8, lines=1, max_lines=6, render=False)
        send_btn = gr.Button("➤", elem_id="send-btn", scale=0, render=False)
        # No file_types filter: the browser's extension→MIME lookup classifies
        # ".webm" as video, so an "audio"-only filter rejects our own recordings.
        mic_upload = gr.File(elem_id="mic-upload", render=False)
        reminders_panel = gr.HTML(render=False)
        tasks_panel = gr.HTML(render=False)

        with gr.Column(elem_id="app-root"):
            gr.HTML(theme.topbar_html())

            # off-canvas conversation drawer (opened by the ☰ / ⚙ buttons in the top bar)
            gr.HTML('<div id="scrim" onclick="awaazToggleSidebar()"></div>')
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

            # ── dashboard: reminders | chat screen | tasks + weather ──────
            with gr.Row(elem_id="dashboard"):
                reminders_panel.render()

                with gr.Column(elem_id="center-screen"):
                    chatbot.render()
                    status_line.render()
                    gr.HTML(theme.rec_indicator_html())
                    gr.HTML('<div id="mic-status"></div>')
                    with gr.Row(elem_id="audio-row"):
                        audio_out.render()
                        stop_audio_btn.render()
                    with gr.Column(elem_id="composer-wrap"):
                        gr.HTML(theme.reticle_html())
                        with gr.Row(elem_id="composer"):
                            gr.HTML('<button class="mic-btn" onclick="awaazMicTap()" title="Tap to speak">🎤</button>')
                            text_in.render()
                            send_btn.render()
                    mic_upload.render()

                tasks_panel.render()

        # ── events ───────────────────────────────────────────────────────
        turn_outputs = [chatbot, active_id, convo_state, text_in, status_line, audio_out, conv_list]
        dashboard_outputs = [reminders_panel, tasks_panel]

        text_in.submit(text_turn, [text_in, chatbot, active_id, convo_state, autoplay_cb], turn_outputs
                       ).then(dashboard_panels, convo_state, dashboard_outputs)
        send_btn.click(text_turn, [text_in, chatbot, active_id, convo_state, autoplay_cb], turn_outputs
                      ).then(dashboard_panels, convo_state, dashboard_outputs)
        mic_upload.upload(voice_turn, [mic_upload, chatbot, active_id, convo_state, autoplay_cb],
                          [*turn_outputs, mic_upload]
                         ).then(dashboard_panels, convo_state, dashboard_outputs)

        new_chat_btn.click(start_new_chat, outputs=[chatbot, active_id, convo_state, text_in])
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
