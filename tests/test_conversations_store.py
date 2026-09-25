"""Tests for services/conversations.py: the sidebar's persistence layer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services import conversations as convo

UTC = timezone.utc


def test_new_conversation_starts_untitled_and_empty():
    c = convo.new_conversation()
    assert c.title == "New chat" and c.messages == [] and c.language == "en"


def test_first_user_message_generates_a_short_title():
    c = convo.new_conversation()
    convo.append_message(c.id, "user", "Remind me to submit my assignment tomorrow at 8 PM", "en")
    assert convo.get_conversation(c.id).title == "Remind me to submit my assignment…"


def test_title_preserves_proper_noun_capitalization():
    c = convo.new_conversation()
    convo.append_message(c.id, "user", "Show the Premier League standings", "en")
    assert convo.get_conversation(c.id).title == "Show the Premier League standings"


def test_title_is_not_overwritten_by_later_messages():
    c = convo.new_conversation()
    convo.append_message(c.id, "user", "Hello there", "en")
    convo.append_message(c.id, "assistant", "Hi! How can I help?", "en")
    convo.append_message(c.id, "user", "What's the weather in Kathmandu?", "en")
    assert convo.get_conversation(c.id).title == "Hello there"


def test_nepali_title_is_not_forced_to_uppercase():
    c = convo.new_conversation()
    convo.append_message(c.id, "user", "मलाई भोलि बिहान ८ बजे सम्झाउनु", "ne")
    assert convo.get_conversation(c.id).title.startswith("मलाई")


def test_very_short_message_gets_no_trailing_ellipsis():
    c = convo.new_conversation()
    convo.append_message(c.id, "user", "Hi", "en")
    assert convo.get_conversation(c.id).title == "Hi"


def test_long_message_is_truncated_with_ellipsis():
    c = convo.new_conversation()
    long_msg = "Please remind me about the following very important thing every single day at nine"
    convo.append_message(c.id, "user", long_msg, "en")
    title = convo.get_conversation(c.id).title
    assert len(title) <= 49 and title.endswith("…")


def test_append_message_updates_language_and_timestamp():
    c = convo.new_conversation()
    before = convo.get_conversation(c.id).updated_at
    convo.append_message(c.id, "user", "नमस्ते", "ne")
    after = convo.get_conversation(c.id)
    assert after.language == "ne" and after.updated_at >= before
    assert [m.role for m in after.messages] == ["user"]


def test_messages_persist_across_a_fresh_read():
    c = convo.new_conversation()
    convo.append_message(c.id, "user", "Hello", "en")
    convo.append_message(c.id, "assistant", "Hi there!", "en")
    reloaded = convo.get_conversation(c.id)
    assert [(m.role, m.content) for m in reloaded.messages] == [("user", "Hello"), ("assistant", "Hi there!")]


def test_rename_and_delete():
    c = convo.new_conversation()
    convo.rename_conversation(c.id, "My reminders")
    assert convo.get_conversation(c.id).title == "My reminders"
    assert convo.delete_conversation(c.id) is True
    assert convo.get_conversation(c.id) is None
    assert convo.delete_conversation(c.id) is False  # already gone


def test_rename_is_trimmed_and_length_limited():
    c = convo.new_conversation()
    convo.rename_conversation(c.id, "  " + "x" * 100 + "  ")
    assert len(convo.get_conversation(c.id).title) == 48


def test_rename_blank_falls_back_to_new_chat():
    c = convo.new_conversation()
    convo.rename_conversation(c.id, "   ")
    assert convo.get_conversation(c.id).title == "New chat"


def test_search_matches_title_or_message_content():
    a = convo.new_conversation()
    convo.append_message(a.id, "user", "Remind me to call mum", "en")
    b = convo.new_conversation()
    convo.append_message(b.id, "user", "Show the Premier League standings", "en")

    assert [x.id for x in convo.search_conversations("mum")] == [a.id]
    assert [x.id for x in convo.search_conversations("premier")] == [b.id]
    assert [x.id for x in convo.search_conversations("MUM")] == [a.id]  # case-insensitive
    assert {x.id for x in convo.search_conversations("")} == {a.id, b.id}  # empty query = everything
    assert convo.search_conversations("xyz-nothing-matches") == []


def test_set_context_persists_pending_follow_up_and_last_city():
    c = convo.new_conversation()
    convo.set_context(c.id, language="en", last_city="Pokhara", pending={"intent": "weather"})
    reloaded = convo.get_conversation(c.id)
    assert reloaded.last_city == "Pokhara" and reloaded.pending == {"intent": "weather"}
    # explicit None clears a field; omitting it (the default `...`) leaves it untouched
    convo.set_context(c.id, pending=None)
    assert convo.get_conversation(c.id).pending is None
    assert convo.get_conversation(c.id).last_city == "Pokhara"


def test_list_conversations_sorted_newest_first():
    a = convo.new_conversation(now=datetime(2026, 9, 20, tzinfo=UTC))
    b = convo.new_conversation(now=datetime(2026, 9, 24, tzinfo=UTC))
    assert [x.id for x in convo.list_conversations()] == [b.id, a.id]


def test_group_conversations_today_yesterday_week_older():
    today = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)
    c_today = convo.new_conversation(now=today)
    c_yesterday = convo.new_conversation(now=today - timedelta(days=1))
    c_week = convo.new_conversation(now=today - timedelta(days=5))
    c_older = convo.new_conversation(now=today - timedelta(days=40))

    groups = convo.group_conversations(convo.list_conversations(), today=today.date())
    assert [c.id for c in groups["Today"]] == [c_today.id]
    assert [c.id for c in groups["Yesterday"]] == [c_yesterday.id]
    assert [c.id for c in groups["Previous 7 Days"]] == [c_week.id]
    assert [c.id for c in groups["Older"]] == [c_older.id]


def test_empty_groups_are_omitted():
    convo.new_conversation()
    groups = convo.group_conversations(convo.list_conversations())
    assert "Yesterday" not in groups and "Older" not in groups
