"""
Collector for the Israel Land Authority (ILA / rmi) site at land.gov.il.

Scraping strategy
-----------------
The Israel Land Authority (Rashut Mekarke'ei Yisrael) publishes information
about land tenders, housing marketing, and public announcements on land.gov.il.

The site is SharePoint-based with Hebrew content. We scrape:
1. The main page for featured announcements and banners.
2. Known paths for tenders and land marketing news.
3. Any news/updates feed we can locate.

Because this is a government SharePoint site, the HTML structure may include
deeply nested tables, ASP.NET view-state blobs, and Hebrew right-to-left
markup. We use multiple CSS selector strategies to extract content.

All network calls are wrapped in try/except so errors never crash the pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
from bs4 import BeautifulSoup, Tag

from src.collectors.base import BaseCollector, RawArticle
from src.config import Settings
from src.utils.http_client import fetch_page

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://land.gov.il"

# Pages to scrape. The ILA site often reorganises its paths, so we try
# several known locations. Paths that return 404 are silently skipped.
_TARGET_PAGES = [
    # Main homepage -- often has featured tenders / news banners
    _BASE_URL,
    # News and announcements section
    f"{_BASE_URL}/he/Pages/News.aspx",
    f"{_BASE_URL}/he/Pages/newsList.aspx",
    # Tenders and land marketing
    f"{_BASE_URL}/he/Pages/Tenders.aspx",
    f"{_BASE_URL}/he/Pages/LandMarketing.aspx",
    f"{_BASE_URL}/he/Pages/HousingMarketing.aspx",
    # Sometimes tenders are under a different path
    f"{_BASE_URL}/he/PublishingPages/Pages/Tenders.aspx",
]

# Browser-like user-agent to reduce chance of being blocked.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class LandGovCollector(BaseCollector):
    """Collects tender and land marketing announcements from land.gov.il."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    # BaseCollector interface
    # ------------------------------------------------------------------

    @property
    def source_name(self) -> str:
        return "land_gov"

    async def collect(self) -> list[RawArticle]:
        """Fetch and parse announcements from the ILA website.

        Tries multiple pages; aggregates whatever we can extract.
        Returns an empty list if everything fails.
        """
        all_articles: list[RawArticle] = []
        seen_urls: set[str] = set()

        for page_url in _TARGET_PAGES:
            try:
                html = await self._fetch_with_browser_headers(page_url)
                page_articles = self._parse_page(html, page_url)

                # Deduplicate by URL within a single collection run.
                for article in page_articles:
                    if article.url not in seen_urls:
                        seen_urls.add(article.url)
                        all_articles.append(article)

                logger.debug(
                    "Extracted %d items from %s", len(page_articles), page_url
                )
            except httpx.HTTPStatusError as exc:
                # 404 / 403 are expected -- the site restructures often.
                logger.debug(
                    "HTTP %s for %s (expected for missing pages)",
                    exc.response.status_code,
                    page_url,
                )
            except Exception:
                logger.warning(
                    "Failed to fetch/parse ILA page: %s", page_url, exc_info=True
                )

        logger.info(
            "LandGovCollector finished: %d total articles", len(all_articles)
        )
        return all_articles

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _fetch_with_browser_headers(self, url: str) -> str:
        """Fetch a page with browser-like headers.

        We use httpx directly (instead of fetch_page) so we can set
        Accept-Language and other headers that help with Hebrew content
        and SharePoint compatibility.
        """
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._settings.http_timeout),
            follow_redirects=True,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
            },
            verify=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text

    # ------------------------------------------------------------------
    # HTML parsing
    # ------------------------------------------------------------------

    def _parse_page(self, html: str, page_url: str) -> list[RawArticle]:
        """Extract announcements/tenders from an HTML page.

        The ILA site (SharePoint-based) uses various layouts depending on
        the page type. We try multiple extraction strategies in order of
        specificity.
        """
        soup = BeautifulSoup(html, "html.parser")
        articles: list[RawArticle] = []

        # Strategy 1: SharePoint list items / news web parts.
        articles.extend(self._extract_sharepoint_items(soup, page_url))

        # Strategy 2: Structured card / tile elements.
        if not articles:
            articles.extend(self._extract_card_items(soup, page_url))

        # Strategy 3: Generic link extraction from content area.
        if not articles:
            articles.extend(self._extract_content_links(soup, page_url))

        # Strategy 4: Table-based tender listings (common in gov sites).
        if not articles:
            articles.extend(self._extract_table_rows(soup, page_url))

        return articles

    def _extract_sharepoint_items(
        self, soup: BeautifulSoup, page_url: str
    ) -> list[RawArticle]:
        """Extract items from SharePoint list/news web parts."""
        articles: list[RawArticle] = []

        # SharePoint often renders news in divs with specific class patterns.
        sp_selectors = [
            "div.ms-listviewtable tr",
            "div.slm-layout-main div.item",
            "div.dfwp-list li",
            "div.news-item",
            "div.tender-item",
            "div[class*='NewsItem']",
            "div[class*='TenderItem']",
            "div[class*='news-webpart'] li",
            "div[class*='cbs-List'] li",
            "ul.cbs-List li",
        ]

        for selector in sp_selectors:
            elements = soup.select(selector)
            for el in elements:
                article = self._element_to_article(el, page_url, "sharepoint_item")
                if article:
                    articles.append(article)
            if articles:
                break  # Found items with this selector; no need to try more.

        return articles

    def _extract_card_items(
        self, soup: BeautifulSoup, page_url: str
    ) -> list[RawArticle]:
        """Extract items from card/tile-style layouts."""
        articles: list[RawArticle] = []

        card_selectors = [
            "div.card",
            "div.tile",
            "article",
            "div.announcement",
            "div.tender-card",
            "div[class*='Card']",
            "div[class*='Tile']",
            "li.result-item",
        ]

        for selector in card_selectors:
            cards = soup.select(selector)
            for card in cards:
                article = self._element_to_article(card, page_url, "card_item")
                if article:
                    articles.append(article)
            if articles:
                break

        return articles

    def _extract_content_links(
        self, soup: BeautifulSoup, page_url: str
    ) -> list[RawArticle]:
        """Extract links from the main content area of the page.

        Filters out navigation/footer links by focusing on the main content
        region and links that look like announcements or tenders.
        """
        articles: list[RawArticle] = []

        # Try to isolate the main content area.
        content_area = (
            soup.find("main")
            or soup.find("div", {"id": "contentBox"})
            or soup.find("div", {"id": "DeltaPlaceHolderMain"})
            or soup.find("div", role="main")
            or soup.find("div", {"class": "ms-rtestate-field"})
            or soup.body
        )

        if not content_area:
            return articles

        # Keywords that suggest a link is about housing/tenders (Hebrew).
        _relevance_keywords = [
            "מכרז", "שיווק", "קרקע", "דירה", "דיור", "מגורים",
            "הודעה", "חדש", "פרסום", "tender", "land", "housing",
            "מחיר", "הגרלה", "בניה", "בנייה", "תכנון",
        ]

        for link in content_area.find_all("a", href=True):
            href: str = link["href"]
            text = link.get_text(strip=True)

            # Skip empty links, anchors, javascript, and very short text.
            if not text or len(text) < 5:
                continue
            if href.startswith("#") or href.startswith("javascript:"):
                continue

            # Check if the link text or URL suggests relevance.
            combined = (text + " " + href).lower()
            is_relevant = any(kw in combined for kw in _relevance_keywords)
            if not is_relevant:
                continue

            full_url = self._resolve_url(href)

            articles.append(
                RawArticle(
                    url=full_url,
                    title=text[:200],
                    snippet=text[:500],
                    source=self.source_name,
                    metadata={"type": "content_link", "page": page_url},
                )
            )

        return articles

    def _extract_table_rows(
        self, soup: BeautifulSoup, page_url: str
    ) -> list[RawArticle]:
        """Extract tender/announcement data from HTML tables.

        Government sites frequently list tenders in <table> elements.
        """
        articles: list[RawArticle] = []

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            # Skip tables with fewer than 2 rows (just a header).
            if len(rows) < 2:
                continue

            # Use the first row as headers (if present).
            header_cells = rows[0].find_all(["th", "td"])
            headers = [cell.get_text(strip=True) for cell in header_cells]

            for row in rows[1:]:
                cells = row.find_all("td")
                if not cells:
                    continue

                # Build a text representation of the row.
                cell_texts = [cell.get_text(strip=True) for cell in cells]
                row_text = " | ".join(t for t in cell_texts if t)

                if not row_text or len(row_text) < 10:
                    continue

                # Find the first link in the row.
                link_tag = row.find("a", href=True)
                url = self._resolve_url(link_tag["href"]) if link_tag else page_url
                title = link_tag.get_text(strip=True) if link_tag else cell_texts[0]

                # Build metadata from header-cell pairs.
                metadata: dict[str, str] = {"type": "table_row", "page": page_url}
                for i, header in enumerate(headers):
                    if i < len(cell_texts) and header and cell_texts[i]:
                        metadata[header] = cell_texts[i]

                articles.append(
                    RawArticle(
                        url=url,
                        title=title[:200] if title else row_text[:200],
                        snippet=row_text[:500],
                        source=self.source_name,
                        metadata=metadata,
                    )
                )

        return articles

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _element_to_article(
        self, el: Tag, page_url: str, extraction_type: str
    ) -> RawArticle | None:
        """Convert a generic HTML element to a RawArticle.

        Attempts to extract a title, link, snippet, and optional date.
        Returns None if there is not enough content to form a useful article.
        """
        try:
            # Extract title from heading tags or the first link.
            title_tag = el.find(["h1", "h2", "h3", "h4", "a"])
            title = title_tag.get_text(strip=True) if title_tag else ""

            # Get full text content as snippet.
            full_text = el.get_text(strip=True)
            snippet = full_text[:500]

            # Skip elements with very little content.
            if not title and len(full_text) < 15:
                return None

            if not title:
                title = full_text[:150]

            # Find a link.
            link_tag = el.find("a", href=True)
            url = self._resolve_url(link_tag["href"]) if link_tag else page_url

            # Try to extract a date from the element.
            date = self._extract_date_from_element(el)

            return RawArticle(
                url=url,
                title=title,
                snippet=snippet,
                source=self.source_name,
                published_date=date,
                metadata={"type": extraction_type, "page": page_url},
            )
        except Exception:
            return None

    def _resolve_url(self, href: str) -> str:
        """Resolve a potentially relative URL to an absolute one."""
        if not href:
            return _BASE_URL
        if href.startswith("http://") or href.startswith("https://"):
            return href
        if href.startswith("/"):
            return f"{_BASE_URL}{href}"
        return f"{_BASE_URL}/{href}"

    @staticmethod
    def _extract_date_from_element(el: Tag) -> datetime | None:
        """Try to find and parse a date within an HTML element.

        Looks for common date patterns in time tags or spans with
        date-related classes.
        """
        # <time> tag with datetime attribute
        time_tag = el.find("time")
        if time_tag:
            dt_attr = time_tag.get("datetime", "")
            parsed = _try_parse_date(dt_attr)
            if parsed:
                return parsed
            # Fall back to text content of the <time> tag.
            parsed = _try_parse_date(time_tag.get_text(strip=True))
            if parsed:
                return parsed

        # Spans or divs with date-related classes.
        for date_el in el.find_all(["span", "div"], class_=lambda c: c and "date" in c.lower()):
            parsed = _try_parse_date(date_el.get_text(strip=True))
            if parsed:
                return parsed

        return None


# ---------------------------------------------------------------------------
# Module-level utility
# ---------------------------------------------------------------------------

def _try_parse_date(date_str: str) -> datetime | None:
    """Attempt to parse a date string in common formats used by Israeli gov sites."""
    if not date_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d.%m.%Y",
        "%d.%m.%Y %H:%M",
    ):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None
