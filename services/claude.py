"""Claude (Anthropic API) client used ONLY for final response generation.

Awaaz splits its LLM work in two: Groq classifies the user's intent (services/llm.py's chat_json)
and Claude writes the reply (this module, reached through services/llm.py's chat_text). Claude never
classifies and is never asked to re-route; it trusts the intent the application already chose.
Everything here runs server-side; the key is read from ANTHROPIC_API_KEY and never reaches the page.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from config import require_key, settings
from services.http import RateLimitError, ServiceError

log = logging.getLogger(__name__)

# Headroom for the model's own reasoning, which counts against max_tokens before the visible reply.
THINKING_HEADROOM = 4000


@lru_cache(maxsize=1)
def get_client():
    import anthropic  # lazy: tests and Groq-only setups don't need the package or a key
    return anthropic.Anthropic(api_key=require_key(settings.anthropic_api_key, "ANTHROPIC_API_KEY"),
                               timeout=60, max_retries=1)


def _translate_error(e: Exception) -> ServiceError:
    import anthropic
    if isinstance(e, anthropic.RateLimitError):
        return RateLimitError("Claude", "the language model quota is exhausted for now — try again in a minute",
                              status=429)
    if isinstance(e, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return ServiceError("Claude", "could not reach the language model (check your internet connection)")
    if isinstance(e, anthropic.AuthenticationError):
        return ServiceError("Claude", "the ANTHROPIC_API_KEY was rejected", status=401)
    detail = getattr(e, "message", "") or str(e)
    status = getattr(e, "status_code", "")
    return ServiceError("Claude", f"the language model returned an error ({status} {detail[:200]})".replace("( ", "("))


def _normalize_turns(turns: list[dict[str, str]]) -> list[dict[str, str]]:
    """The Messages API wants the conversation to start with the user and alternate roles; a bounded
    history slice can start with an assistant turn or repeat a role, so fix that up here."""
    out: list[dict[str, str]] = []
    for m in turns:
        if not out and m["role"] != "user":
            continue
        if out and out[-1]["role"] == m["role"]:
            out[-1] = {"role": m["role"], "content": out[-1]["content"] + "\n\n" + m["content"]}
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def generate(messages: list[dict[str, str]], *, max_tokens: int, intent: str = "unknown") -> str:
    """One Claude call for OpenAI-style `messages` (system turns are lifted into `system`).
    Logs provider/model/intent/status only - never the prompt, the user's text or any context."""
    model = settings.anthropic_model
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = _normalize_turns([m for m in messages if m["role"] != "system"])
    try:
        resp = get_client().messages.create(
            model=model,
            max_tokens=max_tokens + THINKING_HEADROOM,
            system=system or "You are a helpful assistant.",
            messages=turns,
            output_config={"effort": "low"},   # low effort keeps spoken replies fast
        )
    except ServiceError:
        raise
    except Exception as e:  # noqa: BLE001 - translated into a user-safe error
        if type(e).__module__.startswith("anthropic"):
            log.warning("[ResponseGenerator] provider=anthropic model=%s intent=%s status=error error=%s: %s",
                        model, intent, type(e).__name__, getattr(e, "message", "") or e)
            raise _translate_error(e) from e
        raise
    if resp.stop_reason == "refusal":
        log.warning("[ResponseGenerator] provider=anthropic model=%s intent=%s status=refused", model, intent)
        raise ServiceError("Claude", "the language model declined that request")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        log.warning("[ResponseGenerator] provider=anthropic model=%s intent=%s status=empty", model, intent)
        raise ServiceError("Claude", "the language model returned an empty answer")
    log.info("[ResponseGenerator] provider=anthropic model=%s intent=%s status=success", model, intent)
    return text
