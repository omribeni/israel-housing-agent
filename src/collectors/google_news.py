from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import feedparser
import httpx

from src.collectors.base import BaseCollector, RawArticle
from src.config import GOOGLE_NEWS_QUERIES, Settings

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _parse_date(date_str: str | None) -> datetime | None:
    """Try to parse common RSS date formats. Returns None on failure."""
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    # Fallback: try ISO-8601 variants
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    logger.debug("Unable to parse date string: %s", date_str)
    return None


class GoogleNewsCollector(BaseCollector):
    """Collects Hebrew-language housing news from Google News RSS feeds."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def source_name(self) -> str:
        return "google_news"

    async def collect(self) -> list[RawArticle]:
        """Fetch Google News RSS for every configured query and return articles."""
        all_articles: list[RawArticle] = []

        async with httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as client:
            for idx, query in enumerate(GOOGLE_NEWS_QUERIES):
                try:
                    articles = await self._fetch_query(client, query)
                    all_articles.extend(articles)
                    logger.info(
                        "Query '%s' returned %d articles", query, len(articles)
                    )
                except Exception:
                    logger.exception("Failed to fetch Google News for query '%s'", query)

                # Avoid rate-limiting; skip sleep after the last query
                if idx < len(GOOGLE_NEWS_QUERIES) - 1:
                    await asyncio.sleep(2)

        logger.info("GoogleNewsCollector finished: %d total articles", len(all_articles))
        return all_articles

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_query(
        self, client: httpx.AsyncClient, query: str
    ) -> list[RawArticle]:
        encoded_query = quote(query)
        url = (
            f"https://news.google.com/rss/search?"
            f"q={encoded_query}+when:1d&hl=iw&gl=IL&ceid=IL:he"
        )

        resp = await client.get(url)
        resp.raise_for_status()

        feed = feedparser.parse(resp.text)
        articles: list[RawArticle] = []

        for entry in feed.entries:
            article = RawArticle(
                url=entry.link,
                title=entry.title,
                snippet=entry.get("summary", "")[:500],
                source=self.source_name,
                published_date=_parse_date(entry.get("published")),
                metadata={"query": query},
            )
            articles.append(article)

        return articles
