"""Pre-demo check: verifies every API key with one small request and generates TTS samples.

    python scripts/check_setup.py

Listen to the files in data/tts_check/ to decide which engine sounds best for Nepali, then set
TTS_ENGINE_NE in .env accordingly (gemini, elevenlabs or edge).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import MissingAPIKeyError, settings, setup_logging  # noqa: E402
from services import football, news, weather  # noqa: E402
from services import text_to_speech as tts  # noqa: E402
from services.http import ServiceError  # noqa: E402
from services.llm import chat_text  # noqa: E402

NE_SAMPLE = "नमस्ते! आज काठमाडौंमा तापक्रम चौबीस डिग्री छ र साँझ पानी पर्ने सम्भावना छ।"
EN_SAMPLE = "Hello! It is twenty-four degrees in Kathmandu with a chance of rain this evening."


def check(name, fn):
    try:
        detail = fn()
        print(f"  ✅ {name}: {detail}")
        return True
    except MissingAPIKeyError as e:
        print(f"  ❌ {name}: {e}")
    except ServiceError as e:
        print(f"  ❌ {name}: {e.user_message}")
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ {name}: {type(e).__name__}: {e}")
    return False


def main() -> int:
    setup_logging("WARNING")
    out = settings.audio_dir.parent / "tts_check"
    out.mkdir(parents=True, exist_ok=True)
    print("API connectivity")
    results = [
        check("Claude LLM", lambda: chat_text([{"role": "user", "content": "Reply with the single word OK."}], max_tokens=300)),
        check("Open-Meteo", lambda: f"{weather.get_weather_report('Kathmandu').temperature}°C in Kathmandu"),
        check("Football-Data.org", lambda: f"{len(football.get_standings('PL')[0][1])} teams in the PL table"),
        check("NewsAPI", lambda: f"{len(news.fetch_football_articles())} football articles"),
    ]
    print("\nText-to-speech samples (listen to them!)")

    def sample(engine, lang, text):
        path = tts.ENGINES[engine](tts.clean_for_speech(text), lang)
        target = out / f"{engine}_{lang}{path.suffix}"
        path.replace(target)
        return str(target)

    results += [
        check("ElevenLabs English", lambda: sample("elevenlabs", "en", EN_SAMPLE)),
        check("ElevenLabs Nepali ", lambda: sample("elevenlabs", "ne", NE_SAMPLE)),
        check("Gemini TTS English", lambda: sample("gemini", "en", EN_SAMPLE)),
        check("Gemini TTS Nepali ", lambda: sample("gemini", "ne", NE_SAMPLE)),
        check("edge-tts Nepali   ", lambda: sample("edge", "ne", NE_SAMPLE)),
    ]
    print(f"\nCurrent config: TTS_ENGINE_EN={settings.tts_engine_en}, TTS_ENGINE_NE={settings.tts_engine_ne}")
    print("Whisper speech-to-text is checked by recording a question in the app's Voice tab.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
