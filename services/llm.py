"""LLM calls (intent classification, summaries, small talk) via Claude, plus the Groq client used
only for Whisper speech-to-text (services/speech_to_text.py) - Anthropic has no audio API."""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any

from config import require_key, settings
from services.http import RateLimitError, ServiceError

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_groq_client():
    from groq import Groq  # imported lazily so tests don't need network access or keys
    # A slow/hung request used to cost up to 90s (30s timeout x 3 attempts) before the user saw
    # any error - keep this tight since STT is the only thing still using Groq.
    return Groq(api_key=require_key(settings.groq_api_key, "GROQ_API_KEY"), timeout=15, max_retries=1)


def _translate_error(e: Exception) -> ServiceError:
    """Groq-specific: used by services/speech_to_text.py for Whisper failures."""
    import groq
    if isinstance(e, groq.RateLimitError):
        return RateLimitError("Groq", "the speech-to-text quota is exhausted for now — try again in a minute", status=429)
    if isinstance(e, (groq.APIConnectionError, groq.APITimeoutError)):
        return ServiceError("Groq", "could not reach the speech-to-text service (check your internet connection)")
    if isinstance(e, groq.AuthenticationError):
        return ServiceError("Groq", "the GROQ_API_KEY was rejected", status=401)
    return ServiceError("Groq", "the speech-to-text service returned an error")


@lru_cache(maxsize=1)
def get_anthropic_client():
    from anthropic import Anthropic  # imported lazily so tests don't need network access or keys
    kwargs: dict[str, Any] = {}
    if settings.anthropic_workspace_id:
        kwargs["default_headers"] = {"anthropic-workspace-id": settings.anthropic_workspace_id}
    return Anthropic(api_key=require_key(settings.anthropic_api_key, "ANTHROPIC_API_KEY"),
                     timeout=15, max_retries=1, **kwargs)


def _is_claude_error(e: Exception) -> bool:
    return type(e).__module__.startswith("anthropic")


def _translate_claude_error(e: Exception) -> ServiceError:
    import anthropic
    if isinstance(e, anthropic.RateLimitError):
        return RateLimitError("Claude", "the language model quota is exhausted for now — try again in a minute", status=429)
    if isinstance(e, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return ServiceError("Claude", "could not reach the language model (check your internet connection)")
    if isinstance(e, anthropic.AuthenticationError):
        return ServiceError("Claude", "the ANTHROPIC_API_KEY was rejected", status=401)
    return ServiceError("Claude", "the language model returned an error")


def _split_system(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    """Anthropic takes `system` as a separate top-level field, not a message role."""
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    rest = [m for m in messages if m.get("role") != "system"]
    return system, rest


def chat_text(messages: list[dict[str, str]], *, max_tokens: int = 1500) -> str:
    # No `temperature` param: the installed anthropic SDK rejects it as an unexpected kwarg on
    # messages.create() (client-side TypeError, not a server 400) - Claude's own default sampling
    # is used instead.
    system, msgs = _split_system(messages)
    try:
        resp = get_anthropic_client().messages.create(
            model=settings.claude_model, max_tokens=max_tokens,
            system=system, messages=msgs)
    except ServiceError:
        raise
    except Exception as e:  # noqa: BLE001 - translated into a user-safe error
        if _is_claude_error(e):
            log.warning("claude_error", extra={"error": type(e).__name__, "detail": str(e)})
            raise _translate_claude_error(e) from e
        raise
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        raise ServiceError("Claude", "the language model returned an empty answer")
    return text


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_object(raw: str) -> dict[str, Any]:
    """Extract the first JSON object from a model reply (tolerates ```json fences and chatter)."""
    match = _JSON_OBJECT.search(raw or "")
    if not match:
        raise ValueError("no JSON object in model output")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("model output is not a JSON object")
    return data


def chat_json(messages: list[dict[str, str]], *, max_tokens: int = 1500) -> dict[str, Any]:
    """Ask for a JSON object. Retries once with a stricter reminder if the output is malformed,
    and raises ServiceError if it still cannot be parsed."""
    system, msgs = _split_system(messages)
    system = (system + "\n\nRespond with ONLY a single JSON object - no markdown fences, no commentary.").strip()
    last_error: Exception | None = None
    attempts = 0
    while attempts < 2:
        try:
            resp = get_anthropic_client().messages.create(
                model=settings.claude_model, max_tokens=max_tokens,
                system=system, messages=msgs)
        except ServiceError:
            raise
        except Exception as e:  # noqa: BLE001
            if not _is_claude_error(e):
                raise
            log.warning("claude_error", extra={"error": type(e).__name__, "detail": str(e)})
            raise _translate_claude_error(e) from e
        attempts += 1
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return parse_json_object(text)
        except (ValueError, json.JSONDecodeError) as e:
            last_error = e
            log.warning("llm_json_parse_failed", extra={"attempt": attempts})
            msgs = msgs + [{"role": "user", "content": "Reply with ONLY the JSON object, nothing else."}]
    raise ServiceError("Claude", "the language model gave an unreadable answer") from last_error
