"""
Collector for Israel Land Authority (ILA / רשות מקרקעי ישראל) data.

Data source: data.gov.il open data portal (CKAN API).

The original land.gov.il SharePoint site has been shut down — all URLs
redirect to www.gov.il, which is behind Cloudflare bot protection.

This collector queries data.gov.il for ILA-related datasets and the
"apartments for sale without lottery" resource as a complement to the
DiraGovCollector which handles lottery data.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from src.collectors.base import BaseCollector, RawArticle
from src.config import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# data.gov.il CKAN API
# ---------------------------------------------------------------------------

_CKAN_BASE = "https://data.gov.il/api/3/action/datastore_search"

# "Apartments for sale without lottery" — complements the lottery dataset
_APARTMENTS_RESOURCE_ID = "ea93b3c9-15e2-4b74-a632-097ee53737e4"

# Lottery dataset (same as gov_dira) — query with a different filter to find
# records specifically marketed by the Israel Land Authority
_LOTTERY_RESOURCE_ID = "7c8255d0-49ef-49db-8904-4cf917586031"

_PAGE_SIZE = 50

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class LandGovCollector(BaseCollector):
    """Collects ILA-related housing data from data.gov.il."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def source_name(self) -> str:
        return "land_gov"

    async def collect(self) -> list[RawArticle]:
        """Fetch ILA-related data from data.gov.il open data portal."""
        articles: list[RawArticle] = []

        async with httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as client:
            # Try the apartments-for-sale resource
            apt_articles = await self._fetch_apartments(client)
            articles.extend(apt_articles)

            # Query lottery data for ILA-marketed projects
            ila_articles = await self._fetch_ila_lotteries(client)
            articles.extend(ila_articles)

        logger.info("LandGovCollector finished: %d total articles", len(articles))
        return articles

    async def _fetch_apartments(self, client: httpx.AsyncClient) -> list[RawArticle]:
        """Fetch apartments-for-sale-without-lottery data."""
        try:
            resp = await client.get(
                _CKAN_BASE,
                params={
                    "resource_id": _APARTMENTS_RESOURCE_ID,
                    "limit": _PAGE_SIZE,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("success"):
                return []

            records = data.get("result", {}).get("records", [])
            if not records:
                logger.debug("Apartments-for-sale resource returned 0 records")
                return []

            logger.info("Fetched %d apartment-for-sale records", len(records))
            articles = []
            for record in records:
                article = self._apartment_to_article(record)
                if article:
                    articles.append(article)
            return articles

        except Exception:
            logger.debug("Failed to fetch apartments-for-sale data", exc_info=True)
            return []

    async def _fetch_ila_lotteries(self, client: httpx.AsyncClient) -> list[RawArticle]:
        """Fetch lottery records that mention ILA/land authority marketing."""
        try:
            resp = await client.get(
                _CKAN_BASE,
                params={
                    "resource_id": _LOTTERY_RESOURCE_ID,
                    "limit": _PAGE_SIZE,
                    "sort": "LotteryExecutionDate desc",
                    "q": "רשות מקרקעי",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("success"):
                return []

            records = data.get("result", {}).get("records", [])
            if not records:
                logger.debug("No ILA-specific lottery records found")
                return []

            logger.info("Fetched %d ILA-related lottery records", len(records))
            articles = []
            for record in records:
                article = self._lottery_to_article(record)
                if article:
                    articles.append(article)
            return articles

        except Exception:
            logger.debug("Failed to fetch ILA lottery data", exc_info=True)
            return []

    def _apartment_to_article(self, record: dict) -> RawArticle | None:
        """Convert an apartment-for-sale record to a RawArticle."""
        try:
            project_name = record.get("ProjectName", "") or record.get("project_name", "")
            city = record.get("CityName", "") or record.get("city_name", "")

            title_parts = [p for p in [project_name, city] if p]
            title = " - ".join(title_parts) if title_parts else "דירה למכירה"

            snippet_parts = []
            for key in ("ContractorName", "RoomCount", "Price", "Area", "Floor"):
                val = record.get(key, "")
                if val:
                    snippet_parts.append(f"{key}: {val}")
            snippet = " | ".join(snippet_parts) if snippet_parts else "דירה למכירה ללא הגרלה"

            return RawArticle(
                url="https://dira.moch.gov.il",
                title=title,
                snippet=snippet[:500],
                source=self.source_name,
                metadata={"type": "apartment_for_sale"},
            )
        except Exception:
            return None

    def _lottery_to_article(self, record: dict) -> RawArticle | None:
        """Convert an ILA lottery record to a RawArticle."""
        try:
            lottery_id = record.get("LotteryId", "")
            project_name = record.get("ProjectName", "")
            city = record.get("LamasName", "")
            provider = record.get("ProviderName", "")
            units = record.get("LotteryHousingUnits", "")
            marketing_method = record.get("MarketingMethodDesc", "")
            status = record.get("LotteryStatusValue", "")
            lottery_date = record.get("LotteryExecutionDate", "")

            title_parts = [p for p in [project_name, city] if p]
            title = " - ".join(title_parts) if title_parts else f"שיווק קרקע {lottery_id}"

            snippet_parts = []
            if marketing_method:
                snippet_parts.append(f"שיטת שיווק: {marketing_method}")
            if provider:
                snippet_parts.append(f"יזם: {provider}")
            if units:
                snippet_parts.append(f"יח\"ד: {units}")
            if status:
                snippet_parts.append(f"סטטוס: {status}")
            snippet = " | ".join(snippet_parts) if snippet_parts else "שיווק קרקעות"

            url = f"https://dira.moch.gov.il/Lottery/{lottery_id}" if lottery_id else "https://land.gov.il"

            published = self._try_parse_date(lottery_date)

            return RawArticle(
                url=url,
                title=title,
                snippet=snippet[:500],
                source=self.source_name,
                published_date=published,
                metadata={
                    k: str(v)
                    for k, v in {
                        "lottery_id": lottery_id,
                        "city": city,
                        "provider": provider,
                        "marketing_method": marketing_method,
                        "type": "ila_lottery",
                    }.items()
                    if v
                },
            )
        except Exception:
            return None

    @staticmethod
    def _try_parse_date(date_str: str | None) -> datetime | None:
        if not date_str:
            return None
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d",
            "%d/%m/%Y",
        ):
            try:
                return datetime.strptime(str(date_str).strip(), fmt)
            except (ValueError, TypeError):
                continue
        return None
