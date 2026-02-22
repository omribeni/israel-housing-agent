"""
Shared async HTTP client utility for fetching web pages.

Uses httpx for async HTTP requests and tenacity for retry logic
with exponential backoff.
"""

from __future__ import annotations

import logging

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import Settings

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
    reraise=True,
)
async def fetch_page(url: str, settings: Settings) -> str:
    """Fetch a web page and return its content as a UTF-8 string.

    Args:
        url: The URL to fetch.
        settings: Application settings providing timeout, user-agent,
                  and retry configuration.

    Returns:
        The response body decoded as UTF-8.

    Raises:
        httpx.HTTPStatusError: If the response has a non-2xx status code
            after all retry attempts are exhausted.
        httpx.TransportError: If a network-level error persists after
            all retry attempts are exhausted.
    """
    logger.debug("Fetching URL: %s", url)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout),
        follow_redirects=True,
        headers={"User-Agent": settings.user_agent},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()

        # Ensure correct UTF-8 decoding for Hebrew content
        response.encoding = "utf-8"
        return response.text
