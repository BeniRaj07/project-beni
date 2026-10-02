"""Thin wrapper around the chat LLM (Claude via the Anthropic API, or Groq) used for intent
classification, summaries and small talk. Speech-to-text (services/speech_to_text.py) stays on Groq."""
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
    # any error; both STT and LLM calls share this client, so that latency hit every turn.
    return Groq(api_key=require_key(settings.groq_api_key, "GROQ_API_KEY"), timeout=15, max_retries=1)


def use_anthropic() -> bool:
    provider = settings.llm_provider
    return provider == "anthropic" or (provider != "groq" and bool(settings.anthropic_api_key))


@lru_cache(maxsize=1)
def get_anthropic_client():
    import anthropic  # lazy, like groq above
    return anthropic.Anthropic(api_key=require_key(settings.anthropic_api_key, "ANTHROPIC_API_KEY"),
                               timeout=60, max_retries=1)


def _translate_anthropic_error(e: Exception) -> ServiceError:
    import anthropic
    if isinstance(e, anthropic.RateLimitError):
        return RateLimitError("Claude", "the language model quota is exhausted for now — try again in a minute", status=429)
    if isinstance(e, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return ServiceError("Claude", "could not reach the language model (check your internet connection)")
    if isinstance(e, anthropic.AuthenticationError):
        return ServiceError("Claude", "the ANTHROPIC_API_KEY was rejected", status=401)
    return ServiceError("Claude", "the language model returned an error")


def _anthropic_text(messages: list[dict[str, str]], max_tokens: int) -> str:
    """One Claude call for OpenAI-style `messages` (system turns are lifted into `system`)."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] != "system"]
    try:
        resp = get_anthropic_client().beta.messages.create(
            model=settings.anthropic_model,
            # Thinking is always on for Claude Opus 5.5 and its tokens count against max_tokens,
            # so leave headroom above the visible answer; low effort keeps replies fast.
            max_tokens=max_tokens + 4000,
            system=system or "You are a helpful assistant.",
            messages=turns,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},  # re-run on another model if a safety classifier declines
        )
    except ServiceError:
        raise
    except Exception as e:  # noqa: BLE001 - translated into a user-safe error
        if type(e).__module__.startswith("anthropic"):
            log.warning("anthropic_error", extra={"error": type(e).__name__})
            raise _translate_anthropic_error(e) from e
        raise
    if resp.stop_reason == "refusal":
        raise ServiceError("Claude", "the language model declined that request")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        raise ServiceError("Claude", "the language model returned an empty answer")
    return text


def _is_groq_error(e: Exception) -> bool:
    return type(e).__module__.startswith("groq")


def _translate_error(e: Exception) -> ServiceError:
    import groq
    if isinstance(e, groq.RateLimitError):
        return RateLimitError("Groq", "the language model quota is exhausted for now — try again in a minute", status=429)
    if isinstance(e, (groq.APIConnectionError, groq.APITimeoutError)):
        return ServiceError("Groq", "could not reach the language model (check your internet connection)")
    if isinstance(e, groq.AuthenticationError):
        return ServiceError("Groq", "the GROQ_API_KEY was rejected", status=401)
    return ServiceError("Groq", "the language model returned an error")


def _model_kwargs(max_tokens: int) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": settings.groq_llm_model, "max_tokens": max_tokens}
    # gpt-oss models "think" before answering and the hidden reasoning counts against max_tokens;
    # low effort keeps answers fast and stops the visible reply from being cut off.
    if "gpt-oss" in settings.groq_llm_model:
        kwargs["reasoning_effort"] = "low"
    return kwargs


def chat_text(messages: list[dict[str, str]], *, temperature: float = 0.4, max_tokens: int = 1500) -> str:
    if use_anthropic():  # temperature is not accepted by the newest Claude models, so it's not sent
        return _anthropic_text(messages, max_tokens)
    try:
        resp = get_groq_client().chat.completions.create(
            messages=messages, temperature=temperature, **_model_kwargs(max_tokens))
    except ServiceError:
        raise
    except Exception as e:  # noqa: BLE001 - translated into a user-safe error
        if _is_groq_error(e):
            log.warning("groq_error", extra={"error": type(e).__name__})
            raise _translate_error(e) from e
        raise
    text = (resp.choices[0].message.content or "").strip()
    if not text:
        raise ServiceError("Groq", "the language model returned an empty answer")
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
    """Ask for a JSON object. Uses JSON mode when the model supports it, retries once with a stricter
    reminder if the output is malformed, and raises ServiceError if it still cannot be parsed."""
    if use_anthropic():
        msgs = messages
        for attempt in (1, 2):
            try:
                return parse_json_object(_anthropic_text(msgs, max_tokens))
            except (ValueError, json.JSONDecodeError) as e:
                log.warning("llm_json_parse_failed", extra={"attempt": attempt})
                msgs = messages + [{"role": "user", "content": "Reply with ONLY the JSON object, nothing else."}]
        raise ServiceError("Claude", "the language model gave an unreadable answer")
    json_mode = True
    msgs = messages
    last_error: Exception | None = None
    attempts = 0
    while attempts < 2:
        extra = {"response_format": {"type": "json_object"}} if json_mode else {}
        try:
            resp = get_groq_client().chat.completions.create(
                messages=msgs, temperature=0, **_model_kwargs(max_tokens), **extra)
        except ServiceError:
            raise
        except Exception as e:  # noqa: BLE001
            if not _is_groq_error(e):
                raise
            import groq
            if isinstance(e, groq.BadRequestError) and json_mode:
                # Model rejected JSON mode (or its strict validation failed): retry as plain text
                log.warning("json_mode_rejected", extra={"model": settings.groq_llm_model})
                json_mode = False
                last_error = e
                continue
            raise _translate_error(e) from e
        attempts += 1
        try:
            return parse_json_object(resp.choices[0].message.content or "")
        except (ValueError, json.JSONDecodeError) as e:
            last_error = e
            log.warning("llm_json_parse_failed", extra={"attempt": attempts})
            msgs = messages + [{"role": "user", "content": "Reply with ONLY the JSON object, nothing else."}]
    raise ServiceError("Groq", "the language model gave an unreadable answer") from last_error
