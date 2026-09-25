"""Conversation storage, backed by data/conversations.json (see database/json_store.py).

Each conversation keeps its own language, last-discussed city and any in-flight follow-up
("What time?"), so reopening an old conversation restores full context, not just the transcript.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone

from config import settings
from database import stores
from database.models import Conversation, Message

log = logging.getLogger(__name__)
MAX_TITLE_WORDS = 6
MAX_TITLE_CHARS = 48
GROUP_ORDER = ("Today", "Yesterday", "Previous 7 Days", "Older")


def make_title(first_message: str) -> str:
    """A short, deterministic title from the first user message — no LLM call needed for this."""
    text = re.sub(r"\s+", " ", (first_message or "").strip())
    if not text:
        return "New chat"
    words = text.split(" ")[:MAX_TITLE_WORDS]
    title = " ".join(words).strip(" .,!?।")
    if len(title) > MAX_TITLE_CHARS:
        title = title[:MAX_TITLE_CHARS].rstrip() + "…"
    elif len(words) < len(text.split(" ")):
        title += "…"
    # Capitalize only the first letter — .capitalize() would also lowercase proper nouns
    # like "Premier League" in the rest of the title.
    if title and title[0].isascii() and title[0].isalpha():
        title = title[0].upper() + title[1:]
    return title


def new_conversation(now: datetime | None = None) -> Conversation:
    stamp = now or datetime.now(timezone.utc)
    saved: dict[str, Conversation] = {}

    def mutate(data):
        cid = data.next_id
        data.next_id += 1
        conv = Conversation(id=cid, title="New chat", created_at=stamp, updated_at=stamp)
        data.conversations[str(cid)] = conv
        saved["conv"] = conv

    stores.conversations.update(mutate)
    log.info("conversation_created", extra={"conversation_id": saved["conv"].id})
    return saved["conv"]


def get_conversation(conversation_id: int) -> Conversation | None:
    return stores.conversations.read().conversations.get(str(conversation_id))


def list_conversations() -> list[Conversation]:
    items = list(stores.conversations.read().conversations.values())
    items.sort(key=lambda c: c.updated_at, reverse=True)
    return items


def search_conversations(query: str) -> list[Conversation]:
    q = (query or "").strip().lower()
    if not q:
        return list_conversations()
    return [c for c in list_conversations()
           if q in c.title.lower() or any(q in m.content.lower() for m in c.messages)]


def group_conversations(items: list[Conversation], today: date | None = None) -> dict[str, list[Conversation]]:
    """Buckets for the sidebar: Today, Yesterday, Previous 7 Days, Older."""
    today = today or datetime.now(settings.tz).date()
    groups: dict[str, list[Conversation]] = {k: [] for k in GROUP_ORDER}
    for c in items:
        d = c.updated_at.astimezone(settings.tz).date()
        age = (today - d).days
        key = "Today" if age <= 0 else "Yesterday" if age == 1 else "Previous 7 Days" if age <= 7 else "Older"
        groups[key].append(c)
    return {k: v for k, v in groups.items() if v}


def rename_conversation(conversation_id: int, title: str) -> Conversation:
    title = (title or "").strip()[:MAX_TITLE_CHARS] or "New chat"

    def mutate(data):
        c = data.conversations.get(str(conversation_id))
        if c is not None:
            c.title = title

    stores.conversations.update(mutate)
    conv = get_conversation(conversation_id)
    if conv is None:
        raise KeyError(f"conversation {conversation_id} does not exist")
    return conv


def delete_conversation(conversation_id: int) -> bool:
    removed = {"ok": False}

    def mutate(data):
        removed["ok"] = data.conversations.pop(str(conversation_id), None) is not None

    stores.conversations.update(mutate)
    log.info("conversation_deleted", extra={"conversation_id": conversation_id, "deleted": removed["ok"]})
    return removed["ok"]


def append_message(conversation_id: int, role: str, content: str, language: str = "en",
                   now: datetime | None = None) -> Conversation:
    stamp = now or datetime.now(timezone.utc)

    def mutate(data):
        c = data.conversations[str(conversation_id)]
        c.messages.append(Message(role=role, content=content, language=language, timestamp=stamp))
        c.updated_at = stamp
        if role == "user":
            c.language = language
            if c.title == "New chat":
                c.title = make_title(content)

    stores.conversations.update(mutate)
    return get_conversation(conversation_id)  # type: ignore[return-value]


def set_context(conversation_id: int, *, language: str | None = None, last_city: str | None = ...,
                pending: dict | None = ...) -> None:
    """Persist the assistant's follow-up state so it survives a conversation switch or a restart.
    `last_city`/`pending` default to `...` (leave unchanged) so callers can clear them with None."""
    def mutate(data):
        c = data.conversations.get(str(conversation_id))
        if c is None:
            return
        if language is not None:
            c.language = language
        if last_city is not ...:
            c.last_city = last_city
        if pending is not ...:
            c.pending = pending

    stores.conversations.update(mutate)
