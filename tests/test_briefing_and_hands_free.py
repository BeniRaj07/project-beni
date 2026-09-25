from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from assistant import conversation, handlers, intent_classifier
from assistant.briefing import build_briefing
from assistant.conversation import ConversationState, respond
from services import reminders, tasks, weather
from services.speech_to_text import STTError, Transcription
from tests.conftest import GEOCODE_KATHMANDU, forecast_payload

KTM = ZoneInfo("Asia/Kathmandu")
NOW = datetime(2026, 9, 25, 9, 0, tzinfo=KTM)


@pytest.fixture
def report(monkeypatch):
    monkeypatch.setattr(weather, "get_json", lambda service, url, **kw:
                        GEOCODE_KATHMANDU if "geocoding" in url else forecast_payload(rain_now=0.8, code=53))
    return weather.get_weather_report("Kathmandu")


def seed_day():
    tasks.create_task("Submit report", due_date=date(2026, 9, 25))
    tasks.create_task("Pay electricity bill", due_date=date(2026, 9, 25))
    tasks.create_task("Old essay", due_date=date(2026, 9, 20))
    tasks.create_task("Plan trip", month="2026-09")
    done = tasks.create_task("Buy groceries", due_date=date(2026, 9, 25))
    tasks.complete_task(done.id)
    reminders.create_reminder("Call mum", date(2026, 9, 25), time(20, 0), now=NOW)


def test_tasks_due_and_completed_today(monkeypatch):
    seed_day()
    assert [t.title for t in tasks.tasks_due_on(date(2026, 9, 25))] == ["Submit report", "Pay electricity bill"]
    today_real = datetime.now(KTM).date()   # completed_at is stamped with the real clock
    assert [t.title for t in tasks.tasks_completed_on(today_real, KTM)] == ["Buy groceries"]


def test_briefing_covers_weather_tasks_done_overdue_and_reminders(report, monkeypatch):
    seed_day()
    monkeypatch.setattr(tasks, "tasks_completed_on", lambda day, tz=None: [tasks.find_tasks("groceries", status="completed")[0]])
    b = build_briefing(NOW, "en", report, None, "Kathmandu")
    assert "Good morning! Here's your update for Friday 25 September." in b.spoken
    assert "In Kathmandu it's 24°C with moderate drizzle. It is raining right now." in b.spoken
    assert "2 tasks due today: Submit report, Pay electricity bill." in b.spoken
    assert "Completed today: Buy groceries." in b.spoken
    assert "1 overdue: Old essay." in b.spoken
    assert "1 other task pending this month." in b.spoken
    assert "Reminders still to come today: Call mum 20:00." in b.spoken
    assert b.intent == "daily_briefing" and b.text.startswith("**Good morning")


def test_empty_day_and_missing_weather_in_nepali():
    b = build_briefing(NOW, "ne", None, "could not connect", "Kathmandu")
    assert b.language == "ne" and "शुभ प्रभात" in b.spoken
    assert "मौसम अहिले उपलब्ध छैन" in b.spoken
    assert "आज म्याद पुग्ने कुनै काम छैन" in b.spoken
    assert "कुनै काम पूरा भएको छैन" in b.spoken


def test_what_is_my_update_by_voice(report, monkeypatch):
    seed_day()
    monkeypatch.setattr(intent_classifier, "chat_json", lambda messages, **kw: {"intent": "daily_briefing"})
    reply = respond("What's my update for today?", ConversationState(), now=NOW)
    assert reply.intent == "daily_briefing" and "due today" in reply.text
    assert "daily_briefing" in handlers.HANDLERS and conversation.HANDLERS is handlers.HANDLERS


# ── hands-free turn handling (app.voice_ask) ────────────────────────────────

@pytest.fixture
def app_module(monkeypatch):
    import app
    calls = {"respond": 0}

    def fake_respond(text, state, now=None):
        calls["respond"] += 1
        from assistant.response_generator import Reply
        return Reply("It is 24°C.", "en", "weather")
    monkeypatch.setattr(app, "respond", fake_respond)
    monkeypatch.setattr(app, "synthesize", lambda text, lang: None)
    return app, calls


def last(gen):
    return list(gen)[-1]


# voice_turn / text_turn yield (chatbot, conv_id, state, textbox, status, audio, conv_list[, mic_upload])
CHATBOT, CONV_ID, STATE, STATUS, AUDIO, CONV_LIST = 0, 1, 2, 4, 5, 6


def test_voice_turn_with_no_clip_is_a_noop(app_module):
    app, calls = app_module
    out = last(app.voice_turn(None, [], None, ConversationState(), True))
    assert calls["respond"] == 0 and out[CONV_ID] is None


def test_voice_turn_transcription_failure_shows_the_error(app_module, monkeypatch):
    app, calls = app_module

    def silent(path, hint=None):
        raise STTError("I couldn't hear any speech in that recording — please try again")
    monkeypatch.setattr(app, "transcribe", silent)
    out = last(app.voice_turn("clip.webm", [], None, ConversationState(), True))
    assert calls["respond"] == 0
    assert "couldn't hear" in out[STATUS]
    assert out[CHATBOT] == []  # nothing was echoed into the chat


def test_voice_turn_always_speaks_even_with_autoplay_off(app_module, monkeypatch, tmp_path):
    """A spoken question always gets a spoken answer; the autoplay setting only gates typed replies."""
    app, calls = app_module
    wav = tmp_path / "r.wav"
    wav.write_bytes(b"RIFF1234")
    monkeypatch.setattr(app, "transcribe", lambda path, hint=None: Transcription("Is it raining?", "en"))
    monkeypatch.setattr(app, "synthesize", lambda text, lang: wav)
    outs = list(app.voice_turn("clip.webm", [], None, ConversationState(), False))  # autoplay OFF
    assert outs[-1][-1] is None       # the trailing yield clears the hidden upload
    final = outs[-2]
    assert calls["respond"] == 1
    assert final[CHATBOT][-1] == {"role": "assistant", "content": "It is 24°C."}
    assert final[AUDIO] == str(wav)
    assert isinstance(final[CONV_ID], int)  # a conversation was created on first message
    assert [c.title for c in final[CONV_LIST]] == ["Is it raining"]  # trailing "?" stripped by make_title


def test_text_turn_speaks_only_when_autoplay_is_on(app_module, monkeypatch, tmp_path):
    app, calls = app_module
    wav = tmp_path / "r.wav"
    wav.write_bytes(b"RIFF1234")
    synth_calls = []
    monkeypatch.setattr(app, "synthesize", lambda text, lang: synth_calls.append(1) or wav)

    off = last(app.text_turn("Is it raining?", [], None, ConversationState(), False))
    assert off[AUDIO] is None and synth_calls == []

    on = last(app.text_turn("Is it raining?", [], None, ConversationState(), True))
    assert on[AUDIO] == str(wav) and synth_calls == [1]
    assert calls["respond"] == 2


def test_text_turn_ignores_blank_input(app_module):
    app, calls = app_module
    out = last(app.text_turn("   ", [], None, ConversationState(), True))
    assert calls["respond"] == 0 and out[CONV_ID] is None


def test_conversation_is_reused_across_a_multi_turn_exchange(app_module):
    app, _ = app_module
    first = last(app.text_turn("Is it raining?", [], None, ConversationState(), False))
    conv_id, state = first[CONV_ID], first[STATE]
    second = last(app.text_turn("And tomorrow?", first[CHATBOT], conv_id, state, False))
    assert second[CONV_ID] == conv_id
    assert len(second[CHATBOT]) == 4  # 2 user + 2 assistant messages, same conversation

