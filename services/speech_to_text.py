"""Speech-to-text with Groq Whisper (kept from the original transcribe_file, now validated and safe)."""
from __future__ import annotations

import logging
import os
import wave
from dataclasses import dataclass

from config import settings
from services.http import ServiceError
from services.llm import _translate_error, get_groq_client

log = logging.getLogger(__name__)

MAX_BYTES = 25 * 1024 * 1024        # Groq free-tier upload limit
MIN_SECONDS = 0.4                   # shorter clips are almost always accidental clicks

WHISPER_PROMPT = (
    "Conversational request to a personal assistant about reminders, monthly tasks, the weather "
    "or football (soccer) news, spoken in Nepali (Devanagari script) or English. "
    "नमस्ते, मलाई भोलि बिहान ८ बजे सम्झाउनु। काठमाडौंको मौसम कस्तो छ?"
)


class STTError(ServiceError):
    def __init__(self, user_message: str):
        super().__init__("Speech recognition", user_message)


@dataclass
class Transcription:
    text: str
    language: str  # "en" or "ne"


def _wav_duration(path: str) -> float | None:
    try:
        with wave.open(path, "rb") as wf:
            return wf.getnframes() / float(wf.getframerate() or 1)
    except (wave.Error, EOFError, OSError):
        return None  # not a WAV (e.g. uploaded mp3/m4a) — let Whisper handle it


def detect_script_language(text: str) -> str:
    return "ne" if any("ऀ" <= ch <= "ॿ" for ch in text) else "en"


def transcribe(audio_path: str | None, language_hint: str | None = None) -> Transcription:
    """language_hint: None/'auto', 'en' or 'ne'. Whisper sometimes labels Nepali as Hindi,
    so forcing 'ne' in the UI helps when auto-detection struggles."""
    if not audio_path:
        raise STTError("no audio was received — please record or upload a clip")
    if not os.path.exists(audio_path):
        raise STTError("the recording could not be found — please try again")
    size = os.path.getsize(audio_path)
    if size == 0:
        raise STTError("the recording is empty — check your microphone permissions")
    if size > MAX_BYTES:
        raise STTError("the audio file is larger than 25 MB — please upload a shorter clip")
    duration = _wav_duration(audio_path)
    if duration is not None and duration < MIN_SECONDS:
        raise STTError("the recording is too short — hold the button and speak a full sentence")

    kwargs = {}
    if language_hint in ("en", "ne"):
        kwargs["language"] = language_hint
    try:
        with open(audio_path, "rb") as f:
            result = get_groq_client().audio.transcriptions.create(
                file=(os.path.basename(audio_path), f.read()),
                model=settings.groq_stt_model,
                response_format="verbose_json",
                temperature=0.0,
                prompt=WHISPER_PROMPT,
                **kwargs,
            )
    except ServiceError:
        raise
    except Exception as e:  # noqa: BLE001
        if type(e).__module__.startswith("groq"):
            err = _translate_error(e)
            raise STTError(err.user_message) from e
        log.exception("stt_unexpected_error", extra={"error_type": type(e).__name__})
        raise STTError("transcription failed unexpectedly") from e

    text = (getattr(result, "text", "") or "").strip()
    if not text:
        raise STTError("I couldn't hear any speech in that recording — please try again")
    detected = (getattr(result, "language", "") or "").lower()
    language = "ne" if detected in ("nepali", "ne", "hindi", "hi") or detect_script_language(text) == "ne" else "en"
    if language_hint in ("en", "ne"):
        language = language_hint
    log.info("transcribed", extra={"chars": len(text), "whisper_language": detected, "language": language})
    return Transcription(text=text, language=language)
