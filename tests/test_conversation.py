"""End-to-end tests of the shared chat/voice backend with the LLM mocked."""
from datetime import datetime, timezone

import pytest

from assistant import conversation, handlers, intent_classifier
from assistant.conversation import ConversationState, respond
from services import reminders, tasks
from services.http import ServiceError

NOW = datetime(2026, 9, 24, 4, 15, tzinfo=timezone.utc)   # 10:00 in Kathmandu


@pytest.fixture
def llm_replies(monkeypatch):
    """Queue the JSON the classifier 'LLM' will return, in order."""
    queue = []
    monkeypatch.setattr(intent_classifier, "chat_json", lambda messages, **kw: queue.pop(0))
    return queue


def test_reminder_follow_up_question_and_answer(llm_replies):
    state = ConversationState()
    llm_replies.append({"intent": "create_reminder", "language": "en", "title": "call mum"})
    first = respond("Remind me to call mum", state, now=NOW)
    assert "What time" in first.text and state.pending["missing"] == "time"
    assert reminders.list_reminders() == []                      # nothing saved yet

    # "tomorrow at eight" — the classifier only returns the new fields; the title comes from the pending request
    llm_replies.append({"intent": "create_reminder", "language": "en", "date": "2026-09-25", "time": "08:00"})
    second = respond("tomorrow at eight", state, now=NOW)
    saved = reminders.list_reminders()
    assert len(saved) == 1 and saved[0].title == "call mum" and saved[0].local_due.hour == 8
    assert "Reminder saved" in second.text and second.data_changed and state.pending is None


def test_nepali_monthly_rent_reminder(llm_replies):
    llm_replies.append({"intent": "create_reminder", "language": "ne", "title": "घरभाडा तिर्ने",
                        "date": "2026-10-01", "time": "09:00", "recurrence": "monthly"})
    reply = respond("मलाई हरेक महिनाको १ गते बिहान ९ बजे घरभाडा तिर्न सम्झाउनु।", ConversationState(), now=NOW)
    assert reply.language == "ne" and "रिमाइन्डर सुरक्षित भयो" in reply.text and "हरेक महिना" in reply.text
    assert reminders.list_reminders()[0].recurrence == "monthly"


def test_time_without_date_uses_next_occurrence(llm_replies):
    llm_replies.append({"intent": "create_reminder", "title": "drink water", "time": "09:00"})   # 09:00 < 10:00 now
    respond("remind me to drink water at 9", ConversationState(), now=NOW)
    assert reminders.list_reminders()[0].local_due.day == 25   # tomorrow, not in the past


def test_list_and_delete_reminder_by_title(llm_replies):
    reminders.create_reminder("Submit assignment", datetime(2026, 9, 25).date(),
                              datetime(2026, 9, 25, 20).time(), now=NOW)
    llm_replies.append({"intent": "list_reminders"})
    assert "Submit assignment" in respond("What reminders do I have?", ConversationState(), now=NOW).text
    llm_replies.append({"intent": "delete_reminder", "title": "assignment"})
    assert "Deleted" in respond("Delete my assignment reminder", ConversationState(), now=NOW).text
    assert reminders.list_reminders() == []


def test_ambiguous_target_asks_which_one(llm_replies):
    tasks.create_task("Project report draft")
    tasks.create_task("Project report final")
    state = ConversationState()
    llm_replies.append({"intent": "complete_task", "title": "project report"})
    reply = respond("Mark my project report as completed", state, now=NOW)
    assert "several matches" in reply.text and state.pending["missing"] == "target_id"


def test_task_add_complete_and_list_in_nepali(llm_replies):
    llm_replies.append({"intent": "create_task", "language": "ne", "title": "प्रोजेक्ट रिपोर्ट बनाउने"})
    assert "थपियो" in respond("प्रोजेक्ट रिपोर्ट बनाउने काम थप।", ConversationState(), now=NOW).text
    task_id = tasks.list_tasks()[0].id
    llm_replies.append({"intent": "complete_task", "language": "ne", "target_id": task_id})
    assert "पूरा" in respond("मेरो रिपोर्टको काम पूरा भयो।", ConversationState(), now=NOW).text
    llm_replies.append({"intent": "list_tasks", "language": "ne", "status": "completed"})
    listing = respond("पूरा भएका काम देखाऊ", ConversationState(), now=NOW).text
    assert "प्रोजेक्ट रिपोर्ट बनाउने" in listing and "✅" in listing


def test_out_of_scope_is_refused(llm_replies):
    llm_replies.append({"intent": "out_of_scope", "language": "en"})
    assert "I can only help with" in respond("Write me a poem about cats", ConversationState(), now=NOW).text


def test_llm_outage_gives_friendly_message(monkeypatch):
    def down(*a, **k):
        raise ServiceError("Groq", "could not reach the language model")
    monkeypatch.setattr(intent_classifier, "chat_json", down)
    reply = respond("hello", ConversationState(), now=NOW)
    assert "Groq is unavailable right now" in reply.text


def test_unexpected_bug_does_not_crash_the_ui(llm_replies, monkeypatch):
    llm_replies.append({"intent": "list_tasks"})
    monkeypatch.setitem(handlers.HANDLERS, "list_tasks", lambda *a: 1 / 0)
    monkeypatch.setitem(conversation.HANDLERS, "list_tasks", lambda *a: 1 / 0)
    assert "Something went wrong" in respond("show tasks", ConversationState(), now=NOW).text


def test_greeting_uses_llm_in_users_language(llm_replies, monkeypatch):
    llm_replies.append({"intent": "greeting", "language": "ne"})
    monkeypatch.setattr(handlers, "generate_greeting", lambda text, lang, history: f"[{lang}] नमस्ते!")
    reply = respond("नमस्ते", ConversationState(), now=NOW)
    assert reply.text == "[ne] नमस्ते!" and reply.language == "ne"


def test_in_memory_history_is_kept(llm_replies):
    state = ConversationState()
    llm_replies.append({"intent": "out_of_scope"})
    respond("what is 2+2", state, now=NOW)
    assert [m["role"] for m in state.history] == ["user", "assistant"]


def test_state_round_trips_through_a_persisted_conversation(llm_replies, monkeypatch):
    """assistant.conversation's bridge to services.conversations: a follow-up question's pending
    state, last city and language all survive being saved to disk and reloaded (e.g. after
    switching to another conversation and back, or restarting the app)."""
    from services import conversations as convo
    from services import weather
    from tests.conftest import GEOCODE_KATHMANDU, forecast_payload
    monkeypatch.setattr(weather, "get_json", lambda service, url, **kw:
                        GEOCODE_KATHMANDU if "geocoding" in url else forecast_payload())

    conv = convo.new_conversation()
    state = conversation.state_from_conversation(conv)
    llm_replies.append({"intent": "weather", "city": "Pokhara"})
    reply = respond("What's the weather in Pokhara?", state, now=NOW)
    convo.append_message(conv.id, "user", "What's the weather in Pokhara?", state.last_language)
    convo.append_message(conv.id, "assistant", reply.text, reply.language)
    conversation.sync_conversation(conv.id, state)

    reloaded_state = conversation.state_from_conversation(convo.get_conversation(conv.id))
    assert reloaded_state.last_city == "Pokhara"
    assert reloaded_state.history == [{"role": "user", "content": "What's the weather in Pokhara?"},
                                      {"role": "assistant", "content": reply.text}]
