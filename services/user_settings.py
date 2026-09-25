"""User-editable preferences, backed by data/settings.json (see database/json_store.py).

.env / config.py hold the fixed, developer-level defaults (API keys, timezone, TTS engine order);
this store holds the handful of things the UI lets the user change at runtime (theme, whether
replies play automatically, briefing language). Falls back to config.settings the first time.
"""
from __future__ import annotations

from config import settings as app_settings
from database import stores
from database.models import UserSettings


def get_settings() -> UserSettings:
    return stores.user_settings.read()


def update_settings(**changes) -> UserSettings:
    def mutate(data):
        for key, value in changes.items():
            setattr(data, key, value)

    return stores.user_settings.update(mutate)


def seed_from_env() -> UserSettings:
    """Called once at start-up so a first run reflects .env instead of hard-coded defaults."""
    def mutate(data):
        data.timezone = app_settings.timezone
        data.voice_engine = app_settings.tts_engine_en
        data.default_language = "ne" if app_settings.briefing_language == "ne" else "en"

    return stores.user_settings.update(mutate)
