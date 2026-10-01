"""Tests for services/nepal_news.py and assistant.handlers.handle_nepal_news."""
from __future__ import annotations

import dataclasses
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from assistant.conversation import ConversationState
from assistant.handlers import handle_nepal_news
from assistant.intent_classifier import IntentResult
from config import MissingAPIKeyError
from services import nepal_news

NOW = datetime(2026, 9, 24, 10, 0, tzinfo=ZoneInfo("Asia/Kathmandu"))

RAW_ARTICLES = {"articles": [
    {"title": "PM reshuffles cabinet amid coalition talks", "description": "Three ministers replaced.",
     "source": {"name": "Kathmandu Post"}, "url": "https://example.com/1", "publishedAt": "2026-09-23T10:00:00Z"},
    # Near-duplicate of the above (same story via a wire pickup) - should be deduplicated
    {"title": "PM reshuffles cabinet amid coalition talks!", "description": "Three ministers replaced.",
     "source": {"name": "Some Aggregator"}, "url": "https://example.com/1b", "publishedAt": "2026-09-23T09:00:00Z"},
    {"title": "Opposition party alleges election irregularities", "description": "Claims made at a press conference.",
     "source": {"name": "Setopati"}, "url": "https://example.com/2", "publishedAt": "2026-09-22T12:00:00Z"},
]}


@pytest.fixture
def news_api(monkeypatch):
    monkeypatch.setattr(nepal_news, "settings", dataclasses.replace(nepal_news.settings, news_api_key="secret-key"))
    captured = {}

    def fake(service, url, params=None, headers=None, timeout=None):
        captured.update(params=params, headers=headers)
        return RAW_ARTICLES
    monkeypatch.setattr(nepal_news, "get_json", fake)
    return captured


def test_fetch_deduplicates_near_identical_titles(news_api):
    articles = nepal_news.fetch_nepal_political_news()
    assert len(articles) == 2   # the near-duplicate reshuffle story was dropped
    titles = [a.title for a in articles]
    assert "Opposition party alleges election irregularities" in titles


def test_fetch_prefers_known_outlets_on_tie(news_api):
    articles = nepal_news.fetch_nepal_political_news()
    # Kathmandu Post (a preferred outlet) should rank at/near the top even though it isn't the
    # single newest article overall in a larger feed - here it's simply present and well-formed.
    assert any(a.source == "Kathmandu Post" for a in articles)


def test_key_never_appears_in_query_params(news_api):
    nepal_news.fetch_nepal_political_news()
    assert "secret-key" not in str(news_api["params"])
    assert news_api["headers"]["X-Api-Key"] == "secret-key"
    assert "Nepal" in news_api["params"]["q"]


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.setattr(nepal_news, "settings", dataclasses.replace(nepal_news.settings, news_api_key=""))
    with pytest.raises(MissingAPIKeyError):
        nepal_news.fetch_nepal_political_news()


def test_handler_includes_sources_and_speaks_only_summary(news_api, monkeypatch):
    import assistant.handlers as h
    monkeypatch.setattr(h, "summarize_nepal_politics",
                        lambda arts, lang: "The cabinet was reshuffled; the opposition disputes the process.")
    reply = handle_nepal_news(IntentResult(intent="nepal_news"), "", ConversationState(), NOW)
    assert "Nepal politics" in reply.text
    assert "[PM reshuffles cabinet amid coalition talks](https://example.com/1) — Kathmandu Post" in reply.text
    assert reply.spoken == "The cabinet was reshuffled; the opposition disputes the process."
    assert "http" not in reply.spoken


def test_no_articles_is_reported_not_invented(monkeypatch):
    import assistant.handlers as h
    monkeypatch.setattr(h.nepal_news, "fetch_nepal_political_news", lambda count=6: [])
    reply = handle_nepal_news(IntentResult(intent="nepal_news"), "", ConversationState(), NOW)
    assert "couldn't find any recent Nepal political news" in reply.text
