import dataclasses
import wave
from types import SimpleNamespace

import pytest

from services import speech_to_text as stt
from services import text_to_speech as tts
from services.speech_to_text import STTError
from services.text_to_speech import TTSError


def make_wav(path, seconds=1.0, rate=16000):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * seconds))
    return str(path)


def fake_groq(monkeypatch, result=None, error=None):
    def create(**kw):
        if error:
            raise error
        return result
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    monkeypatch.setattr(stt, "get_groq_client", lambda: client)


# ── speech-to-text ──────────────────────────────────────────────────────────

def test_no_audio_or_missing_file():
    with pytest.raises(STTError, match="no audio"):
        stt.transcribe(None)
    with pytest.raises(STTError, match="could not be found"):
        stt.transcribe("/nope/recording.wav")


def test_empty_and_too_short_recordings(tmp_path):
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    with pytest.raises(STTError, match="empty"):
        stt.transcribe(str(empty))
    with pytest.raises(STTError, match="too short"):
        stt.transcribe(make_wav(tmp_path / "short.wav", seconds=0.1))


def test_successful_nepali_transcription(tmp_path, monkeypatch):
    fake_groq(monkeypatch, SimpleNamespace(text=" काठमाडौंको मौसम कस्तो छ? ", language="nepali"))
    result = stt.transcribe(make_wav(tmp_path / "q.wav"))
    assert result.text == "काठमाडौंको मौसम कस्तो छ?" and result.language == "ne"


def test_whisper_hindi_label_on_devanagari_is_treated_as_nepali(tmp_path, monkeypatch):
    fake_groq(monkeypatch, SimpleNamespace(text="आजको समाचार", language="hindi"))
    assert stt.transcribe(make_wav(tmp_path / "q.wav")).language == "ne"


def test_blank_transcription_is_an_error(tmp_path, monkeypatch):
    fake_groq(monkeypatch, SimpleNamespace(text="   ", language="english"))
    with pytest.raises(STTError, match="couldn't hear"):
        stt.transcribe(make_wav(tmp_path / "q.wav"))


def test_api_failure_becomes_friendly_error(tmp_path, monkeypatch):
    fake_groq(monkeypatch, error=RuntimeError("socket closed"))
    with pytest.raises(STTError, match="failed"):
        stt.transcribe(make_wav(tmp_path / "q.wav"))


# ── text-to-speech ──────────────────────────────────────────────────────────

def test_clean_for_speech_removes_markdown_and_urls():
    text = "**Arsenal** won. See [BBC](https://bbc.co.uk/x) or https://example.com\n| 1 | Arsenal |"
    spoken = tts.clean_for_speech(text)
    assert "http" not in spoken and "*" not in spoken and "|" not in spoken and "BBC" in spoken


def fake_engines(monkeypatch, tmp_path, failing=()):
    """Replace every engine with a stub that records calls (and optionally fails)."""
    used = []
    for name in ("groq", "gemini", "edge"):
        def engine(text, lang, name=name):
            used.append(name)
            if name in failing:
                raise TTSError(f"{name} down")
            return tmp_path / f"{name}.wav"
        monkeypatch.setitem(tts.ENGINES, name, engine)
    return used


def test_configured_engine_is_used_first_for_both_languages(monkeypatch, tmp_path):
    used = fake_engines(monkeypatch, tmp_path)
    monkeypatch.setattr(tts, "settings", dataclasses.replace(tts.settings, tts_engine_en="groq",
                                                             tts_engine_ne="edge"))
    assert tts.synthesize("Hello", "en") == tmp_path / "groq.wav"
    assert tts.synthesize("नमस्ते", "ne") == tmp_path / "edge.wav"
    assert used == ["groq", "edge"]


def test_fallback_order_depends_on_language(monkeypatch, tmp_path):
    used = fake_engines(monkeypatch, tmp_path, failing=("groq",))
    monkeypatch.setattr(tts, "settings", dataclasses.replace(tts.settings, tts_engine_en="groq",
                                                             tts_engine_ne="groq"))
    assert tts.synthesize("नमस्ते", "ne") == tmp_path / "edge.wav"      # native Nepali voice next
    assert tts.synthesize("Hello", "en") == tmp_path / "gemini.wav"
    assert used == ["groq", "edge", "groq", "gemini"]


def test_all_engines_failing_raises_tts_error(monkeypatch, tmp_path):
    fake_engines(monkeypatch, tmp_path, failing=("groq", "gemini", "edge"))
    with pytest.raises(TTSError, match="voice reply unavailable"):
        tts.synthesize("Hello", "en")


WAV_BYTES = b"RIFF" + b"\x00" * 40


def test_gemini_audio_saved_to_unique_wav(monkeypatch):
    pcm = b"\x01\x00" * 2400
    response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(
        parts=[SimpleNamespace(inline_data=SimpleNamespace(data=pcm))]))])
    monkeypatch.setattr(tts, "generate_with_retry", lambda **kw: response)
    a, b = tts.gemini_tts("one"), tts.gemini_tts("two")
    assert a != b and a.suffix == ".wav"
    with wave.open(str(a)) as wf:
        assert wf.getframerate() == 24000 and wf.getnframes() == 2400


def test_gemini_quota_error_is_not_retried(monkeypatch):
    calls = []

    def quota(**kw):
        calls.append(1)
        raise RuntimeError("429 RESOURCE_EXHAUSTED")
    monkeypatch.setattr(tts, "_gemini_client", lambda: SimpleNamespace(models=SimpleNamespace(generate_content=quota)))
    with pytest.raises(TTSError, match="quota"):
        tts.generate_with_retry(model="m", contents="hi")
    assert len(calls) == 1


def test_notification_chime_is_a_valid_wav():
    with wave.open(str(tts.notification_sound())) as wf:
        assert wf.getnframes() > 0


def test_post_for_bytes_reports_paid_plan_errors(monkeypatch):
    from services import http
    monkeypatch.setattr(http._session, "request",
                        lambda *a, **k: SimpleNamespace(status_code=402, content=b"", json=lambda: {}))
    with pytest.raises(http.ServiceError, match="paid plan") as e:
        http.post_for_bytes("TTS", "https://example.com/x", json_body={"text": "hi"})
    assert e.value.status == 402
    monkeypatch.setattr(http._session, "request",
                        lambda *a, **k: SimpleNamespace(status_code=200, content=b"RIFF...", json=lambda: {}))
    assert http.post_for_bytes("TTS", "https://x", json_body={}) == b"RIFF..."


# ── Groq Orpheus engine ─────────────────────────────────────────────────────

def test_groq_text_is_split_into_200_char_requests():
    text = "First sentence here. " + "word " * 80 + "Last one!"
    pieces = tts._split_for_groq(text)
    assert all(0 < len(p) <= 200 for p in pieces) and len(pieces) >= 2
    assert " ".join(pieces).split() == text.split()


def test_groq_tts_joins_chunks_into_one_wav(monkeypatch):
    import io

    def fake_wav(n):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1), wf.setsampwidth(2), wf.setframerate(24000)
            wf.writeframes(b"\x01\x00" * n)
        return buf.getvalue()

    sent = []
    speech = SimpleNamespace(create=lambda **kw: (sent.append(kw), SimpleNamespace(read=lambda: fake_wav(100)))[1])
    monkeypatch.setattr("services.llm.get_groq_client", lambda: SimpleNamespace(audio=SimpleNamespace(speech=speech)))
    path = tts.groq_tts("Hello there. " + "x" * 190 + ". Bye.", "en")
    assert len(sent) >= 2 and all(k["response_format"] == "wav" and len(k["input"]) <= 200 for k in sent)
    with wave.open(str(path)) as wf:
        assert wf.getnframes() == 100 * len(sent) and wf.getframerate() == 24000


def test_groq_tts_refuses_nepali():
    with pytest.raises(TTSError, match="English"):
        tts.groq_tts("नमस्ते", "ne")
