"""NewsAPI football (soccer) articles. The API key is sent in a header so it never appears in URLs/logs."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config import require_key, settings
from services.http import TTLCache, get_json

log = logging.getLogger(__name__)
NEWS_URL = "https://newsapi.org/v2/everything"
_cache = TTLCache()

# Belt and braces: the query excludes these, and we filter again locally
AMERICAN_FOOTBALL = re.compile(
    r"\b(nfl|ncaa|college football|american football|super bowl|touchdown|quarterback|gridiron|"
    r"field goal|wide receiver|linebacker)\b", re.IGNORECASE)


@dataclass
class Article:
    title: str
    description: str
    source: str
    url: str
    published_at: datetime


def _clean_query_term(term: str) -> str:
    # NewsAPI query syntax: keep it to plain words so user input can't inject operators
    return re.sub(r"[^\w\s'-]", " ", term, flags=re.UNICODE).strip()[:80]


def fetch_football_articles(topic: str | None = None, count: int = 6) -> list[Article]:
    key = require_key(settings.news_api_key, "NEWS_API_KEY")
    base = '(soccer OR football OR "Premier League" OR "Champions League" OR "La Liga")'
    topic = _clean_query_term(topic or "")
    query = f'"{topic}" AND {base}' if topic else base
    query += ' NOT NFL NOT "college football" NOT "american football"'
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")

    def fetch():
        data = get_json("NewsAPI", NEWS_URL, headers={"X-Api-Key": key}, params={
            "q": query, "language": "en", "sortBy": "publishedAt", "pageSize": min(count * 3, 30), "from": since,
        })
        articles = []
        for a in (data.get("articles") or []) if isinstance(data, dict) else []:
            title = (a.get("title") or "").strip()
            desc = (a.get("description") or "").strip()
            if not title or title == "[Removed]" or AMERICAN_FOOTBALL.search(f"{title} {desc}"):
                continue
            try:
                published = datetime.fromisoformat((a.get("publishedAt") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            articles.append(Article(title=title, description=desc, source=(a.get("source") or {}).get("name") or "Unknown",
                                    url=a.get("url") or "", published_at=published))
        return articles

    articles = _cache.get_or_set(("news", query), 600, fetch)
    log.info("news_fetched", extra={"topic": topic or "general", "count": len(articles)})
    return articles[:count]
