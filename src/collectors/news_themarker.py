"""
Collector for TheMarker real-estate news articles.

Scrapes the TheMarker real-estate section and extracts article metadata
(title, URL, snippet, publication date) from the free listing page.

Note: TheMarker may have a paywall on individual articles. This collector
only scrapes the freely accessible listing/index page and does not attempt
to access paywalled content.
"""

from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector, RawArticle
from src.config import Settings
from src.utils.http_client import fetch_page

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.themarker.com"
_SECTION_URL = f"{_BASE_URL}/realestate"
_MAX_ARTICLES = 20


class TheMarkerCollector(BaseCollector):
    """Collects housing-related articles from TheMarker's real-estate section."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def source_name(self) -> str:
        return "themarker"

    async def collect(self) -> list[RawArticle]:
        """Fetch the TheMarker real-estate listing page and extract articles."""
        try:
            html = await fetch_page(_SECTION_URL, self._settings)
            return self._parse(html)
        except Exception:
            logger.exception("TheMarkerCollector failed to collect articles")
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse(self, html: str) -> list[RawArticle]:
        soup = BeautifulSoup(html, "lxml")
        articles: list[RawArticle] = []
        seen_urls: set[str] = set()

        link_candidates = soup.find_all("a", href=True)

        for link in link_candidates:
            href: str = link["href"]

            if not self._is_article_url(href):
                continue

            url = urljoin(_BASE_URL, href)

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = self._extract_title(link)
            if not title:
                continue

            snippet = self._extract_snippet(link)
            published = self._extract_date(link)

            articles.append(
                RawArticle(
                    url=url,
                    title=title,
                    snippet=snippet,
                    source=self.source_name,
                    published_date=published,
                )
            )

            if len(articles) >= _MAX_ARTICLES:
                break

        logger.info("TheMarkerCollector parsed %d articles", len(articles))
        return articles

    @staticmethod
    def _is_article_url(href: str) -> bool:
        """Return True if the href looks like a TheMarker article link."""
        # TheMarker (Haaretz family) article URLs typically contain
        # /article/ or have a pattern like /realestate/YYYY-MM-DD/...
        if "/article/" in href:
            return True
        if "/realestate/" in href:
            # Must be deeper than the section root
            stripped = href.rstrip("/")
            if stripped.endswith("/realestate"):
                return False
            parts = stripped.split("/")
            if len(parts) >= 4:
                return True
        # Haaretz-style .premium or numeric article IDs
        if ".premium" in href and ("/realestate" in href or "/market" in href):
            return True
        return False

    @staticmethod
    def _extract_title(link_tag) -> str:
        """Try to pull a meaningful title from the <a> or its parent heading."""
        heading = link_tag.find(["h1", "h2", "h3", "h4", "h5", "h6"])
        if heading and heading.get_text(strip=True):
            return heading.get_text(strip=True)

        for parent in link_tag.parents:
            if parent.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                return parent.get_text(strip=True)
            if parent.name in ("div", "article", "section", "body"):
                break

        text = link_tag.get_text(strip=True)
        if text and len(text) > 5:
            return text

        return link_tag.get("title", "").strip()

    @staticmethod
    def _extract_snippet(link_tag) -> str:
        """Extract a short description from sibling or nearby <p> elements."""
        container = link_tag.find_parent(["div", "article", "section", "li"])
        if container:
            paragraphs = container.find_all("p")
            for p in paragraphs:
                text = p.get_text(strip=True)
                if text and len(text) > 15:
                    return text[:500]
            for desc in container.find_all(
                ["span", "div"],
                class_=lambda c: c and any(
                    kw in (c if isinstance(c, str) else " ".join(c)).lower()
                    for kw in ("desc", "subtitle", "summary", "snippet", "blurb")
                ),
            ):
                text = desc.get_text(strip=True)
                if text and len(text) > 15:
                    return text[:500]
        return ""

    @staticmethod
    def _extract_date(link_tag) -> datetime | None:
        """Try to find a date near the article link."""
        container = link_tag.find_parent(["div", "article", "section", "li"])
        if not container:
            return None

        time_tag = container.find("time")
        if time_tag:
            dt_str = time_tag.get("datetime") or time_tag.get_text(strip=True)
            return _try_parse_date(dt_str)

        for el in container.find_all(
            ["span", "div"],
            class_=lambda c: c and any(
                kw in (c if isinstance(c, str) else " ".join(c)).lower()
                for kw in ("date", "time", "publish")
            ),
        ):
            text = el.get_text(strip=True)
            parsed = _try_parse_date(text)
            if parsed:
                return parsed

        return None


def _try_parse_date(date_str: str | None) -> datetime | None:
    """Attempt to parse a date string in common formats."""
    if not date_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
    ):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None
