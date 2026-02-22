"""
Collector for public Telegram channels with government housing updates.

Uses Telethon to connect as a user account and fetch recent messages
from a curated list of public channels. Filters messages by government
housing program keywords before returning them as RawArticle objects.

First-time setup (interactive, run once locally):
    python -m src.collectors.telegram_channels --login
"""

from __future__ import annotations

import hashlib
import logging
import sys
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    FloodWaitError,
    SessionPasswordNeededError,
)
from telethon.tl.types import Message

from src.collectors.base import BaseCollector, RawArticle
from src.config import (
    TELEGRAM_CHANNELS,
    TELEGRAM_GOV_KEYWORDS,
    Settings,
)

logger = logging.getLogger(__name__)

_MIN_MESSAGE_LENGTH = 20
_MAX_MESSAGES_PER_CHANNEL = 200
_LOOKBACK_HOURS = 26  # slightly more than 24h to avoid timezone edge cases


class TelegramChannelCollector(BaseCollector):
    """Collects government housing updates from public Telegram channels."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: TelegramClient | None = None

    @property
    def source_name(self) -> str:
        return "telegram"

    async def collect(self) -> list[RawArticle]:
        """Fetch recent messages from configured Telegram channels."""
        if not self._settings.telegram_api_id or not self._settings.telegram_api_hash:
            logger.warning(
                "TelegramChannelCollector: TELEGRAM_API_ID/HASH not set, skipping"
            )
            return []

        articles: list[RawArticle] = []
        seen_hashes: set[str] = set()

        try:
            client = TelegramClient(
                self._settings.telegram_session_path,
                int(self._settings.telegram_api_id),
                self._settings.telegram_api_hash,
            )
            await client.connect()

            if not await client.is_user_authorized():
                logger.error(
                    "Telegram session not authorized. Run: "
                    "python -m src.collectors.telegram_channels --login"
                )
                await client.disconnect()
                return []

            cutoff = datetime.now(timezone.utc) - timedelta(hours=_LOOKBACK_HOURS)

            for channel_username in TELEGRAM_CHANNELS:
                try:
                    channel_articles = await self._fetch_channel(
                        client, channel_username, cutoff, seen_hashes
                    )
                    articles.extend(channel_articles)
                    logger.info(
                        "Channel @%s: %d relevant messages",
                        channel_username,
                        len(channel_articles),
                    )
                except (ChannelInvalidError, ChannelPrivateError, ValueError):
                    logger.warning(
                        "Channel @%s not found or not accessible, skipping",
                        channel_username,
                    )
                except FloodWaitError as e:
                    logger.warning(
                        "Telegram rate limit, waiting %ds", e.seconds
                    )
                    import asyncio
                    await asyncio.sleep(e.seconds)
                except Exception:
                    logger.exception(
                        "Failed to fetch channel @%s", channel_username
                    )

            await client.disconnect()

        except Exception:
            logger.exception("TelegramChannelCollector failed")

        logger.info(
            "TelegramChannelCollector finished: %d articles", len(articles)
        )
        return articles

    async def _fetch_channel(
        self,
        client: TelegramClient,
        channel_username: str,
        cutoff: datetime,
        seen_hashes: set[str],
    ) -> list[RawArticle]:
        """Fetch and filter messages from a single channel."""
        articles: list[RawArticle] = []

        async for message in client.iter_messages(
            channel_username,
            limit=_MAX_MESSAGES_PER_CHANNEL,
            offset_date=None,
        ):
            if not isinstance(message, Message):
                continue

            # Stop if we've gone past the lookback window
            if message.date < cutoff:
                break

            text = message.text or ""
            if len(text) < _MIN_MESSAGE_LENGTH:
                continue

            # Filter: must contain at least one government program keyword
            if not self._has_gov_keyword(text):
                continue

            # Deduplicate by text hash (same message forwarded across channels)
            text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
            if text_hash in seen_hashes:
                continue
            seen_hashes.add(text_hash)

            articles.append(
                RawArticle(
                    url=f"https://t.me/{channel_username}/{message.id}",
                    title=text[:150].replace("\n", " "),
                    snippet=text[:500],
                    source=self.source_name,
                    published_date=message.date,
                    metadata={
                        "channel": channel_username,
                        "message_id": str(message.id),
                    },
                )
            )

        return articles

    @staticmethod
    def _has_gov_keyword(text: str) -> bool:
        """Check if text contains any government program keyword."""
        text_lower = text.lower()
        return any(kw in text_lower for kw in TELEGRAM_GOV_KEYWORDS)


# ---------------------------------------------------------------------------
# CLI: one-time interactive login
# ---------------------------------------------------------------------------

async def _interactive_login() -> None:
    """Run interactive Telegram login to create a session file."""
    import os
    os.environ.setdefault("ANTHROPIC_API_KEY", "not-needed")
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "not-needed")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "not-needed")

    settings = Settings()

    if not settings.telegram_api_id or not settings.telegram_api_hash:
        print("Error: Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first.")
        sys.exit(1)

    client = TelegramClient(
        settings.telegram_session_path,
        int(settings.telegram_api_id),
        settings.telegram_api_hash,
    )

    await client.start()
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} (phone: {me.phone})")
    print(f"Session saved to: {settings.telegram_session_path}.session")
    await client.disconnect()


if __name__ == "__main__":
    import asyncio

    if "--login" in sys.argv:
        asyncio.run(_interactive_login())
    else:
        print("Usage: python -m src.collectors.telegram_channels --login")
        print("  Runs interactive Telegram login to create session file.")
