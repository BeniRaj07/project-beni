"""Shared fixtures. Every external service (Groq, Gemini, Open-Meteo, Football-Data, NewsAPI)
is mocked — the tests never touch the network and need no API keys."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Must happen before `config` is imported: keep test files out of the real data/ and logs/ folders
_TMP = Path(tempfile.mkdtemp(prefix="assistant-tests-"))
os.environ["AUDIO_DIR"] = str(_TMP / "audio")
os.environ["LOG_DIR"] = str(_TMP / "logs")
os.environ["DATA_DIR"] = str(_TMP / "unused-data")
os.environ["APP_TIMEZONE"] = "Asia/Kathmandu"

from database import stores  # noqa: E402
from services import football, news, weather  # noqa: E402


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    """Fresh, isolated JSON data files (conversations/reminders/tasks/settings) for every test."""
    stores.set_data_dir(tmp_path / "data")
    yield tmp_path / "data"


@pytest.fixture(autouse=True)
def clear_caches():
    for c in (weather._cache, football._cache, news._cache):
        c.clear()
    football._limiter._calls.clear()
    yield


# ── canned API payloads ─────────────────────────────────────────────────────

GEOCODE_KATHMANDU = {"results": [{"name": "Kathmandu", "country": "Nepal", "admin1": "Bagmati Province",
                                  "latitude": 27.70169, "longitude": 85.3206}]}


def forecast_payload(*, rain_now: float = 0.0, code: int = 2, tomorrow_prob: int = 80, tomorrow_sum: float = 6.4):
    return {
        "timezone": "Asia/Kathmandu",
        "current": {"time": "2026-09-24T14:00", "temperature_2m": 24.3, "apparent_temperature": 25.1,
                    "precipitation": rain_now, "rain": rain_now, "showers": 0.0, "weather_code": code,
                    "wind_speed_10m": 6.8},
        "hourly": {"time": ["2026-09-24T13:00", "2026-09-24T14:00", "2026-09-24T18:00", "2026-09-25T09:00"],
                   "precipitation_probability": [10, 20, 65, 90]},
        "daily": {"time": ["2026-09-24", "2026-09-25", "2026-09-26"],
                  "weather_code": [2, 63, 1],
                  "temperature_2m_max": [27.0, 24.0, 28.0], "temperature_2m_min": [17.0, 16.5, 18.0],
                  "precipitation_sum": [0.4, tomorrow_sum, 0.0],
                  "precipitation_probability_max": [65, tomorrow_prob, 5]},
    }


def fd_match(utc, home, away, hs, as_, status="FINISHED", comp="Premier League"):
    return {"utcDate": utc, "status": status, "competition": {"name": comp},
            "homeTeam": {"name": home}, "awayTeam": {"name": away},
            "score": {"fullTime": {"home": hs, "away": as_}}}


PL_MATCHES = {"matches": [
    fd_match("2026-09-13T14:00:00Z", "Arsenal FC", "Chelsea FC", 2, 1),
    fd_match("2026-09-20T16:30:00Z", "Liverpool FC", "Everton FC", 3, 0),
    fd_match("2026-09-06T14:00:00Z", "Manchester City FC", "Brentford FC", 1, 1),
    fd_match("2099-10-03T14:00:00Z", "Chelsea FC", "Liverpool FC", None, None, status="TIMED"),
    fd_match("2099-09-27T11:30:00Z", "Everton FC", "Arsenal FC", None, None, status="SCHEDULED"),
]}

PL_STANDINGS = {"standings": [
    {"type": "TOTAL", "group": None, "table": [
        {"position": 1, "team": {"name": "Arsenal FC"}, "playedGames": 5, "won": 4, "draw": 1, "lost": 0,
         "goalDifference": 8, "points": 13},
        {"position": 2, "team": {"name": "Liverpool FC"}, "playedGames": 5, "won": 4, "draw": 0, "lost": 1,
         "goalDifference": 6, "points": 12},
        {"position": 3, "team": {"name": "Chelsea FC"}, "playedGames": 5, "won": 3, "draw": 1, "lost": 1,
         "goalDifference": 3, "points": 10}]},
    {"type": "HOME", "table": []},
]}

PD_TEAMS = {"teams": [{"id": 81, "name": "FC Barcelona", "shortName": "Barça", "tla": "FCB"},
                      {"id": 86, "name": "Real Madrid CF", "shortName": "Real Madrid", "tla": "RMA"}]}

NEWS = {"articles": [
    {"title": "Arsenal beat Chelsea in London derby", "description": "Two late goals settled it.",
     "source": {"name": "BBC Sport"}, "url": "https://example.com/a", "publishedAt": "2026-09-23T18:00:00Z"},
    {"title": "NFL: Chiefs quarterback throws four touchdowns", "description": "American football.",
     "source": {"name": "ESPN"}, "url": "https://example.com/nfl", "publishedAt": "2026-09-23T17:00:00Z"},
    {"title": "Salah signs new Liverpool contract", "description": "The forward commits his future.",
     "source": {"name": "The Guardian"}, "url": "https://example.com/b", "publishedAt": "2026-09-22T09:00:00Z"},
]}
