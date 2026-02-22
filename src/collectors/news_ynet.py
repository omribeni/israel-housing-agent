"""
Collector for Ynet real-estate news articles.

Scrapes the Ynet economy/realestate section and extracts article metadata
(title, URL, snippet, publication date) from the listing page.
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

_BASE_URL = "https://www.ynet.co.il"
_SECTION_URL = f"{_BASE_URL}/economy/category/8315"
_MAX_ARTICLES = 20


class YnetCollector(BaseCollector):
    """Collects housing-related articles from Ynet's real-estate section."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def source_name(self) -> str:
        return "ynet"

    async def collect(self) -> list[RawArticle]:
        """Fetch the Ynet real-estate listing page and extract articles."""
        try:
            html = await fetch_page(_SECTION_URL, self._settings)
            return self._parse(html)
        except Exception:
            logger.exception("YnetCollector failed to collect articles")
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse(self, html: str) -> list[RawArticle]:
        soup = BeautifulSoup(html, "lxml")
        articles: list[RawArticle] = []
        seen_urls: set[str] = set()

        # Strategy 1: look for common Ynet card containers that hold an
        # <a> tag with an article-like href.
        link_candidates = soup.find_all("a", href=True)

        for link in link_candidates:
            href: str = link["href"]

            # Only consider links that look like article URLs
            if not self._is_article_url(href):
                continue

            url = urljoin(_BASE_URL, href)

            # Deduplicate by URL
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

        logger.info("YnetCollector parsed %d articles", len(articles))
        return articles

    @staticmethod
    def _is_article_url(href: str) -> bool:
        """Return True if the href looks like a Ynet article link."""
        # Ynet article URLs typically contain '/article/' or numeric IDs
        # under the economy section.
        if "/article/" in href:
            return True
        if "/economy/" in href and "/category/8315" not in href:
            # Must have something beyond the section root
            parts = href.rstrip("/").split("/")
            if len(parts) >= 4:
                return True
        return False

    @staticmethod
    def _extract_title(link_tag) -> str:
        """Try to pull a meaningful title from the <a> or its parent heading."""
        # Check if the <a> wraps a heading element
        heading = link_tag.find(["h1", "h2", "h3", "h4", "h5", "h6"])
        if heading and heading.get_text(strip=True):
            return heading.get_text(strip=True)

        # Check if the <a> itself is inside a heading
        for parent in link_tag.parents:
            if parent.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                return parent.get_text(strip=True)
            # Don't go further than two levels up
            if parent.name in ("div", "article", "section", "body"):
                break

        # Fallback: the link's own text
        text = link_tag.get_text(strip=True)
        if text and len(text) > 5:
            return text

        # Try title attribute
        return link_tag.get("title", "").strip()

    @staticmethod
    def _extract_snippet(link_tag) -> str:
        """Extract a short description from sibling or nearby <p> elements."""
        # Walk up to the nearest container and look for <p> text
        container = link_tag.find_parent(["div", "article", "section", "li"])
        if container:
            paragraphs = container.find_all("p")
            for p in paragraphs:
                text = p.get_text(strip=True)
                if text and len(text) > 15:
                    return text[:500]
            # Try any span/div with description-like class names
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

        # Look for elements with date-like class names
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
