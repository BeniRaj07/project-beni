"""Central configuration, loaded once from environment variables / .env.

API keys are optional at import time so the app (and the tests) can start
without them; each service raises a clear error only when it is actually used
without its key.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # API keys
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    groq_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY"))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    news_api_key: str = field(default_factory=lambda: _env("NEWS_API_KEY"))
    football_data_key: str = field(default_factory=lambda: _env("FOOTBALL_DATA_KEY"))

    # Which service WRITES replies: "anthropic" or "groq". Blank = Claude whenever an ANTHROPIC_API_KEY
    # is set, otherwise Groq. Intent classification and speech-to-text are always Groq.
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER").lower())
    # Claude: final response generation. ANTHROPIC_RESPONSE_MODEL is preferred; ANTHROPIC_MODEL still works.
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_RESPONSE_MODEL") or _env("ANTHROPIC_MODEL", "claude-opus-5-5"))

    # Models
    # Groq: intent classification (and the reply fallback when no Anthropic key is set).
    # GROQ_INTENT_MODEL is the preferred name; GROQ_LLM_MODEL still works.
    groq_llm_model: str = field(default_factory=lambda: _env("GROQ_INTENT_MODEL") or _env("GROQ_LLM_MODEL", "openai/gpt-oss-20b"))
    groq_stt_model: str = field(default_factory=lambda: _env("GROQ_STT_MODEL", "whisper-large-v3"))
    gemini_tts_model: str = field(default_factory=lambda: _env("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts"))
    gemini_voice: str = field(default_factory=lambda: _env("GEMINI_VOICE", "Kore"))

    # Groq Orpheus TTS (English only - Nepali is spoken by edge-tts). Voices: autumn, diana,
    # hannah, austin, daniel, troy. The model's terms must be accepted once in the Groq console.
    groq_tts_model: str = field(default_factory=lambda: _env("GROQ_TTS_MODEL", "canopylabs/orpheus-v1-english"))
    groq_tts_voice: str = field(default_factory=lambda: _env("GROQ_TTS_VOICE", "hannah"))

    # Text-to-speech engine tried first per language: "groq", "gemini" or "edge". The others are
    # used automatically as fallbacks (see services/text_to_speech.py). Groq cannot speak Nepali,
    # so Nepali defaults to edge-tts's native ne-NP voices.
    tts_engine_en: str = field(default_factory=lambda: _env("TTS_ENGINE_EN", "groq"))
    tts_engine_ne: str = field(default_factory=lambda: _env("TTS_ENGINE_NE", "edge"))
    edge_voice_en: str = field(default_factory=lambda: _env("EDGE_VOICE_EN", "en-US-JennyNeural"))
    edge_voice_ne: str = field(default_factory=lambda: _env("EDGE_VOICE_NE", "ne-NP-HemkalaNeural"))

    # Wake-word phrases for the browser's passive wake-word listener (comma-separated in .env).
    # Matching is case-insensitive substring/fuzzy matching done client-side — see theme.py's JS
    # and README's "how to configure wake phrases" section. Adding a phrase needs no code change.
    wake_phrases: tuple[str, ...] = field(default_factory=lambda: tuple(
        p.strip() for p in _env("WAKE_PHRASES", "Hey Aawaz,Aawaz").split(",") if p.strip()))

    # App behaviour
    timezone: str = field(default_factory=lambda: _env("APP_TIMEZONE", "Asia/Kathmandu"))
    briefing_language: str = field(default_factory=lambda: _env("BRIEFING_LANGUAGE", "en"))  # en | ne
    default_city: str = field(default_factory=lambda: _env("DEFAULT_CITY", "Kathmandu"))  # used when no city has been mentioned yet
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(BASE_DIR / "data"))))
    audio_dir: Path = field(default_factory=lambda: Path(_env("AUDIO_DIR", str(BASE_DIR / "data" / "audio"))))
    log_dir: Path = field(default_factory=lambda: Path(_env("LOG_DIR", str(BASE_DIR / "logs"))))
    reminder_check_seconds: int = field(default_factory=lambda: int(_env("REMINDER_CHECK_SECONDS", "20")))
    http_timeout: float = field(default_factory=lambda: float(_env("HTTP_TIMEOUT", "15")))
    server_host: str = field(default_factory=lambda: _env("SERVER_HOST", "127.0.0.1"))
    server_port: int = field(default_factory=lambda: int(_env("SERVER_PORT", "7860")))
    # Optional "username:password" to protect the UI if you ever expose it beyond localhost
    app_auth: str = field(default_factory=lambda: _env("APP_AUTH"))

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            logging.getLogger(__name__).warning("Unknown APP_TIMEZONE %r, falling back to Asia/Kathmandu", self.timezone)
            return ZoneInfo("Asia/Kathmandu")


settings = Settings()


class MissingAPIKeyError(RuntimeError):
    """Raised when a service is used without its API key configured."""

    def __init__(self, env_name: str):
        super().__init__(f"{env_name} is not set. Add it to your .env file (see .env.example).")
        self.env_name = env_name


def require_key(value: str, env_name: str) -> str:
    if not value:
        raise MissingAPIKeyError(env_name)
    return value


# ── Structured logging ──────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """One JSON object per line: easy to grep and to load into pandas for analysis."""

    RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Anything passed via logger.info(..., extra={...}) becomes a structured field
        payload.update({k: v for k, v in vars(record).items() if k not in self.RESERVED})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str | None = None) -> None:
    level = level or _env("LOG_LEVEL", "INFO")
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if getattr(root, "_assistant_configured", False):
        return
    root.setLevel(level)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(JsonFormatter())
    file_handler = logging.FileHandler(settings.log_dir / "app.log", encoding="utf-8")
    file_handler.setFormatter(JsonFormatter())
    root.handlers[:] = [console, file_handler]
    # Third-party loggers can print full request URLs; keep them quiet so nothing sensitive leaks
    for noisy in ("urllib3", "httpx", "httpcore", "apscheduler", "google_genai", "groq", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._assistant_configured = True  # type: ignore[attr-defined]
