from datetime import datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from assistant import intent_classifier
from assistant.intent_classifier import IntentResult, classify_intent, has_devanagari
from services import llm
from services.http import ServiceError

NOW = datetime(2026, 9, 24, 10, 0, tzinfo=ZoneInfo("Asia/Kathmandu"))


def fake_llm(monkeypatch, payload):
    calls = []

    def _chat_json(messages, **kw):
        calls.append(messages)
        return payload

    monkeypatch.setattr(intent_classifier, "chat_json", _chat_json)
    return calls


@pytest.mark.parametrize("text,payload,expected", [
    ("Remind me to submit my assignment tomorrow at 8 PM",
     {"intent": "create_reminder", "language": "en", "title": "submit my assignment",
      "date": "2026-09-25", "time": "20:00", "recurrence": "none"}, ("create_reminder", "en")),
    ("मलाई भोलि बिहान ८ बजे असाइनमेन्ट बुझाउन सम्झाउनु।",
     {"intent": "create_reminder", "language": "ne", "title": "असाइनमेन्ट बुझाउने",
      "date": "2026-09-25", "time": "08:00"}, ("create_reminder", "ne")),
    ("mero reminder haru dekhau",  # Romanized Nepali
     {"intent": "list_reminders", "language": "ne"}, ("list_reminders", "ne")),
    ("What is the weather in Kathmandu?", {"intent": "weather", "city": "Kathmandu"}, ("weather", "en")),
    ("काठमाडौंमा अहिले पानी परिरहेको छ?",
     {"intent": "weather", "language": "en", "city": "Kathmandu", "weather_when": "current"}, ("weather", "ne")),
    ("Show the Premier League standings", {"intent": "league_table", "league": "Premier League"}, ("league_table", "en")),
    ("यो महिनाको कामको सूची देखाऊ।", {"intent": "list_tasks", "language": "ne"}, ("list_tasks", "ne")),
    ("Who won the Super Bowl?", {"intent": "out_of_scope"}, ("out_of_scope", "en")),
])
def test_classify_english_and_nepali(monkeypatch, text, payload, expected):
    fake_llm(monkeypatch, payload)
    result = classify_intent(text, now=NOW)
    assert (result.intent, result.language) == expected


def test_devanagari_forces_nepali_even_if_model_says_english(monkeypatch):
    fake_llm(monkeypatch, {"intent": "greeting", "language": "en"})
    assert classify_intent("नमस्ते", now=NOW).language == "ne"
    assert has_devanagari("नमस्ते") and not has_devanagari("namaste")


def test_entities_are_validated_and_coerced():
    r = IntentResult.model_validate({
        "intent": "news_summary",           # legacy name from the original project
        "date": "2026-02-30",               # impossible date -> None, not a crash
        "time": "२०:३०",                     # Nepali digits
        "recurrence": "every month",
        "language": "Nepali",
        "target_id": "7",
        "month": "2026-09",
        "timezone": "Mars/Olympus",         # invalid tz -> None
        "city": "null",
    })
    assert r.intent == "football_news"
    assert r.date is None and r.time == time(20, 30)
    assert r.recurrence == "monthly" and r.language == "ne"
    assert r.target_id == 7 and r.month == "2026-09" and r.timezone is None and r.city is None


def test_unknown_intent_becomes_out_of_scope():
    assert IntentResult.model_validate({"intent": "write_my_essay"}).intent == "out_of_scope"


def test_context_includes_pending_question_and_existing_items(monkeypatch):
    calls = fake_llm(monkeypatch, {"intent": "create_reminder", "time": "08:00", "date": "2026-09-25"})
    pending = {"intent": "create_reminder", "missing": "time", "fields": {"title": "call mum"}}
    classify_intent("tomorrow at eight", now=NOW, pending=pending, reminders=[(3, "Pay rent")])
    user_msg = calls[0][1]["content"]
    assert "pending_question" in user_msg and "call mum" in user_msg and "Pay rent" in user_msg
    assert "tomorrow at eight" in user_msg


def test_parse_json_object_tolerates_fences_and_chatter():
    assert llm.parse_json_object('Sure!\n```json\n{"intent": "greeting"}\n```') == {"intent": "greeting"}
    with pytest.raises(ValueError):
        llm.parse_json_object("I cannot help with that")


def _text_response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def test_malformed_llm_output_retries_then_raises_service_error(monkeypatch):
    replies = iter(["not json", "still not json"])

    class FakeMessages:
        def create(self, **kw):
            return _text_response(next(replies))

    monkeypatch.setattr(llm, "get_anthropic_client", lambda: SimpleNamespace(messages=FakeMessages()))
    with pytest.raises(ServiceError):
        llm.chat_json([{"role": "user", "content": "hi"}])


def test_malformed_first_reply_recovers_on_retry(monkeypatch):
    replies = iter(["oops", '{"intent": "weather", "city": "Pokhara"}'])

    class FakeMessages:
        def create(self, **kw):
            return _text_response(next(replies))

    monkeypatch.setattr(llm, "get_anthropic_client", lambda: SimpleNamespace(messages=FakeMessages()))
    assert llm.chat_json([{"role": "user", "content": "x"}])["city"] == "Pokhara"


def _fake_client(monkeypatch, handler):
    calls = []

    class FakeMessages:
        def create(self, **kw):
            calls.append(kw)
            return handler(kw)

    monkeypatch.setattr(llm, "get_anthropic_client", lambda: SimpleNamespace(messages=FakeMessages()))
    return calls


def test_system_message_is_split_out_for_claude(monkeypatch):
    calls = _fake_client(monkeypatch, lambda kw: _text_response('{"intent": "greeting"}'))
    llm.chat_json([{"role": "system", "content": "You classify intents."}, {"role": "user", "content": "hi"}])
    assert calls[0]["system"].startswith("You classify intents.")
    assert calls[0]["messages"] == [{"role": "user", "content": "hi"}]


def test_empty_text_is_an_error(monkeypatch):
    _fake_client(monkeypatch, lambda kw: _text_response(""))
    with pytest.raises(ServiceError, match="empty"):
        llm.chat_text([{"role": "user", "content": "hi"}])
