"""Nepal political news: recent developments, always retrieved from a real news provider — never
generated or recalled from the LLM's own (possibly stale or wrong) training data. Mirrors
services/news.py's football-article fetch, with three things football news didn't need:
deduplication (the same wire story often gets republished by several outlets), a soft preference
for well-known outlets, and a summarizer prompt that keeps reported facts and political
claims/opinions visibly separate and never recommends a party or candidate.

Modularity: fetch_nepal_political_news() is the only function callers use. Its current
implementation calls NewsAPI (_fetch_from_newsapi), but that is an internal detail — swapping in an
RSS feed or a different search API later only means changing what this one function calls
internally, not any caller in assistant/handlers.py.
"""
from __future__ import annotations

import difflib
import logging
import re
from datetime import datetime, timedelta, timezone

from config import require_key, settings
from services.http import TTLCache, get_json
from services.news import Article

log = logging.getLogger(__name__)
NEWS_URL = "https://newsapi.org/v2/everything"
_cache = TTLCache()

# Political-only query: keep this narrow so results are about government/parties/elections, not
# general Nepal news (tourism, sport, weather, etc.) that would dilute a "political news" request.
QUERY = ('"Nepal" AND (politics OR government OR parliament OR "prime minister" OR minister OR '
        'party OR election OR cabinet OR coalition OR "constituent assembly")')

# Soft preference only (never a hard filter — an unlisted outlet is still shown, just ranked
# below these when there's a tie on recency). Mixes international wires and Nepali outlets.
_PREFERRED_SOURCES = (
    "reuters", "associated press", "ap ", "bbc", "al jazeera",
    "kathmandu post", "the himalayan times", "himalayan times", "republica", "myrepublica",
    "onlinekhabar", "setopati", "nepali times", "annapurna post", "ratopati",
)


def _is_preferred(source: str) -> bool:
    s = source.lower()
    return any(name in s for name in _PREFERRED_SOURCES)


def _normalize_title(title: str) -> str:
    return re.sub(r"[^\w\s]", "", title.lower()).strip()


def _dedup(articles: list[Article]) -> list[Article]:
    """Drop near-duplicate stories (the same development reported by several outlets). Keeps the
    first occurrence of each cluster, which — since articles arrive sorted newest first — is the
    most recent report of that story."""
    kept: list[Article] = []
    seen_norm: list[str] = []
    for a in articles:
        norm = _normalize_title(a.title)
        if any(difflib.SequenceMatcher(None, norm, s).ratio() > 0.8 for s in seen_norm):
            continue
        kept.append(a)
        seen_norm.append(norm)
    return kept


def _fetch_from_newsapi(count: int) -> list[Article]:
    key = require_key(settings.news_api_key, "NEWS_API_KEY")
    since = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
    data = get_json("NewsAPI", NEWS_URL, headers={"X-Api-Key": key}, params={
        "q": QUERY, "language": "en", "sortBy": "publishedAt", "pageSize": min(count * 4, 40), "from": since,
    })
    articles = []
    for a in (data.get("articles") or []) if isinstance(data, dict) else []:
        title = (a.get("title") or "").strip()
        desc = (a.get("description") or "").strip()
        if not title or title == "[Removed]":
            continue
        try:
            published = datetime.fromisoformat((a.get("publishedAt") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        articles.append(Article(title=title, description=desc,
                                source=(a.get("source") or {}).get("name") or "Unknown",
                                url=a.get("url") or "", published_at=published))
    return articles


def fetch_nepal_political_news(count: int = 6) -> list[Article]:
    """Recent Nepal political news: deduplicated, newest first, well-known outlets preferred on
    ties. Cached for 10 minutes (same rationale as services/news.py — stay inside free-tier limits
    without serving stale news for hours)."""

    def fetch() -> list[Article]:
        articles = _fetch_from_newsapi(count)
        articles = _dedup(articles)
        articles.sort(key=lambda a: (_is_preferred(a.source), a.published_at), reverse=True)
        return articles[:count]

    articles = _cache.get_or_set(("nepal_politics", count), 600, fetch)
    log.info("nepal_news_fetched", extra={"count": len(articles)})
    return articles
