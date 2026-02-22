"""
Pipeline orchestrator for the Israel Housing Agent.

Runs the full daily pipeline: collect articles from all sources,
deduplicate, filter/classify with Claude, and deliver via Telegram.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime

from src.collectors.base import BaseCollector, RawArticle
from src.collectors.google_news import GoogleNewsCollector
from src.config import Settings
from src.delivery.telegram_bot import TelegramDelivery
from src.processing.claude_filter import ClaudeFilter
from src.processing.dedup import Deduplicator

# ---------------------------------------------------------------------------
# Optional collectors — import each one but gracefully skip if not yet written
# ---------------------------------------------------------------------------

_OPTIONAL_COLLECTORS: list[type[BaseCollector]] = []

try:
    from src.collectors.news_ynet import YnetCollector
    _OPTIONAL_COLLECTORS.append(YnetCollector)
except ImportError:
    pass

try:
    from src.collectors.news_calcalist import CalcalistCollector
    _OPTIONAL_COLLECTORS.append(CalcalistCollector)
except ImportError:
    pass

try:
    from src.collectors.news_globes import GlobesCollector
    _OPTIONAL_COLLECTORS.append(GlobesCollector)
except ImportError:
    pass

try:
    from src.collectors.news_themarker import TheMarkerCollector
    _OPTIONAL_COLLECTORS.append(TheMarkerCollector)
except ImportError:
    pass

try:
    from src.collectors.gov_dira import DiraGovCollector
    _OPTIONAL_COLLECTORS.append(DiraGovCollector)
except ImportError:
    pass

try:
    from src.collectors.gov_land import LandGovCollector
    _OPTIONAL_COLLECTORS.append(LandGovCollector)
except ImportError:
    pass

try:
    from src.collectors.telegram_channels import TelegramChannelCollector
    _OPTIONAL_COLLECTORS.append(TelegramChannelCollector)
except ImportError:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


async def run_pipeline() -> None:
    """Execute the full collection-to-delivery pipeline."""

    settings = Settings()

    dedup = Deduplicator(db_path=settings.db_path)
    claude = ClaudeFilter(settings)
    telegram = TelegramDelivery(settings)

    # Build the list of all collectors
    collectors: list[BaseCollector] = [GoogleNewsCollector(settings)]
    for collector_cls in _OPTIONAL_COLLECTORS:
        try:
            collectors.append(collector_cls(settings))
        except Exception:
            logger.warning(
                "Failed to instantiate collector %s — skipping",
                collector_cls.__name__,
            )

    logger.info("Starting pipeline with %d collector(s)", len(collectors))

    # ------------------------------------------------------------------
    # Phase 1 — COLLECT
    # ------------------------------------------------------------------
    logger.info("Phase 1: COLLECT — running %d collectors concurrently", len(collectors))

    results = await asyncio.gather(
        *(collector.collect() for collector in collectors),
        return_exceptions=True,
    )

    all_raw: list[RawArticle] = []
    for collector, result in zip(collectors, results):
        if isinstance(result, Exception):
            logger.error(
                "Collector %s failed: %s", collector.source_name, result
            )
            continue
        all_raw.extend(result)
        logger.info(
            "Collector %s returned %d articles",
            collector.source_name,
            len(result),
        )

    logger.info("Total raw articles collected: %d", len(all_raw))

    # ------------------------------------------------------------------
    # Phase 2 — DEDUP
    # ------------------------------------------------------------------
    logger.info("Phase 2: DEDUP — filtering previously seen articles")

    new_articles = dedup.filter_new(all_raw)
    logger.info(
        "Dedup: %d raw -> %d new articles", len(all_raw), len(new_articles)
    )

    # ------------------------------------------------------------------
    # Early exit if nothing new
    # ------------------------------------------------------------------
    if not new_articles:
        logger.info("No new articles — sending empty digest")
        date_str = datetime.now().strftime("%d/%m/%Y")
        await telegram.send_digest([], date_str)
        return

    # ------------------------------------------------------------------
    # Phase 3 — FILTER
    # ------------------------------------------------------------------
    logger.info("Phase 3: FILTER — classifying %d articles with Claude", len(new_articles))

    processed = claude.filter_and_classify(new_articles)
    logger.info("Claude filter: %d relevant articles after classification", len(processed))

    # ------------------------------------------------------------------
    # Phase 4 — DELIVER
    # ------------------------------------------------------------------
    date_str = datetime.now().strftime("%d/%m/%Y")
    logger.info("Phase 4: DELIVER — sending digest for %s", date_str)

    await telegram.send_digest(processed, date_str)

    # ------------------------------------------------------------------
    # Phase 5 — CLEANUP
    # ------------------------------------------------------------------
    logger.info("Phase 5: CLEANUP — purging old dedup entries")
    dedup.purge_old()

    logger.info("Pipeline completed successfully")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Set up logging and run the async pipeline."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    asyncio.run(run_pipeline())


if __name__ == "__main__":
    main()
