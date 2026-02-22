"""
Collector for government housing lottery data (Dira BeHanaha / מחיר למשתכן).

Data source: data.gov.il open data portal (CKAN Datastore API).
Resource: "Tracking Discounted Housing Lottery Draws" — updated weekly.

The original dira.moch.gov.il site is an Angular SPA with reCAPTCHA-protected
API endpoints that cannot be scraped reliably. The data.gov.il CKAN API
provides the same lottery data in clean JSON without authentication.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import httpx

from src.collectors.base import BaseCollector, RawArticle
from src.config import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# data.gov.il CKAN Datastore API
# ---------------------------------------------------------------------------

_CKAN_BASE = "https://data.gov.il/api/3/action/datastore_search"

# "Tracking Discounted Housing Lottery Draws" dataset
_LOTTERY_RESOURCE_ID = "7c8255d0-49ef-49db-8904-4cf917586031"

# How many records to fetch per request
_PAGE_SIZE = 100

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class DiraGovCollector(BaseCollector):
    """Collects housing lottery data from data.gov.il open data portal."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def source_name(self) -> str:
        return "dira_gov"

    async def collect(self) -> list[RawArticle]:
        """Fetch the latest housing lottery records from data.gov.il."""
        try:
            return await self._fetch_lotteries()
        except Exception:
            logger.exception("DiraGovCollector failed to collect data")
            return []

    async def _fetch_lotteries(self) -> list[RawArticle]:
        """Query the CKAN Datastore API for recent lotteries."""
        async with httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        ) as client:
            resp = await client.get(
                _CKAN_BASE,
                params={
                    "resource_id": _LOTTERY_RESOURCE_ID,
                    "limit": _PAGE_SIZE,
                    "sort": "LotteryExecutionDate desc",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        if not data.get("success"):
            logger.warning("CKAN API returned success=false")
            return []

        records = data.get("result", {}).get("records", [])
        logger.info("DiraGovCollector fetched %d lottery records", len(records))

        articles: list[RawArticle] = []
        for record in records:
            article = self._record_to_article(record)
            if article:
                articles.append(article)

        return articles

    def _record_to_article(self, record: dict) -> RawArticle | None:
        """Convert a CKAN lottery record to a RawArticle."""
        try:
            lottery_id = record.get("LotteryId", "")
            project_name = record.get("ProjectName", "")
            city = record.get("LamasName", "")
            neighborhood = record.get("Neighborhood", "")
            provider = record.get("ProviderName", "")
            units = record.get("LotteryHousingUnits", "")
            price_per_meter = record.get("PriceForMeter", "")
            status = record.get("LotteryStatusValue", "")
            marketing_method = record.get("MarketingMethodDesc", "")
            lottery_date = record.get("LotteryExecutionDate", "")
            signup_end = record.get("LotteryEndSignupDate", "")
            subscribers = record.get("Subscribers", "")
            winners = record.get("Winners", "")

            # Build title
            title_parts = [p for p in [project_name, city] if p]
            title = " - ".join(title_parts) if title_parts else f"Lottery {lottery_id}"

            # Build snippet
            snippet_parts = []
            if marketing_method:
                snippet_parts.append(f"תוכנית: {marketing_method}")
            if provider:
                snippet_parts.append(f"יזם: {provider}")
            if neighborhood:
                snippet_parts.append(f"שכונה: {neighborhood}")
            if units:
                snippet_parts.append(f"יח\"ד: {units}")
            if price_per_meter:
                snippet_parts.append(f"מחיר למ\"ר: ₪{price_per_meter:,}" if isinstance(price_per_meter, (int, float)) else f"מחיר למ\"ר: {price_per_meter}")
            if status:
                snippet_parts.append(f"סטטוס: {status}")
            if subscribers:
                snippet_parts.append(f"נרשמו: {subscribers}")
            if winners:
                snippet_parts.append(f"זוכים: {winners}")
            snippet = " | ".join(snippet_parts) if snippet_parts else "הגרלת דירות"

            url = f"https://dira.moch.gov.il/Lottery/{lottery_id}" if lottery_id else "https://dira.moch.gov.il"

            # Parse date
            published = self._try_parse_date(lottery_date) or self._try_parse_date(signup_end)

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
                        "neighborhood": neighborhood,
                        "provider": provider,
                        "units": units,
                        "price_per_meter": price_per_meter,
                        "status": status,
                        "marketing_method": marketing_method,
                        "signup_end": signup_end,
                        "subscribers": subscribers,
                        "winners": winners,
                        "type": "lottery",
                    }.items()
                    if v
                },
            )
        except Exception:
            logger.debug("Skipping unparseable lottery record: %s", record)
            return None

    @staticmethod
    def _try_parse_date(date_str: str | None) -> datetime | None:
        """Attempt to parse a date string from the CKAN dataset."""
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
                return datetime.strptime(str(date_str).strip(), fmt)
            except (ValueError, TypeError):
                continue
        return None
