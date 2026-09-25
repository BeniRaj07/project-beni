"""Text-to-speech with three engines and automatic fallback.

* ElevenLabs (default for every reply) — the voice FL6uoOl4FRyQjIxYJbjj. English uses
  eleven_multilingual_v2; Nepali uses eleven_v3, which has ElevenLabs' broadest language support
  (multilingual_v2 does not include Nepali).
* Gemini TTS (from the original project).
* edge-tts — native Nepali neural voices (ne-NP-HemkalaNeural / ne-NP-SagarNeural).

If the first engine fails (no key, no credits, unsupported language, network), the next one is
tried, in an order that suits the language. Run scripts/check_setup.py to compare them by ear.

Every reply gets its own uniquely named WAV file, so simultaneous requests never overwrite
each other's audio.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import struct
import time
import uuid
import wave
from functools import lru_cache
from pathlib import Path

from config import require_key, settings
from services.http import ServiceError, post_for_bytes

log = logging.getLogger(__name__)

MAX_TTS_CHARS = 1500


class TTSError(ServiceError):
    def __init__(self, user_message: str):
        super().__init__("Text-to-speech", user_message)


# ── helpers ──────────────────────────────────────────────────────────────────

def new_audio_path(suffix: str = ".wav") -> Path:
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    return settings.audio_dir / f"reply_{uuid.uuid4().hex}{suffix}"


def save_wave_file(filename: str | Path, pcm_data: bytes, channels: int = 1, rate: int = 24000,
                   sample_width: int = 2) -> None:
    with wave.open(str(filename), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_data)


def clean_for_speech(text: str) -> str:
    """Remove markdown, URLs and table symbols that sound terrible when read aloud."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)       # [label](url) -> label
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#`>|]+", " ", text)
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    if len(text) > MAX_TTS_CHARS:
        cut = text[:MAX_TTS_CHARS]
        text = cut[: max(cut.rfind("."), cut.rfind("।"), 200) + 1]
    return text


def cleanup_old_audio(max_age_hours: float = 2.0) -> int:
    """Delete generated audio older than max_age_hours (called periodically by the scheduler)."""
    if not settings.audio_dir.exists():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for f in settings.audio_dir.glob("reply_*"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed


# ── Gemini engine (original code, kept) ─────────────────────────────────────

@lru_cache(maxsize=1)
def _gemini_client():
    from google import genai
    return genai.Client(api_key=require_key(settings.gemini_api_key, "GEMINI_API_KEY"))


def generate_with_retry(model, contents, max_retries=2, **kwargs):
    """Original retry helper: back off on 503, fail fast on quota (429) errors.
    Kept low so a struggling Gemini falls through to the next TTS engine quickly instead of
    burning 15s of backoff (1+2+4+8s) on a call whose reply is already spoken as text."""
    for attempt in range(max_retries):
        try:
            return _gemini_client().models.generate_content(model=model, contents=contents, **kwargs)
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                raise TTSError("the Gemini speech quota is exhausted") from e
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                time.sleep(2 ** attempt)
            else:
                raise
    raise TTSError("Gemini speech service is still unavailable after retries")


def gemini_tts(text: str, voice: str | None = None) -> Path:
    from google.genai import types
    response = generate_with_retry(
        model=settings.gemini_tts_model, contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice or settings.gemini_voice))),
        ),
    )
    try:
        pcm_data = response.candidates[0].content.parts[0].inline_data.data
    except (AttributeError, IndexError, TypeError) as e:
        raise TTSError("Gemini returned no audio") from e
    if not pcm_data:
        raise TTSError("Gemini returned empty audio")
    out = new_audio_path()
    save_wave_file(out, pcm_data)  # Gemini TTS returns raw 24 kHz 16-bit mono PCM
    return out


# ── edge-tts engine (Nepali-capable fallback) ───────────────────────────────

def _mp3_to_wav(mp3_path: Path) -> Path:
    import miniaudio
    decoded = miniaudio.decode_file(str(mp3_path), output_format=miniaudio.SampleFormat.SIGNED16,
                                    nchannels=1, sample_rate=24000)
    wav_path = mp3_path.with_suffix(".wav")
    save_wave_file(wav_path, decoded.samples.tobytes())
    mp3_path.unlink(missing_ok=True)
    return wav_path


def edge_tts_synthesize(text: str, language: str) -> Path:
    import edge_tts
    voice = settings.edge_voice_ne if language == "ne" else settings.edge_voice_en
    mp3_path = new_audio_path(".mp3")

    async def _run() -> None:
        await edge_tts.Communicate(text, voice).save(str(mp3_path))

    try:
        asyncio.run(_run())  # Gradio runs handlers in worker threads, so no event loop is active here
    except Exception as e:  # noqa: BLE001
        raise TTSError("the backup speech service could not be reached") from e
    if not mp3_path.exists() or mp3_path.stat().st_size == 0:
        raise TTSError("the backup speech service returned no audio")
    try:
        return _mp3_to_wav(mp3_path)
    except Exception:  # noqa: BLE001 - MP3 is still playable in the browser
        log.warning("mp3_to_wav_failed", exc_info=True)
        return mp3_path


# ── ElevenLabs engine ───────────────────────────────────────────────────────

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


def elevenlabs_tts(text: str, language: str) -> Path:
    key = require_key(settings.elevenlabs_api_key, "ELEVENLABS_API_KEY")
    model = settings.elevenlabs_model_ne if language == "ne" else settings.elevenlabs_model_en
    body: dict = {"text": text, "model_id": model,
                  "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
    if "multilingual_v2" not in model:          # language_code is rejected by multilingual_v2 models
        body["language_code"] = "ne" if language == "ne" else "en"
    try:
        audio = post_for_bytes(
            "ElevenLabs", ELEVENLABS_URL.format(voice_id=settings.elevenlabs_voice_id),
            json_body=body, params={"output_format": "wav_24000"},
            headers={"xi-api-key": key, "Accept": "audio/wav"}, timeout=60)
    except ServiceError as e:
        hint = " — open the voice link and click 'Add to my voices' first" if e.status == 404 else ""
        raise TTSError(f"ElevenLabs: {e.user_message}{hint}") from e
    if not audio.startswith(b"RIFF"):
        raise TTSError("ElevenLabs returned audio in an unexpected format")
    out = new_audio_path()
    out.write_bytes(audio)
    return out


ENGINES = {"elevenlabs": elevenlabs_tts, "gemini": lambda text, lang: gemini_tts(text), "edge": edge_tts_synthesize}
# Fallback order after the configured engine: Nepali prefers the dedicated ne-NP voices
FALLBACK_ORDER = {"en": ["elevenlabs", "gemini", "edge"], "ne": ["elevenlabs", "edge", "gemini"]}


def synthesize(text: str, language: str = "en") -> Path:
    """Return the path of a playable audio file (WAV). Raises TTSError if every engine fails.
    Callers must treat failure as non-fatal: the text reply is still shown."""
    spoken = clean_for_speech(text)
    if not spoken:
        raise TTSError("there is nothing to read aloud")
    primary = settings.tts_engine_ne if language == "ne" else settings.tts_engine_en
    order = [primary] + [e for e in FALLBACK_ORDER.get(language, FALLBACK_ORDER["en"]) if e != primary]
    errors = []
    for engine in order:
        if engine not in ENGINES:
            continue
        try:
            path = ENGINES[engine](spoken, language)
            log.info("tts_ok", extra={"engine": engine, "language": language, "chars": len(spoken)})
            return path
        except Exception as e:  # noqa: BLE001 - try the next engine
            errors.append(f"{engine}: {getattr(e, 'user_message', type(e).__name__)}")
            log.warning("tts_engine_failed", extra={"engine": engine, "language": language,
                                                    "error": type(e).__name__})
    raise TTSError("voice reply unavailable (" + "; ".join(errors) + ")")


# ── notification sound ──────────────────────────────────────────────────────

def notification_sound() -> Path:
    """A short two-tone chime generated locally (no external file or API needed)."""
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    path = settings.audio_dir / "chime.wav"
    if path.exists():
        return path
    rate, frames = 24000, bytearray()
    for freq, dur in ((880, 0.18), (1320, 0.28)):
        n = int(rate * dur)
        for i in range(n):
            envelope = min(1.0, i / 400) * (1 - i / n)
            frames += struct.pack("<h", int(12000 * envelope * math.sin(2 * math.pi * freq * i / rate)))
    save_wave_file(path, bytes(frames), rate=rate)
    return path
