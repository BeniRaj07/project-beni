"""Tests for services/user_settings.py: the small, user-editable preferences file."""
from __future__ import annotations

import dataclasses

from services import user_settings


def test_defaults():
    s = user_settings.get_settings()
    assert s.auto_play is True and s.theme == "dark" and s.default_language == "en"


def test_update_persists():
    user_settings.update_settings(auto_play=False, theme="light")
    s = user_settings.get_settings()
    assert s.auto_play is False and s.theme == "light"
    # unrelated fields untouched
    assert s.timezone == "Asia/Kathmandu"


def test_seed_from_env_reflects_config(monkeypatch):
    import config
    monkeypatch.setattr(user_settings, "app_settings",
                        dataclasses.replace(config.settings, timezone="America/New_York", tts_engine_en="edge"))
    s = user_settings.seed_from_env()
    assert s.timezone == "America/New_York" and s.voice_engine == "edge"
