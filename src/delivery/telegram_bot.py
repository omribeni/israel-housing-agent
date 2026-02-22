"""
Telegram delivery module for sending daily housing digest messages.

Formats processed articles into a readable Hebrew digest and sends
them to a configured Telegram chat via the Bot API.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.config import ProgramType, Settings

logger = logging.getLogger(__name__)

# Importance ordering for sorting (lower = higher priority)
_IMPORTANCE_ORDER = {"high": 0, "medium": 1, "low": 2}

# Emoji mapping by program type
_PROGRAM_EMOJI: dict[str, str] = {
    ProgramType.mechir_lamishtaken.value: "\U0001f3db\ufe0f",   # 🏛️
    ProgramType.mechir_mufchat.value: "\U0001f3db\ufe0f",       # 🏛️
    ProgramType.other_gov_program.value: "\U0001f3db\ufe0f",    # 🏛️
    ProgramType.dira_behagralah.value: "\U0001f3b2",             # 🎲
    ProgramType.private_deal.value: "\U0001f3d7\ufe0f",         # 🏗️
    ProgramType.general_news.value: "\U0001f4f0",               # 📰
}


class TelegramDelivery:
    """Sends formatted housing digests to a Telegram chat."""

    def __init__(self, settings: Settings) -> None:
        self._token = settings.telegram_bot_token
        self._chat_id = settings.telegram_chat_id
        self._api_url = f"https://api.telegram.org/bot{self._token}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_digest(self, articles: list[Any], date_str: str) -> None:
        """Build and send the daily digest to Telegram.

        Args:
            articles: List of processed article objects (with attributes such
                      as ``raw``, ``program_type``, ``cities``, ``summary_he``,
                      ``importance``, and ``area``).
            date_str: Human-readable date string for the header.
        """
        if not articles:
            no_news = (
                f"\U0001f4cb *\u05e1\u05d9\u05db\u05d5\u05dd \u05d9\u05d5\u05de\u05d9"
                f" - {date_str}*\n\n"
                f"\u05dc\u05d0 \u05e0\u05de\u05e6\u05d0\u05d5 \u05d7\u05d3\u05e9\u05d5\u05ea"
                f" \u05e8\u05dc\u05d5\u05d5\u05e0\u05d8\u05d9\u05d5\u05ea \u05d4\u05d9\u05d5\u05dd."
            )
            await self._send_message(no_news)
            return

        # Sort: high importance first, then medium, then low; within same
        # importance level sort alphabetically by area name.
        sorted_articles = sorted(
            articles,
            key=lambda a: (
                _IMPORTANCE_ORDER.get(a.importance, 99),
                getattr(a, "area", "") or "",
            ),
        )

        count = len(sorted_articles)
        header = (
            f"\U0001f3e0 *\u05e1\u05d9\u05db\u05d5\u05dd \u05d7\u05d3\u05e9\u05d5\u05ea"
            f" \u05d3\u05d9\u05d5\u05e8 \u05d9\u05d5\u05de\u05d9"
            f" - {date_str}*\n"
            f"\u05e0\u05de\u05e6\u05d0\u05d5 {count}"
            f" \u05e2\u05d3\u05db\u05d5\u05e0\u05d9\u05dd"
            f" \u05e8\u05dc\u05d5\u05d5\u05e0\u05d8\u05d9\u05dd\n\n"
        )

        sections = self._build_sections(sorted_articles)
        messages = self._split_to_messages(header, sections)

        for message in messages:
            await self._send_message(message)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_sections(self, articles: list[Any]) -> list[str]:
        """Return a list of formatted Markdown section strings."""
        sections: list[str] = []
        for article in articles:
            program_value = (
                article.program_type.value
                if hasattr(article.program_type, "value")
                else str(article.program_type)
            )
            emoji = _PROGRAM_EMOJI.get(program_value, "\U0001f4f0")

            importance_marker = ""
            if getattr(article, "importance", None) == "high":
                importance_marker = "\U0001f534 "  # 🔴

            title = article.raw.title
            cities = ", ".join(article.cities) if article.cities else ""
            summary = article.summary_he or ""
            url = article.raw.url

            lines: list[str] = []
            lines.append(f"{emoji} {importance_marker}*{title}*")
            if cities:
                lines.append(f"\U0001f4cd {cities}")
            if summary:
                lines.append(summary)
            if url:
                lines.append(f"[\u05e7\u05e8\u05d0 \u05e2\u05d5\u05d3]({url})")
            lines.append("")  # trailing blank line separator

            sections.append("\n".join(lines))

        return sections

    def _split_to_messages(
        self,
        header: str,
        sections: list[str],
        max_len: int = 4000,
    ) -> list[str]:
        """Split header + sections into messages that fit within *max_len*.

        Telegram enforces a 4096 character limit per message; we default to
        4000 to leave a small safety margin.
        """
        messages: list[str] = []
        current = header

        for section in sections:
            # If adding this section would exceed the limit, flush current
            # message and start a new one.
            if len(current) + len(section) > max_len and current.strip():
                messages.append(current.rstrip())
                current = ""

            # If a single section itself exceeds max_len we still include it
            # as its own message rather than silently dropping it.
            current += section

        if current.strip():
            messages.append(current.rstrip())

        return messages

    async def _send_message(self, text: str) -> None:
        """Send a single message via the Telegram Bot API.

        Errors are logged but intentionally not re-raised so that a delivery
        failure does not crash the rest of the pipeline.
        """
        url = f"{self._api_url}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Telegram API returned %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
        except httpx.RequestError as exc:
            logger.error("Failed to send Telegram message: %s", exc)
