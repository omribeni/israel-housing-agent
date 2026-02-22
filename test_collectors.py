"""
Dry-run test: run all collectors and print what they find.
No API keys required — this only tests the scraping/collection layer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

# Stub out required env vars so Settings doesn't crash
os.environ.setdefault("ANTHROPIC_API_KEY", "test-not-used")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-not-used")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-not-used")

from src.collectors.base import BaseCollector, RawArticle
from src.collectors.google_news import GoogleNewsCollector
from src.collectors.gov_dira import DiraGovCollector
from src.collectors.gov_land import LandGovCollector
from src.collectors.news_calcalist import CalcalistCollector
from src.collectors.news_globes import GlobesCollector
from src.collectors.news_themarker import TheMarkerCollector
from src.collectors.news_ynet import YnetCollector
from src.collectors.telegram_channels import TelegramChannelCollector
from src.config import Settings


def print_articles(name: str, articles: list[RawArticle]) -> None:
    print(f"\n{'='*60}")
    print(f"  {name}: {len(articles)} articles")
    print(f"{'='*60}")
    for i, a in enumerate(articles[:5], 1):  # Show first 5
        title = a.title[:80] if a.title else "(no title)"
        print(f"  [{i}] {title}")
        print(f"      URL: {a.url[:100]}")
        if a.snippet:
            print(f"      Snippet: {a.snippet[:120]}...")
        if a.published_date:
            print(f"      Date: {a.published_date}")
        print()
    if len(articles) > 5:
        print(f"  ... and {len(articles) - 5} more\n")


async def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    settings = Settings()

    collectors: list[tuple[str, BaseCollector]] = [
        ("Google News", GoogleNewsCollector(settings)),
        ("Ynet", YnetCollector(settings)),
        ("Calcalist", CalcalistCollector(settings)),
        ("Globes", GlobesCollector(settings)),
        ("TheMarker", TheMarkerCollector(settings)),
        ("Dira Gov", DiraGovCollector(settings)),
        ("Land Gov", LandGovCollector(settings)),
        ("Telegram Channels", TelegramChannelCollector(settings)),
    ]

    print("Running all 8 collectors (scraping only, no API keys needed)...\n")

    total = 0
    for name, collector in collectors:
        try:
            articles = await collector.collect()
            print_articles(name, articles)
            total += len(articles)
        except Exception as e:
            print(f"\n  {name}: FAILED — {e}\n")

    print(f"\n{'='*60}")
    print(f"  TOTAL: {total} articles collected across all sources")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
