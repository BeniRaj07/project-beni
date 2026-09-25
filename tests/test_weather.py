from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from assistant.handlers import handle_weather
from assistant.conversation import ConversationState
from assistant.intent_classifier import IntentResult
from services import weather
from services.http import ServiceError
from tests.conftest import GEOCODE_KATHMANDU, forecast_payload

NOW = datetime(2026, 9, 24, 14, 5, tzinfo=ZoneInfo("Asia/Kathmandu"))


def patch_api(monkeypatch, geocode=GEOCODE_KATHMANDU, forecast=None):
    def fake_get_json(service, url, params=None, headers=None, timeout=None):
        return geocode if "geocoding" in url else (forecast or forecast_payload())
    monkeypatch.setattr(weather, "get_json", fake_get_json)


def test_current_rain_detected(monkeypatch):
    patch_api(monkeypatch, forecast=forecast_payload(rain_now=1.2, code=61))
    rep = weather.get_weather_report("Kathmandu")
    assert rep.raining_now and rep.location.name == "Kathmandu" and rep.timezone == "Asia/Kathmandu"


def test_not_raining_now_but_rain_forecast_tomorrow(monkeypatch):
    patch_api(monkeypatch, forecast=forecast_payload(rain_now=0.0, code=2, tomorrow_prob=80))
    rep = weather.get_weather_report("Kathmandu")
    assert not rep.raining_now
    assert rep.forecast_for(date(2026, 9, 25)).rain_expected
    assert rep.rest_of_today_rain_probability == 65


def test_current_answer_keeps_now_and_forecast_separate(monkeypatch):
    patch_api(monkeypatch)
    it = IntentResult(intent="weather", city="Kathmandu", weather_when="current")
    reply = handle_weather(it, "Is it raining in Kathmandu right now?", ConversationState(), NOW)
    assert "not raining right now" in reply.text
    assert "Forecast for the rest of today" in reply.text


def test_tomorrow_answer_is_labelled_as_forecast(monkeypatch):
    patch_api(monkeypatch)
    it = IntentResult(intent="weather", city="Kathmandu", date=date(2026, 9, 25), weather_when="forecast")
    reply = handle_weather(it, "Will it rain tomorrow?", ConversationState(), NOW)
    assert "Rain is likely" in reply.text and "not current conditions" in reply.text
    assert "currently" not in reply.text


def test_nepali_weather_reply(monkeypatch):
    patch_api(monkeypatch, forecast=forecast_payload(rain_now=2.0, code=63))
    it = IntentResult(intent="weather", city="Kathmandu", language="ne")
    reply = handle_weather(it, "काठमाडौंमा अहिले पानी परिरहेको छ?", ConversationState(), NOW)
    assert "अहिले पानी परिरहेको छ" in reply.text and reply.language == "ne"


def test_follow_up_uses_previous_city(monkeypatch):
    patch_api(monkeypatch)
    state = ConversationState(last_city="Kathmandu")
    reply = handle_weather(IntentResult(intent="weather", date=date(2026, 9, 25)), "Will it rain tomorrow?", state, NOW)
    assert "Kathmandu" in reply.text


def test_asks_for_city_when_unknown():
    state = ConversationState()
    reply = handle_weather(IntentResult(intent="weather"), "What's the weather?", state, NOW)
    assert "Which city" in reply.text and state.pending["missing"] == "city"


def test_unknown_city(monkeypatch):
    patch_api(monkeypatch, geocode={"generationtime_ms": 0.5})
    reply = handle_weather(IntentResult(intent="weather", city="Atlantisville"), "", ConversationState(), NOW)
    assert "couldn't find" in reply.text


def test_geocoding_prefers_nepal_match_over_top_ranked_foreign_namesake(monkeypatch):
    multi = {"results": [
        {"name": "Birganj", "country": "France", "admin1": "", "latitude": 48.0, "longitude": 2.0},
        {"name": "Birgunj", "country": "Nepal", "admin1": "Madhesh Province", "latitude": 27.0, "longitude": 84.87},
    ]}
    patch_api(monkeypatch, geocode=multi, forecast=forecast_payload())
    rep = weather.get_weather_report("Birgunj")
    assert rep.location.country == "Nepal" and rep.location.name == "Birgunj"


def test_malformed_weather_response_raises_service_error(monkeypatch):
    patch_api(monkeypatch, forecast={"current": {"time": "2026-09-24T14:00"}})   # missing fields
    with pytest.raises(ServiceError):
        weather.get_weather_report("Kathmandu")


def test_forecast_beyond_range(monkeypatch):
    patch_api(monkeypatch)
    it = IntentResult(intent="weather", city="Kathmandu", date=date(2026, 10, 20))
    assert "7 days" in handle_weather(it, "", ConversationState(), NOW).text
