"""Open-Meteo weather: current conditions and a 7-day forecast, in the location's own timezone.

The key design rule: "is it raining NOW" comes only from the `current` block, and "will it rain"
comes only from the forecast blocks, so the two are never confused.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

from config import settings
from services.http import ServiceError, TTLCache, get_json

log = logging.getLogger(__name__)
_cache = TTLCache()

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes (original table, completed and translated)
WEATHER_CODES = {
    0: ("clear sky", "सफा आकाश"), 1: ("mainly clear", "प्रायः सफा"), 2: ("partly cloudy", "आंशिक बादल"),
    3: ("overcast", "बादल ढाकिएको"), 45: ("fog", "हुस्सु"), 48: ("depositing rime fog", "तुसारोसहितको हुस्सु"),
    51: ("light drizzle", "हल्का सिमसिमे पानी"), 53: ("moderate drizzle", "मध्यम सिमसिमे पानी"),
    55: ("dense drizzle", "बाक्लो सिमसिमे पानी"), 56: ("light freezing drizzle", "हल्का चिसो सिमसिमे पानी"),
    57: ("dense freezing drizzle", "बाक्लो चिसो सिमसिमे पानी"), 61: ("slight rain", "हल्का वर्षा"),
    63: ("moderate rain", "मध्यम वर्षा"), 65: ("heavy rain", "भारी वर्षा"),
    66: ("light freezing rain", "हल्का चिसो वर्षा"), 67: ("heavy freezing rain", "भारी चिसो वर्षा"),
    71: ("slight snow", "हल्का हिमपात"), 73: ("moderate snow", "मध्यम हिमपात"), 75: ("heavy snow", "भारी हिमपात"),
    77: ("snow grains", "हिउँका कण"), 80: ("rain showers", "हल्का झरी"), 81: ("moderate rain showers", "मध्यम झरी"),
    82: ("violent rain showers", "अत्यधिक झरी"), 85: ("snow showers", "हिमपात झरी"),
    86: ("heavy snow showers", "भारी हिमपात झरी"), 95: ("thunderstorm", "चट्याङसहितको वर्षा"),
    96: ("thunderstorm with hail", "असिनासहित चट्याङ"), 99: ("thunderstorm with heavy hail", "ठूला असिनासहित चट्याङ"),
}
RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}


def describe_code(code: int | None, language: str = "en") -> str:
    en, ne = WEATHER_CODES.get(code, ("unknown conditions", "अज्ञात अवस्था"))
    return ne if language == "ne" else en


@dataclass
class Location:
    name: str
    country: str
    admin1: str
    latitude: float
    longitude: float

    @property
    def label(self) -> str:
        parts = [self.name] + [p for p in (self.admin1, self.country) if p and p != self.name]
        return ", ".join(parts)


@dataclass
class DailyForecast:
    day: date
    weather_code: int | None
    temp_max: float | None
    temp_min: float | None
    precipitation_sum: float | None
    precipitation_probability: int | None

    @property
    def rain_expected(self) -> bool:
        return ((self.precipitation_probability or 0) >= 50 or (self.precipitation_sum or 0) >= 1.0
                or self.weather_code in RAIN_CODES)


@dataclass
class WeatherReport:
    location: Location
    timezone: str
    local_time: datetime
    temperature: float
    apparent_temperature: float
    precipitation: float
    rain: float
    showers: float
    weather_code: int
    wind_speed: float
    daily: list[DailyForecast]
    rest_of_today_rain_probability: int | None
    fetched_at: datetime

    @property
    def raining_now(self) -> bool:
        return (self.rain or 0) > 0 or (self.showers or 0) > 0 or (self.precipitation or 0) > 0 \
            or self.weather_code in RAIN_CODES

    def forecast_for(self, day: date) -> DailyForecast | None:
        return next((d for d in self.daily if d.day == day), None)


def geocode(city: str) -> Location | None:
    city = (city or "").strip()
    if not city:
        return None

    def fetch():
        data = get_json("Open-Meteo geocoding", GEOCODE_URL,
                        params={"name": city, "count": 5, "language": "en", "format": "json"})
        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            return None
        # This is a Nepal-focused assistant, so a bare city name ("Itahari", "Birgunj") should
        # resolve there even if Open-Meteo's population-ranked top hit is a same-named place
        # elsewhere; fall back to its top result when no Nepal match is among the candidates.
        r = next((x for x in results if x.get("country") == "Nepal"), results[0])
        try:
            return Location(name=r["name"], country=r.get("country", ""), admin1=r.get("admin1", ""),
                            latitude=float(r["latitude"]), longitude=float(r["longitude"]))
        except (KeyError, TypeError, ValueError) as e:
            raise ServiceError("Open-Meteo geocoding", "returned an unexpected location format") from e

    return _cache.get_or_set(("geo", city.lower()), 24 * 3600, fetch)


def get_weather_report(city: str) -> WeatherReport | None:
    """Return None if the city cannot be found; raise ServiceError if the weather service fails."""
    loc = geocode(city)
    if loc is None:
        return None

    def fetch():
        return get_json("Open-Meteo", FORECAST_URL, params={
            "latitude": loc.latitude, "longitude": loc.longitude,
            "current": "temperature_2m,apparent_temperature,precipitation,rain,showers,weather_code,wind_speed_10m",
            "hourly": "precipitation_probability",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max",
            "timezone": "auto", "forecast_days": 7, "wind_speed_unit": "kmh",
        })

    data = _cache.get_or_set(("wx", round(loc.latitude, 3), round(loc.longitude, 3)), 600, fetch)
    try:
        return _parse_report(loc, data)
    except (KeyError, TypeError, ValueError, IndexError) as e:
        log.warning("weather_parse_failed", exc_info=True)
        raise ServiceError("Open-Meteo", "returned weather data in an unexpected format") from e


def _parse_report(loc: Location, data: dict) -> WeatherReport:
    cur = data["current"]
    local_time = datetime.fromisoformat(cur["time"])
    d = data.get("daily") or {}
    daily = [
        DailyForecast(
            day=date.fromisoformat(day),
            weather_code=_idx(d.get("weather_code"), i),
            temp_max=_idx(d.get("temperature_2m_max"), i),
            temp_min=_idx(d.get("temperature_2m_min"), i),
            precipitation_sum=_idx(d.get("precipitation_sum"), i),
            precipitation_probability=_idx(d.get("precipitation_probability_max"), i),
        )
        for i, day in enumerate(d.get("time", []))
    ]
    # Highest hourly rain probability for the remaining hours of today (local time)
    h = data.get("hourly") or {}
    rest = [p for t, p in zip(h.get("time", []), h.get("precipitation_probability", []), strict=False)
            if p is not None and t[:10] == cur["time"][:10] and t >= cur["time"][:13]]
    return WeatherReport(
        location=loc, timezone=data.get("timezone", "UTC"), local_time=local_time,
        temperature=float(cur["temperature_2m"]), apparent_temperature=float(cur["apparent_temperature"]),
        precipitation=float(cur.get("precipitation") or 0), rain=float(cur.get("rain") or 0),
        showers=float(cur.get("showers") or 0), weather_code=int(cur["weather_code"]),
        wind_speed=float(cur["wind_speed_10m"]), daily=daily,
        rest_of_today_rain_probability=max(rest) if rest else None,
        fetched_at=datetime.now(settings.tz),
    )


def _idx(values, i):
    return values[i] if values and i < len(values) else None
