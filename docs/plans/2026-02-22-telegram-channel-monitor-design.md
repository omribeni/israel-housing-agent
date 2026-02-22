# Telegram Channel Monitor — Design

## Purpose

Add a collector that monitors public Hebrew Telegram channels for government housing program announcements. Provides early signals about lotteries, new projects, and program updates that surface in community channels before they hit mainstream news.

## Architecture

New file: `src/collectors/telegram_channels.py` implementing `BaseCollector`.

Uses Telethon (Python Telegram client library) to connect as a user account, fetch messages from the last 24 hours across a curated list of public channels, and filter for government program keywords.

Fits the existing collector pattern — runs once at pipeline time, returns `list[RawArticle]`, no persistent process needed.

## Authentication

- Telethon user account session via `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` env vars.
- First-time login is interactive (one-time code sent to phone): `python -m src.collectors.telegram_channels --login`
- Creates `data/telegram.session` file that persists and auto-renews.
- On Railway, session file lives on the persistent volume at `/app/data/`.

## Channel List

Configurable list of channel usernames in `config.py` (`TELEGRAM_CHANNELS`). Seeded with public Hebrew channels focused on government housing programs. Easy to add/remove channels.

## Message Processing Flow

```
Channel messages (last 24h)
    |
    v
Keyword filter (government program keywords only):
    מחיר למשתכן, דירה בהגרלה, מחיר מופחת, מחיר מטרה,
    דירה בהנחה, דיור בר השגה, הגרלת דירות,
    רשות מקרקעי ישראל, משרד הבינוי והשיכון
    |
    v
Skip: no text, < 20 chars, no keyword match
    |
    v
Deduplicate by text hash (same message forwarded across channels)
    |
    v
Convert to RawArticle:
    title  = first 150 chars of message text
    snippet = first 500 chars
    url    = https://t.me/{channel}/{message_id}
    source = "telegram"
    metadata = {channel, message_id, forward_from}
    |
    v
Into normal pipeline -> dedup -> Claude filter -> Telegram digest
```

## Error Handling

- Session expired/revoked: log error, skip collector, pipeline continues.
- Channel not found or not joined: skip channel, log warning, continue with others.
- Telegram rate limits (`FloodWaitError`): Telethon handles natively (sleeps and retries).
- Network timeouts: retry via tenacity, same as other collectors.

## Changes to Existing Code

- `src/collectors/telegram_channels.py` — new collector
- `src/config.py` — add `TELEGRAM_CHANNELS` list, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` to Settings
- `src/main.py` — add optional import for `TelegramChannelCollector`
- `pyproject.toml` — add `telethon>=1.36`
- `.env.example` — add `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`

## Cost

Zero. Telegram API is free with no usage fees. The only marginal cost is slightly more tokens sent to Claude for filtering, estimated at a fraction of a cent per day.

## First-Time Setup

1. Get API ID and hash from my.telegram.org (done).
2. Add to `.env`: `TELEGRAM_API_ID=31539165`, `TELEGRAM_API_HASH=369817f2ab397b84a3d9cccc6d203317`.
3. Run `python -m src.collectors.telegram_channels --login` — enter phone number and verification code.
4. Session file created at `data/telegram.session`.
5. For Railway: upload session file to the persistent volume.
