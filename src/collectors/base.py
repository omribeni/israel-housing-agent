from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawArticle:
    """A single article/item collected from any news or government source."""

    url: str
    title: str
    snippet: str  # first ~500 chars of body or description
    source: str  # e.g. "ynet", "dira.moch.gov.il", "google_news"
    published_date: datetime | None = None
    full_text: str = ""  # full body if available
    metadata: dict = field(default_factory=dict)


class BaseCollector(ABC):
    """Abstract base class that every collector must implement."""

    @abstractmethod
    async def collect(self) -> list[RawArticle]:
        """Fetch and return a list of raw articles from the source."""
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return a short identifier for this collector's source."""
        ...
