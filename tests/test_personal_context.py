"""Tests for services/personal_context.py: the personal-memory store and its retrieval."""
from __future__ import annotations

import pytest

from services import personal_context as pc


def test_remember_creates_a_fact():
    fact = pc.remember("current project", "a bilingual voice assistant called Awaaz", category="project")
    assert fact.id == 1 and fact.category == "project"
    assert pc.get_fact(1).content == "a bilingual voice assistant called Awaaz"


def test_remember_same_title_updates_instead_of_duplicating():
    pc.remember("email", "old@example.com")
    fact = pc.remember("email", "new@example.com")
    assert fact.id == 1                      # same fact, not a second one
    assert len(pc.list_facts()) == 1
    assert pc.get_fact(1).content == "new@example.com"


def test_remember_rejects_empty_content():
    with pytest.raises(pc.PersonalContextError):
        pc.remember("email", "")


def test_remember_defaults_title_from_content_when_missing():
    fact = pc.remember("", "I study Computer Science at Kathmandu University")
    assert fact.title.startswith("I study Computer Science")


def test_list_facts_filters_by_category_and_sorts_newest_first():
    pc.remember("major", "Computer Science", category="education")
    pc.remember("supervisor", "Dr. Sharma", category="person")
    pc.remember("thesis topic", "voice assistants", category="research")
    assert [f.title for f in pc.list_facts(category="person")] == ["supervisor"]
    assert [f.title for f in pc.list_facts()][0] == "thesis topic"   # most recently saved first


def test_delete_fact():
    fact = pc.remember("nickname", "Beni")
    assert pc.delete_fact(fact.id) is True
    assert pc.get_fact(fact.id) is None
    assert pc.delete_fact(fact.id) is False   # already gone


def test_search_facts_finds_relevant_fact_by_word_overlap():
    pc.remember("current project", "a bilingual voice assistant called Awaaz", category="project")
    pc.remember("favourite food", "momo", category="preference")
    results = pc.search_facts("what project am I working on?")
    assert results and results[0].title == "current project"


def test_search_facts_returns_nothing_for_unrelated_question():
    pc.remember("favourite food", "momo", category="preference")
    assert pc.search_facts("what is the capital of France?") == []


def test_search_facts_fuzzy_matches_near_miss_titles():
    pc.remember("supervisor", "Dr. Sharma", category="person")
    results = pc.search_facts("who is my supervisr")     # typo, no exact word overlap on content
    assert results and results[0].title == "supervisor"


def test_search_facts_respects_limit():
    for i in range(5):
        pc.remember(f"project {i}", "a voice assistant project", category="project")
    assert len(pc.search_facts("tell me about my project", limit=2)) == 2
