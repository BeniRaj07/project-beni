import dataclasses
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import requests

from assistant.conversation import ConversationState, run_intent
from assistant.handlers import handle_football_news, handle_league_results, handle_league_table
from assistant.intent_classifier import IntentResult
from services import football, http, news
from services.http import RateLimitError, ServiceError
from tests.conftest import NEWS, PD_TEAMS, PL_MATCHES, PL_STANDINGS

NOW = datetime(2026, 9, 24, 10, 0, tzinfo=ZoneInfo("Asia/Kathmandu"))


@pytest.fixture
def fd_api(monkeypatch):
    monkeypatch.setattr(football, "settings", dataclasses.replace(football.settings, football_data_key="test"))
    calls = []

    def fake(service, url, params=None, headers=None, timeout=None):
        calls.append(url)
        if url.endswith("/standings"):
            return PL_STANDINGS
        if url.endswith("/PL/matches"):
            return PL_MATCHES
        if url.endswith("/PD/teams"):
            return PD_TEAMS
        if url.endswith("/teams"):
            return {"teams": []}
        if "/teams/81/matches" in url:
            return {"matches": [
                {"utcDate": "2026-09-21T19:00:00Z", "status": "FINISHED", "competition": {"name": "La Liga"},
                 "homeTeam": {"name": "FC Barcelona"}, "awayTeam": {"name": "Sevilla FC"},
                 "score": {"fullTime": {"home": 4, "away": 1}}}]}
        raise AssertionError(url)

    monkeypatch.setattr(football, "get_json", fake)
    return calls


def test_resolve_league_english_nepali_and_unsupported():
    assert football.resolve_league("Premier League") == "PL"
    assert football.resolve_league("प्रिमियर लिग") == "PL"
    assert football.resolve_league("laliga") == "PD"
    assert football.resolve_league("UCL") == "CL"
    assert football.resolve_league("Major League Soccer") is None


def test_results_and_fixtures_come_from_one_cached_request(fd_api):
    results = football.get_recent_results("PL")
    fixtures = football.get_upcoming_fixtures("PL")
    assert [m.home for m in results] == ["Liverpool FC", "Arsenal FC", "Manchester City FC"]   # newest first
    assert [m.home for m in fixtures] == ["Everton FC", "Chelsea FC"]                             # soonest first
    assert all(not m.finished for m in fixtures)
    assert sum(u.endswith("/PL/matches") for u in fd_api) == 1


def test_standings_only_total_table(fd_api):
    groups = football.get_standings("PL")
    assert len(groups) == 1 and groups[0][1][0].team == "Arsenal FC" and groups[0][1][0].points == 13


def test_league_table_handler_formats_real_data_only(fd_api):
    reply = handle_league_table(IntentResult(intent="league_table", league="EPL"), "", ConversationState(), NOW)
    assert "| 1 | Arsenal FC | 5 | 4 | 1 | 0 | +8 | **13** |" in reply.text
    assert "Arsenal FC are 1st with 13 points" in reply.spoken


def test_team_results_by_fuzzy_name(fd_api):
    assert football.find_team("Barcelona") == (81, "Barça")
    reply = handle_league_results(IntentResult(intent="league_results", team="Barcelona"), "", ConversationState(), NOW)
    assert "FC Barcelona **4 – 1** Sevilla FC" in reply.text and "Confirmed results" in reply.text


def test_unsupported_competition_is_explained(fd_api):
    reply = handle_league_table(IntentResult(intent="league_table", league="MLS"), "", ConversationState(), NOW)
    assert "I can only show data for" in reply.text


def test_missing_league_asks_a_question(fd_api):
    state = ConversationState()
    reply = handle_league_table(IntentResult(intent="league_table"), "show the table", state, NOW)
    assert "Which competition" in reply.text and state.pending["intent"] == "league_table"


def test_malformed_football_data_raises(monkeypatch):
    monkeypatch.setattr(football, "settings", dataclasses.replace(football.settings, football_data_key="test"))
    monkeypatch.setattr(football, "get_json", lambda *a, **k: {"unexpected": True})
    with pytest.raises(ServiceError):
        football.get_recent_results("PL")


def test_client_side_rate_limit(fd_api):
    for _ in range(10):
        football._limiter.acquire("x")
    with pytest.raises(RateLimitError):
        football.get_standings("SA")


def test_missing_key_gives_friendly_message(monkeypatch):
    monkeypatch.setattr(football, "settings", dataclasses.replace(football.settings, football_data_key=""))
    reply = run_intent(IntentResult(intent="league_table", league="PL"))
    assert "FOOTBALL_DATA_KEY" in reply.text


# ── HTTP layer: quota errors, timeouts, bad JSON ───────────────────────────

def fake_response(status, payload=None, bad_json=False):
    def _json():
        if bad_json:
            raise ValueError("bad json")
        return payload
    return SimpleNamespace(status_code=status, json=_json)


@pytest.mark.parametrize("status,exc,text", [
    (429, RateLimitError, "rate limit"), (403, ServiceError, "access denied"), (500, ServiceError, "HTTP 500")])
def test_http_errors_become_friendly(monkeypatch, status, exc, text):
    monkeypatch.setattr(http._session, "request", lambda *a, **k: fake_response(status, {}))
    with pytest.raises(exc) as e:
        http.get_json("Test", "https://example.com")
    assert text in e.value.user_message


def test_timeout_and_connection_errors(monkeypatch):
    def timeout(*a, **k):
        raise requests.Timeout()
    monkeypatch.setattr(http._session, "request", timeout)
    with pytest.raises(ServiceError, match="too long"):
        http.get_json("Test", "https://example.com")

    def offline(*a, **k):
        raise requests.ConnectionError()
    monkeypatch.setattr(http._session, "request", offline)
    with pytest.raises(ServiceError, match="connect"):
        http.get_json("Test", "https://example.com")


def test_unreadable_json(monkeypatch):
    monkeypatch.setattr(http._session, "request", lambda *a, **k: fake_response(200, bad_json=True))
    with pytest.raises(ServiceError, match="unreadable"):
        http.get_json("Test", "https://example.com")


def test_requests_always_have_a_timeout(monkeypatch):
    seen = {}

    def capture(method, url, **kw):
        seen.update(kw)
        return fake_response(200, {})
    monkeypatch.setattr(http._session, "request", capture)
    http.get_json("Test", "https://example.com")
    assert seen["timeout"] > 0


# ── news ────────────────────────────────────────────────────────────────────

@pytest.fixture
def news_api(monkeypatch):
    monkeypatch.setattr(news, "settings", dataclasses.replace(news.settings, news_api_key="secret-key"))
    captured = {}

    def fake(service, url, params=None, headers=None, timeout=None):
        captured.update(params=params, headers=headers)
        return NEWS
    monkeypatch.setattr(news, "get_json", fake)
    return captured


def test_news_excludes_american_football_and_hides_key(news_api):
    articles = news.fetch_football_articles("Premier League")
    assert [a.source for a in articles] == ["BBC Sport", "The Guardian"]
    assert "secret-key" not in str(news_api["params"]) and news_api["headers"]["X-Api-Key"] == "secret-key"
    assert "NOT NFL" in news_api["params"]["q"]


def test_news_query_cannot_inject_operators(news_api):
    news.fetch_football_articles('Arsenal") OR (anything')
    assert '")' not in news_api["params"]["q"].split(" AND ")[0][1:-1]


def test_news_handler_includes_sources_and_speaks_only_summary(news_api, monkeypatch):
    import assistant.handlers as h
    monkeypatch.setattr(h, "summarize_news", lambda arts, lang, topic: "Arsenal won the derby, reports say.")
    reply = handle_football_news(IntentResult(intent="football_news", league="Premier League"), "", ConversationState(), NOW)
    assert "not confirmed match results" in reply.text
    assert "[Arsenal beat Chelsea in London derby](https://example.com/a) — BBC Sport, 2026-09-23" in reply.text
    assert reply.spoken == "Arsenal won the derby, reports say." and "http" not in reply.spoken


def test_no_articles_is_reported(monkeypatch):
    monkeypatch.setattr(news, "fetch_football_articles", lambda topic=None, count=6: [])
    import assistant.handlers as h
    monkeypatch.setattr(h.news, "fetch_football_articles", lambda topic=None, count=6: [])
    reply = handle_football_news(IntentResult(intent="football_news", team="Arsenal"), "", ConversationState(), NOW)
    assert "couldn't find any recent football news about Arsenal" in reply.text
