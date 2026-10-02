"""The LLM responsibility split, traced end to end through the real classifier, router and handlers.

Groq  = intent classification (chat_json)       -> exactly 1 call per message
Claude = final response generation (chat_text)  -> exactly 1 call per generated reply
Only the two network clients are faked; nothing here touches the network or needs keys.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from assistant.conversation import ConversationState, respond
from services import claude, llm, nepal_news, personal_context
from services.news import Article

NOW = datetime(2026, 9, 24, 4, 15, tzinfo=timezone.utc)


class Fakes:
    """Records every Groq and Claude call; Groq replies come from a queue of JSON objects."""

    def __init__(self):
        self.classifications: list[dict] = []     # queued Groq replies
        self.groq_calls: list[dict] = []
        self.claude_calls: list[dict] = []
        self.claude_reply = "Claude says hello."
        self.claude_error: Exception | None = None


@pytest.fixture
def fakes(monkeypatch):
    f = Fakes()

    class GroqCompletions:
        def create(self, **kw):
            f.groq_calls.append(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps(f.classifications.pop(0))))])

    class ClaudeMessages:
        def create(self, **kw):
            f.claude_calls.append(kw)
            if f.claude_error:
                raise f.claude_error
            return SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(type="text", text=f.claude_reply)])

    monkeypatch.setattr(llm, "get_groq_client",
                        lambda: SimpleNamespace(chat=SimpleNamespace(completions=GroqCompletions())))
    monkeypatch.setattr(claude, "get_client", lambda: SimpleNamespace(messages=ClaudeMessages()))
    monkeypatch.setattr(llm, "settings", dataclasses.replace(llm.settings, anthropic_api_key="sk-ant-test",
                                                             llm_provider=""))
    monkeypatch.setattr(claude, "settings", llm.settings)
    return f


def _groq_prompt(f: Fakes, i: int = 0) -> str:
    return "\n".join(m["content"] for m in f.groq_calls[i]["messages"])


def test_hello_is_classified_by_groq_and_answered_by_claude(fakes):
    fakes.classifications.append({"intent": "greeting", "confidence": 0.97, "language": "en"})
    fakes.claude_reply = "Hey there! Lovely to hear from you."
    reply = respond("Hello", ConversationState(), now=NOW)
    assert reply.text == "Hey there! Lovely to hear from you." and reply.intent == "greeting"
    assert len(fakes.groq_calls) == 1 and len(fakes.claude_calls) == 1       # the cost rule
    assert "intent classifier" in _groq_prompt(fakes)                         # Groq got the classifier prompt
    system = fakes.claude_calls[0]["system"]
    assert "Intent chosen by the application: greeting" in system             # Claude trusts the routing...
    assert "intent classifier" not in system.lower().replace("intent classification", "")  # ...and never classifies


def test_personal_question_uses_only_retrieved_facts(fakes):
    personal_context.remember("current project", "a bilingual voice assistant called Awaaz")
    personal_context.remember("favourite colour", "green")
    fakes.classifications.append({"intent": "personal_query", "confidence": 0.94})
    fakes.claude_reply = "You're building a bilingual voice assistant called Awaaz."
    reply = respond("What project am I working on?", ConversationState(), now=NOW)
    assert "Awaaz" in reply.text and reply.intent == "personal_query"
    assert len(fakes.groq_calls) == 1 and len(fakes.claude_calls) == 1
    sent = json.dumps(fakes.claude_calls[0]["messages"])
    assert "bilingual voice assistant called Awaaz" in sent
    assert "green" not in sent                                                # only RELEVANT context is sent
    assert "ONLY the saved facts" in fakes.claude_calls[0]["system"]


def test_personal_question_without_saved_facts_makes_no_claude_call(fakes):
    fakes.classifications.append({"intent": "personal_query"})
    reply = respond("What's my email?", ConversationState(), now=NOW)
    assert "don't have that saved" in reply.text
    assert len(fakes.groq_calls) == 1 and fakes.claude_calls == []            # nothing to invent from


def test_general_question_goes_straight_to_claude(fakes):
    fakes.classifications.append({"intent": "general_ai", "confidence": 0.91})
    fakes.claude_reply = "Quantum mechanics describes matter at very small scales."
    reply = respond("Explain quantum mechanics.", ConversationState(), now=NOW)
    assert reply.text.startswith("Quantum mechanics") and reply.intent == "general_ai"
    assert len(fakes.groq_calls) == 1 and len(fakes.claude_calls) == 1
    assert "voice" in fakes.claude_calls[0]["system"].lower()                  # voice-first guidance is centralised


def test_nepal_news_is_summarised_from_the_service_data_only(fakes, monkeypatch):
    arts = [Article("PM reshuffles cabinet", "Three ministers replaced.", "Kathmandu Post",
                    "https://example.com/1", datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc))]
    monkeypatch.setattr(nepal_news, "fetch_nepal_political_news", lambda: arts)
    fakes.classifications.append({"intent": "nepal_news", "confidence": 0.96})
    fakes.claude_reply = "According to Kathmandu Post, the prime minister replaced three ministers."
    reply = respond("What's the latest political news in Nepal?", ConversationState(), now=NOW)
    assert "Kathmandu Post" in reply.text and reply.intent == "nepal_news"
    assert len(fakes.groq_calls) == 1 and len(fakes.claude_calls) == 1
    assert "PM reshuffles cabinet" in json.dumps(fakes.claude_calls[0]["messages"])
    assert "never state" in fakes.claude_calls[0]["system"].lower() or "never stating" in fakes.claude_calls[0]["system"]


def test_nepal_news_with_no_data_never_asks_claude_to_make_something_up(fakes, monkeypatch):
    monkeypatch.setattr(nepal_news, "fetch_nepal_political_news", lambda: [])
    fakes.classifications.append({"intent": "nepal_news"})
    reply = respond("Nepal politics update", ConversationState(), now=NOW)
    assert reply.intent == "nepal_news" and fakes.claude_calls == []


def test_follow_up_carries_the_previous_turns_to_claude(fakes):
    state = ConversationState()
    fakes.classifications.append({"intent": "general_ai"})
    fakes.claude_reply = "Albert Einstein was a theoretical physicist."
    respond("Who was Albert Einstein?", state, now=NOW)

    fakes.classifications.append({"intent": "general_ai"})
    fakes.claude_reply = "He was born on 14 March 1879."
    respond("When was he born?", state, now=NOW)

    msgs = fakes.claude_calls[1]["messages"]
    assert msgs[0] == {"role": "user", "content": "Who was Albert Einstein?"}   # history, user-first
    assert msgs[1]["role"] == "assistant" and "physicist" in msgs[1]["content"]
    assert msgs[-1] == {"role": "user", "content": "When was he born?"}
    assert len(fakes.groq_calls) == 2 and len(fakes.claude_calls) == 2


def test_history_sent_to_claude_is_bounded(fakes):
    state = ConversationState(history=[{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
                                       for i in range(40)])
    fakes.classifications.append({"intent": "general_ai"})
    respond("Tell me more about that.", state, now=NOW)
    assert len(fakes.claude_calls[0]["messages"]) <= 11                          # 10 history turns + current


def test_claude_failure_is_a_friendly_message_not_a_crash(fakes):
    import anthropic
    import httpx
    fakes.claude_error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
    fakes.classifications.append({"intent": "general_ai"})
    reply = respond("Explain quantum mechanics.", ConversationState(), now=NOW)
    assert "Claude is unavailable right now" in reply.text and "could not reach" in reply.text
    assert len(fakes.groq_calls) == 1                                           # classification still worked


def test_invalid_claude_key_is_reported_without_leaking_the_key(fakes):
    import anthropic
    import httpx
    resp = httpx.Response(401, request=httpx.Request("POST", "https://x"))
    fakes.claude_error = anthropic.AuthenticationError("bad key sk-ant-test", response=resp, body=None)
    fakes.classifications.append({"intent": "greeting"})
    reply = respond("Hello", ConversationState(), now=NOW)
    assert "ANTHROPIC_API_KEY was rejected" in reply.text and "sk-ant-test" not in reply.text


def test_chat_json_only_calls_groq(fakes):
    fakes.classifications.append({"intent": "weather"})
    assert llm.chat_json([{"role": "user", "content": "weather?"}]) == {"intent": "weather"}
    assert len(fakes.groq_calls) == 1 and fakes.claude_calls == []


def test_without_an_anthropic_key_replies_fall_back_to_groq(monkeypatch):
    monkeypatch.setattr(llm, "settings", dataclasses.replace(llm.settings, anthropic_api_key="", llm_provider=""))
    assert llm.use_claude_for_responses() is False
    monkeypatch.setattr(llm, "settings", dataclasses.replace(llm.settings, anthropic_api_key="k", llm_provider="groq"))
    assert llm.use_claude_for_responses() is False                              # explicit override


def test_malformed_classifier_output_does_not_crash(fakes):
    fakes.classifications.append({"intent": "no_such_intent", "confidence": "high"})
    reply = respond("asdf", ConversationState(), now=NOW)
    assert reply.intent in ("out_of_scope", "clarify") and fakes.claude_calls == []


def test_logs_show_both_providers_without_private_data(fakes, caplog):
    personal_context.remember("email", "secret@example.com")
    fakes.classifications.append({"intent": "personal_query", "confidence": 0.94})
    with caplog.at_level(logging.INFO):
        respond("What's my email?", ConversationState(), now=NOW)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "[IntentClassifier] provider=groq intent=personal_query confidence=0.94" in text
    assert "[ResponseGenerator] provider=anthropic" in text and "status=success" in text
    assert "secret@example.com" not in text and "sk-ant-test" not in text and "What's my email" not in text
