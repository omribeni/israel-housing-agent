# Telegram Channel Monitor — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Telethon-based collector that monitors public Hebrew Telegram channels for government housing program announcements and feeds them into the existing pipeline.

**Architecture:** New `TelegramChannelCollector` implementing `BaseCollector`. Connects as a Telegram user account via Telethon, fetches last 24h of messages from configured channels, filters by government program keywords, returns `list[RawArticle]`. Includes a `--login` CLI entrypoint for one-time interactive authentication.

**Tech Stack:** Telethon (Telegram MTProto client), existing BaseCollector pattern, config.py for channel list and keywords.

---

### Task 1: Add Telethon dependency

**Files:**
- Modify: `pyproject.toml:7-15`

**Step 1: Add telethon to dependencies**

In `pyproject.toml`, add `"telethon>=1.36"` to the `dependencies` list:

```toml
dependencies = [
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "feedparser>=6.0",
    "anthropic>=0.40",
    "tenacity>=9.0",
    "python-dotenv>=1.0",
    "telethon>=1.36",
]
```

**Step 2: Install**

Run: `pip install -e ".[dev]"`
Expected: telethon installs successfully

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add telethon dependency for Telegram channel monitoring"
```

---

### Task 2: Add Telegram config to Settings and channel list

**Files:**
- Modify: `src/config.py:111-136` (add keyword subset), `src/config.py:160-216` (add Settings fields)
- Modify: `.env.example`

**Step 1: Add government program keyword subset and channel list to config.py**

After `GOOGLE_NEWS_QUERIES` (line 153), add:

```python
# ---------------------------------------------------------------------------
# Telegram channel monitoring
# ---------------------------------------------------------------------------

# Government program keywords for filtering Telegram messages.
# Subset of SEARCH_KEYWORDS_HE focused on gov programs only.
TELEGRAM_GOV_KEYWORDS: list[str] = [
    "מחיר למשתכן",
    "מחיר מופחת",
    "דירה בהנחה",
    "דירה בהגרלה",
    "מחיר מטרה",
    "דיור בר השגה",
    "הגרלת דירות",
    "רשות מקרקעי ישראל",
    "משרד הבינוי והשיכון",
    "מכרז דירות",
    "שיווק קרקעות",
]

# Public Telegram channels to monitor for housing program updates.
# Add/remove channels as needed — use the username without the @ prefix.
TELEGRAM_CHANNELS: list[str] = [
    "dira_behanaha",
    "mechir_lamishtaken",
    "nadlan_israel",
    "dira_gov_il",
    "realestate_il",
]
```

**Step 2: Add Telegram API settings to Settings dataclass**

Add these fields to the `Settings` class (after `dedup_days`):

```python
    # Telegram channel monitoring (optional — collector skipped if not set)
    telegram_api_id: str = field(
        default_factory=lambda: os.environ.get("TELEGRAM_API_ID", "")
    )
    telegram_api_hash: str = field(
        default_factory=lambda: os.environ.get("TELEGRAM_API_HASH", "")
    )
    telegram_session_path: str = field(
        default_factory=lambda: os.environ.get(
            "TELEGRAM_SESSION_PATH", "data/telegram"
        )
    )
```

**Step 3: Update .env.example**

Add to `.env.example`:

```
# Telegram Channel Monitoring — get from https://my.telegram.org/apps
# Optional: if not set, the Telegram channel collector is skipped
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
```

**Step 4: Commit**

```bash
git add src/config.py .env.example
git commit -m "feat: add Telegram channel monitoring config and env vars"
```

---

### Task 3: Implement TelegramChannelCollector

**Files:**
- Create: `src/collectors/telegram_channels.py`

**Step 1: Write the collector**

```python
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
```

**Step 2: Verify imports work**

Run: `python -c "from src.collectors.telegram_channels import TelegramChannelCollector; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/collectors/telegram_channels.py
git commit -m "feat: implement TelegramChannelCollector with Telethon"
```

---

### Task 4: Wire collector into the pipeline

**Files:**
- Modify: `src/main.py:58-62`

**Step 1: Add optional import for TelegramChannelCollector**

After the `LandGovCollector` import block (line 62), add:

```python
try:
    from src.collectors.telegram_channels import TelegramChannelCollector
    _OPTIONAL_COLLECTORS.append(TelegramChannelCollector)
except ImportError:
    pass
```

**Step 2: Verify pipeline imports cleanly**

Run: `python -c "from src.main import run_pipeline; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: wire TelegramChannelCollector into pipeline"
```

---

### Task 5: Update test script and CLAUDE.md

**Files:**
- Modify: `test_collectors.py`
- Modify: `CLAUDE.md`

**Step 1: Add Telegram collector to test script**

Add import (after other collector imports):

```python
from src.collectors.telegram_channels import TelegramChannelCollector
```

Add to the collectors list:

```python
("Telegram Channels", TelegramChannelCollector(settings)),
```

Update the print line to say "8 collectors" instead of "7".

**Step 2: Update CLAUDE.md**

Add a section about the Telegram channel collector under "Data Source Gotchas":

```markdown
### Telegram Channels
- Uses Telethon with a user account session (not a bot). Requires `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in env vars.
- Session file at `data/telegram.session` — created once via `python -m src.collectors.telegram_channels --login`. Must be present on Railway's persistent volume.
- If session expires, the collector logs an error and returns empty — other collectors still run.
- Channel list is in `config.py` (`TELEGRAM_CHANNELS`). Add/remove channel usernames without the `@` prefix.
- Only collects messages containing government program keywords (subset of `SEARCH_KEYWORDS_HE`).
```

**Step 3: Commit**

```bash
git add test_collectors.py CLAUDE.md
git commit -m "docs: update test script and CLAUDE.md for Telegram collector"
```

---

### Task 6: First-time login and integration test

**Step 1: Add API credentials to .env**

Add to `.env` (local only, never committed):

```
TELEGRAM_API_ID=31539165
TELEGRAM_API_HASH=369817f2ab397b84a3d9cccc6d203317
```

**Step 2: Run interactive login**

Run: `python -m src.collectors.telegram_channels --login`
Expected: Prompts for phone number, then verification code. Prints "Logged in as: ..." and creates `data/telegram.session`.

**Step 3: Run the dry test**

Run: `python test_collectors.py`
Expected: Telegram Channels collector runs (may return 0 articles if channels don't exist yet — that's OK, the important thing is no crashes).

**Step 4: Final commit and push**

```bash
git push
```
