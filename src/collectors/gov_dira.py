"""
Collector for the Ministry of Construction housing portal (dira.moch.gov.il).

Scraping strategy
-----------------
The dira.moch.gov.il site is a Single-Page Application (Angular) that loads
data through internal REST API endpoints.  We attempt two approaches:

1. **Primary (API)**  -- Hit known JSON endpoints that back the SPA:
   - /api/Lottery/GetLotteries  -- current housing lotteries
   - /api/Projects/GetProjects  -- marketed projects

   These endpoints may require specific headers, query parameters, or tokens
   that change over time. If they return valid JSON we parse it directly.

2. **Fallback (HTML scraping)** -- If the API calls fail (403, 404, changed
   contract, etc.) we fall back to fetching the rendered HTML pages and
   extracting whatever announcement/project information is available via
   BeautifulSoup.

Government sites are notoriously fragile; every external call is wrapped in
try/except so the collector never crashes the pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector, RawArticle
from src.config import Settings
from src.utils.http_client import fetch_page

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://dira.moch.gov.il"

# Known (or suspected) API endpoints behind the SPA.
# These may change without notice -- keep this list up-to-date.
_API_LOTTERIES = f"{_BASE_URL}/api/Lottery/GetLotteries"
_API_PROJECTS = f"{_BASE_URL}/api/Projects/GetProjects"

# Fallback HTML pages to scrape when the API is unavailable.
_FALLBACK_PAGES = [
    _BASE_URL,
    f"{_BASE_URL}/ProjectList",
    f"{_BASE_URL}/LotteryList",
]

# Browser-like user-agent to reduce chance of being blocked.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class DiraGovCollector(BaseCollector):
    """Collects housing lottery and project data from dira.moch.gov.il."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    # BaseCollector interface
    # ------------------------------------------------------------------

    @property
    def source_name(self) -> str:
        return "dira_gov"

    async def collect(self) -> list[RawArticle]:
        """Fetch lottery/project data, trying API first then HTML fallback.

        Returns an empty list if all approaches fail.
        """
        articles: list[RawArticle] = []

        # --- Attempt 1: JSON API endpoints ---
        api_articles = await self._try_api_endpoints()
        if api_articles:
            logger.info(
                "DiraGovCollector: API returned %d articles", len(api_articles)
            )
            return api_articles

        # --- Attempt 2: HTML fallback ---
        logger.info(
            "DiraGovCollector: API endpoints unavailable, falling back to HTML scraping"
        )
        html_articles = await self._try_html_fallback()
        if html_articles:
            logger.info(
                "DiraGovCollector: HTML scraping returned %d articles",
                len(html_articles),
            )
            return html_articles

        logger.warning("DiraGovCollector: all collection methods failed, returning empty list")
        return articles

    # ------------------------------------------------------------------
    # API approach
    # ------------------------------------------------------------------

    async def _try_api_endpoints(self) -> list[RawArticle]:
        """Try fetching JSON from the site's internal API endpoints."""
        articles: list[RawArticle] = []

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._settings.http_timeout),
            follow_redirects=True,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
                # The SPA may check for this header to distinguish AJAX calls.
                "X-Requested-With": "XMLHttpRequest",
            },
            # Government sites sometimes have self-signed or outdated certs.
            verify=True,
        ) as client:
            # --- Lotteries ---
            articles.extend(await self._fetch_lotteries(client))

            # --- Projects ---
            articles.extend(await self._fetch_projects(client))

        return articles

    async def _fetch_lotteries(self, client: httpx.AsyncClient) -> list[RawArticle]:
        """Fetch lotteries from the API and convert to RawArticle objects."""
        try:
            resp = await client.get(_API_LOTTERIES)
            resp.raise_for_status()

            data = resp.json()

            # The response structure is not documented. Common patterns:
            #   - Top-level list of lottery objects
            #   - Wrapped in {"data": [...]} or {"lotteries": [...]}
            lotteries = self._extract_list(data, keys=["data", "lotteries", "Lotteries"])

            articles: list[RawArticle] = []
            for lottery in lotteries:
                article = self._lottery_to_article(lottery)
                if article:
                    articles.append(article)

            logger.debug("Parsed %d lotteries from API", len(articles))
            return articles

        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Lottery API returned HTTP %s: %s", exc.response.status_code, exc
            )
        except Exception:
            logger.exception("Unexpected error fetching lotteries API")

        return []

    async def _fetch_projects(self, client: httpx.AsyncClient) -> list[RawArticle]:
        """Fetch projects from the API and convert to RawArticle objects."""
        try:
            resp = await client.get(_API_PROJECTS)
            resp.raise_for_status()

            data = resp.json()
            projects = self._extract_list(data, keys=["data", "projects", "Projects"])

            articles: list[RawArticle] = []
            for project in projects:
                article = self._project_to_article(project)
                if article:
                    articles.append(article)

            logger.debug("Parsed %d projects from API", len(articles))
            return articles

        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Projects API returned HTTP %s: %s", exc.response.status_code, exc
            )
        except Exception:
            logger.exception("Unexpected error fetching projects API")

        return []

    # ------------------------------------------------------------------
    # JSON helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_list(data: object, keys: list[str]) -> list[dict]:
        """Pull a list from `data`, trying it directly or under known keys."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in keys:
                if key in data and isinstance(data[key], list):
                    return data[key]
        return []

    def _lottery_to_article(self, lottery: dict) -> RawArticle | None:
        """Convert a single lottery JSON object to a RawArticle."""
        try:
            # Try several key naming conventions the API might use.
            lottery_id = lottery.get("LotteryId") or lottery.get("lotteryId") or lottery.get("id", "")
            project_name = (
                lottery.get("ProjectName")
                or lottery.get("projectName")
                or lottery.get("LotteryProjectName")
                or ""
            )
            city = (
                lottery.get("CityDescription")
                or lottery.get("cityDescription")
                or lottery.get("City")
                or lottery.get("city")
                or ""
            )
            program_type = (
                lottery.get("LotteryPlanDescription")
                or lottery.get("PlanTypeDescription")
                or lottery.get("planType")
                or ""
            )
            num_units = lottery.get("UnitCount") or lottery.get("unitCount") or ""
            registration_end = (
                lottery.get("RegistrationEndDate")
                or lottery.get("registrationEndDate")
                or ""
            )
            lottery_date = (
                lottery.get("LotteryDate")
                or lottery.get("lotteryDate")
                or ""
            )

            title = f"{project_name} - {city}".strip(" -") if (project_name or city) else f"Lottery {lottery_id}"

            snippet_parts = []
            if program_type:
                snippet_parts.append(f"Program: {program_type}")
            if num_units:
                snippet_parts.append(f"Units: {num_units}")
            if registration_end:
                snippet_parts.append(f"Registration ends: {registration_end}")
            if lottery_date:
                snippet_parts.append(f"Lottery date: {lottery_date}")
            snippet = " | ".join(snippet_parts) if snippet_parts else "Housing lottery"

            url = f"{_BASE_URL}/Lottery/{lottery_id}" if lottery_id else _BASE_URL

            return RawArticle(
                url=url,
                title=title,
                snippet=snippet[:500],
                source=self.source_name,
                published_date=self._try_parse_date(registration_end or lottery_date),
                metadata={
                    k: v
                    for k, v in {
                        "lottery_id": str(lottery_id),
                        "city": city,
                        "program_type": program_type,
                        "unit_count": str(num_units) if num_units else "",
                        "registration_end": str(registration_end),
                        "lottery_date": str(lottery_date),
                        "type": "lottery",
                    }.items()
                    if v
                },
            )
        except Exception:
            logger.debug("Skipping unparseable lottery entry: %s", lottery)
            return None

    def _project_to_article(self, project: dict) -> RawArticle | None:
        """Convert a single project JSON object to a RawArticle."""
        try:
            project_id = project.get("ProjectId") or project.get("projectId") or project.get("id", "")
            project_name = (
                project.get("ProjectName")
                or project.get("projectName")
                or project.get("Name")
                or ""
            )
            city = (
                project.get("CityDescription")
                or project.get("cityDescription")
                or project.get("City")
                or project.get("city")
                or ""
            )
            contractor = (
                project.get("ContractorDescription")
                or project.get("contractorName")
                or ""
            )
            num_units = project.get("UnitCount") or project.get("unitCount") or ""

            title = f"{project_name} - {city}".strip(" -") if (project_name or city) else f"Project {project_id}"

            snippet_parts = []
            if contractor:
                snippet_parts.append(f"Contractor: {contractor}")
            if num_units:
                snippet_parts.append(f"Units: {num_units}")
            snippet = " | ".join(snippet_parts) if snippet_parts else "Housing project"

            url = f"{_BASE_URL}/Project/{project_id}" if project_id else _BASE_URL

            return RawArticle(
                url=url,
                title=title,
                snippet=snippet[:500],
                source=self.source_name,
                metadata={
                    k: v
                    for k, v in {
                        "project_id": str(project_id),
                        "city": city,
                        "contractor": contractor,
                        "unit_count": str(num_units) if num_units else "",
                        "type": "project",
                    }.items()
                    if v
                },
            )
        except Exception:
            logger.debug("Skipping unparseable project entry: %s", project)
            return None

    # ------------------------------------------------------------------
    # HTML fallback approach
    # ------------------------------------------------------------------

    async def _try_html_fallback(self) -> list[RawArticle]:
        """Scrape HTML pages when the API is unavailable."""
        articles: list[RawArticle] = []

        for page_url in _FALLBACK_PAGES:
            try:
                html = await fetch_page(page_url, self._settings)
                page_articles = self._parse_html_page(html, page_url)
                articles.extend(page_articles)
                logger.debug(
                    "Extracted %d items from %s", len(page_articles), page_url
                )
            except Exception:
                logger.warning("Failed to fetch/parse fallback page: %s", page_url)

        return articles

    def _parse_html_page(self, html: str, page_url: str) -> list[RawArticle]:
        """Extract project/announcement items from an HTML page.

        The site layout may change at any time. We look for common patterns:
        - Cards or list items with project titles and links
        - News/announcement sections
        - Any element with identifiable project data (city, units, dates)
        """
        articles: list[RawArticle] = []
        soup = BeautifulSoup(html, "html.parser")

        # Strategy 1: Look for project/lottery card elements.
        # Common CSS classes in Angular government SPAs.
        card_selectors = [
            "div.project-card",
            "div.lottery-card",
            "div.card",
            "mat-card",
            "li.project-item",
            "li.lottery-item",
            "div.project-row",
            "tr.project-row",
        ]
        for selector in card_selectors:
            cards = soup.select(selector)
            for card in cards:
                article = self._card_to_article(card, page_url)
                if article:
                    articles.append(article)

        # Strategy 2: Look for links that point to project/lottery detail pages.
        # Typical patterns: /Lottery/123, /Project/456
        if not articles:
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if "/Lottery/" in href or "/Project/" in href:
                    full_url = href if href.startswith("http") else f"{_BASE_URL}{href}"
                    title = link.get_text(strip=True) or href
                    articles.append(
                        RawArticle(
                            url=full_url,
                            title=title,
                            snippet="",
                            source=self.source_name,
                            metadata={"type": "link_extraction", "page": page_url},
                        )
                    )

        # Strategy 3: Look for any news/announcement section.
        if not articles:
            news_selectors = [
                "div.news",
                "section.announcements",
                "div.announcement",
                "div.updates",
                "ul.news-list",
            ]
            for selector in news_selectors:
                for section in soup.select(selector):
                    for item in section.find_all(["li", "div", "article"]):
                        text = item.get_text(strip=True)
                        link_tag = item.find("a", href=True)
                        url = (
                            link_tag["href"]
                            if link_tag
                            else page_url
                        )
                        if url and not url.startswith("http"):
                            url = f"{_BASE_URL}{url}"
                        if text:
                            articles.append(
                                RawArticle(
                                    url=url,
                                    title=text[:150],
                                    snippet=text[:500],
                                    source=self.source_name,
                                    metadata={"type": "news_section", "page": page_url},
                                )
                            )

        return articles

    def _card_to_article(self, card: BeautifulSoup, page_url: str) -> RawArticle | None:
        """Convert an HTML card element to a RawArticle."""
        try:
            # Extract text content.
            title_el = card.find(["h2", "h3", "h4", "span.title", "div.title"])
            title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)[:150]
            if not title:
                return None

            snippet = card.get_text(strip=True)[:500]

            # Try to find a link inside the card.
            link_tag = card.find("a", href=True)
            url = link_tag["href"] if link_tag else page_url
            if url and not url.startswith("http"):
                url = f"{_BASE_URL}{url}"

            return RawArticle(
                url=url,
                title=title,
                snippet=snippet,
                source=self.source_name,
                metadata={"type": "html_card", "page": page_url},
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _try_parse_date(date_str: str) -> datetime | None:
        """Attempt to parse a date string in common formats."""
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
        ):
            try:
                return datetime.strptime(date_str, fmt)
            except (ValueError, TypeError):
                continue
        return None
