"""
Hebrew text utilities for normalization, URL cleaning, and domain extraction.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# Unicode range for Hebrew niqqud (vowel marks / cantillation marks)
# U+0591 .. U+05C7 covers cantillation marks, points, and marks
_NIQQUD_RE = re.compile(r"[\u0591-\u05C7]")

# Whitespace normalization: collapse runs of any whitespace into a single space
_WHITESPACE_RE = re.compile(r"\s+")

# Tracking query parameters to strip from URLs
_TRACKING_PARAMS = frozenset({
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "gclsrc",
    "dclid",
    "msclkid",
    "twclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "yclid",
    "_ga",
    "_gl",
    "ref",
    "source",
})


def normalize_hebrew(text: str) -> str:
    """Strip Hebrew niqqud (vowel / cantillation marks) and normalize whitespace.

    Args:
        text: Raw Hebrew (or mixed) text that may contain niqqud marks.

    Returns:
        Text with all niqqud removed and whitespace collapsed to single spaces.
    """
    text = _NIQQUD_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def clean_url(url: str) -> str:
    """Remove tracking query parameters and normalize a URL.

    Strips common tracking parameters (utm_*, fbclid, gclid, etc.)
    while preserving all other query parameters.

    Args:
        url: The URL to clean.

    Returns:
        Cleaned URL with tracking parameters removed.
    """
    parsed = urlparse(url)

    # Filter out tracking params
    if parsed.query:
        original_params = parse_qs(parsed.query, keep_blank_values=True)
        cleaned_params = {
            key: values
            for key, values in original_params.items()
            if key.lower() not in _TRACKING_PARAMS
        }
        clean_query = urlencode(cleaned_params, doseq=True)
    else:
        clean_query = ""

    # Strip trailing fragment if empty, rebuild URL
    cleaned = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip("/") if parsed.path != "/" else "/",
        parsed.params,
        clean_query,
        "",  # drop fragment
    ))

    return cleaned


def extract_domain(url: str) -> str:
    """Extract the domain (netloc) from a URL.

    Args:
        url: A full URL string.

    Returns:
        The domain portion of the URL (e.g. ``"www.example.com"``).
        Returns an empty string if the URL cannot be parsed.
    """
    parsed = urlparse(url)
    return parsed.netloc or ""
