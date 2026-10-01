"""Personal-context / memory layer: things the user has told Awaaz to remember about themselves
(profile, preferences, education, projects, research, people, schedule, free-form notes).

Kept deliberately separate from general knowledge:
* Stored in its own file (data/personal_context.json, gitignored like every data/ file — see
  .gitignore and README §12) rather than mixed into conversation history or app config.
* Never sent to the LLM in bulk. assistant/handlers.py's handle_personal_query() retrieves only
  the few facts relevant to the current question (search_facts(), a lightweight keyword-overlap
  ranking — no embeddings/vector store needed at this scale) and injects just those into a prompt
  that is explicitly told to answer ONLY from what it was given. If nothing relevant is found, the
  caller is expected to say so rather than let the LLM invent an answer from its general knowledge
  (see generate_personal_answer() in assistant/response_generator.py).
* No fact is ever created except when the user explicitly asks Awaaz to remember something —
  Awaaz never infers or stores personal information on its own initiative.
"""
from __future__ import annotations

import difflib
import logging
import re
from datetime import datetime, timezone

from database import stores
from database.models import PersonalCategory, PersonalFact

log = logging.getLogger(__name__)
MAX_TITLE = 120
MAX_CONTENT = 1000
_WORD_RE = re.compile(r"\w+", re.UNICODE)


class PersonalContextError(ValueError):
    """Validation problem that should be shown to the user."""


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "") if len(w) > 2}


def _clean(title: str, content: str) -> tuple[str, str]:
    title = (title or "").strip()
    content = (content or "").strip()
    if not content:
        raise PersonalContextError("there is nothing to remember — the content was empty")
    if not title:
        title = content[:60]
    if len(title) > MAX_TITLE:
        raise PersonalContextError(f"the title is too long (max {MAX_TITLE} characters)")
    if len(content) > MAX_CONTENT:
        raise PersonalContextError(f"that's too long to remember in one note (max {MAX_CONTENT} characters)")
    return title, content


def remember(title: str, content: str, category: PersonalCategory = "note") -> PersonalFact:
    """Save a new fact, or update an existing one if its title matches closely (so "remember my
    favourite colour is blue" said twice updates the same fact instead of duplicating it)."""
    title, content = _clean(title, content)
    existing = find_by_title(title)
    stamp = datetime.now(timezone.utc)
    saved: dict[str, PersonalFact] = {}

    def mutate(data):
        if existing is not None:
            fact = data.facts[str(existing.id)]
            fact.content, fact.category, fact.updated_at = content, category, stamp
            saved["fact"] = fact
        else:
            fid = data.next_id
            data.next_id += 1
            fact = PersonalFact(id=fid, category=category, title=title, content=content,
                                created_at=stamp, updated_at=stamp)
            data.facts[str(fid)] = fact
            saved["fact"] = fact

    stores.personal_context.update(mutate)
    log.info("personal_fact_saved", extra={"fact_id": saved["fact"].id, "category": category,
                                           "updated": existing is not None})
    return saved["fact"]


def list_facts(category: PersonalCategory | None = None) -> list[PersonalFact]:
    items = list(stores.personal_context.read().facts.values())
    if category:
        items = [f for f in items if f.category == category]
    items.sort(key=lambda f: f.updated_at, reverse=True)
    return items


def get_fact(fact_id: int) -> PersonalFact | None:
    return stores.personal_context.read().facts.get(str(fact_id))


def find_by_title(title: str) -> PersonalFact | None:
    q = (title or "").strip().lower()
    if not q:
        return None
    for f in stores.personal_context.read().facts.values():
        if f.title.lower() == q:
            return f
    return None


def delete_fact(fact_id: int) -> bool:
    found = {"ok": False}

    def mutate(data):
        if str(fact_id) in data.facts:
            del data.facts[str(fact_id)]
            found["ok"] = True

    stores.personal_context.update(mutate)
    return found["ok"]


def search_facts(query: str, limit: int = 3, min_overlap: int = 1) -> list[PersonalFact]:
    """Lightweight retrieval: rank stored facts by word overlap with the query (title counted
    double), falling back to fuzzy title matching for near-misses like "wat's my emial". Returns
    only facts that clear `min_overlap`, so an unrelated question legitimately returns nothing —
    the caller must treat an empty result as "Awaaz doesn't know this," never search harder or guess.
    Deliberately not a vector/embedding search: at the scale of a personal note store (tens to a
    few hundred facts) exact/fuzzy word overlap is simpler, needs no extra API calls or model, and
    is easy to explain and test — see README's "how personal context works" section."""
    q_words = _words(query)
    if not q_words:
        return []
    all_facts = list(stores.personal_context.read().facts.values())
    scored: list[tuple[float, PersonalFact]] = []
    for f in all_facts:
        score = 2 * len(q_words & _words(f.title)) + len(q_words & _words(f.content))
        if score >= min_overlap:
            scored.append((score, f))
    if scored:
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [f for _, f in scored[:limit]]
    # No word-overlap hit at all — try fuzzy word matching (typos, ASR misrecognition), comparing
    # individual query words against individual title words rather than the whole strings, so a
    # short misspelled word ("supervisr") still matches inside a longer question.
    title_words = {w for f in all_facts for w in _words(f.title)}
    fuzzy_hits = {w: difflib.get_close_matches(w, title_words, n=1, cutoff=0.75) for w in q_words}
    matched_words = {hit[0] for hit in fuzzy_hits.values() if hit}
    if not matched_words:
        return []
    fuzzy_scored = [(len(matched_words & _words(f.title)), f) for f in all_facts]
    fuzzy_scored = [(s, f) for s, f in fuzzy_scored if s > 0]
    fuzzy_scored.sort(key=lambda pair: pair[0], reverse=True)
    return [f for _, f in fuzzy_scored[:limit]]
