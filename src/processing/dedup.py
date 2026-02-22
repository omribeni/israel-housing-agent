"""SQLite-based deduplication for collected articles.

Tracks previously seen article URLs so that only genuinely new items
are forwarded to downstream processing stages.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import datetime, timedelta

from src.collectors.base import RawArticle


class Deduplicator:
    """Keeps a persistent SQLite store of already-seen article URLs.

    Each URL is hashed (SHA-256, first 16 hex characters) and stored alongside
    its original URL, title, source, and a timestamp.  The ``filter_new``
    method accepts a batch of :class:`RawArticle` objects and returns only
    those that have not been seen before, inserting the new ones into the
    database in the same transaction.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create the ``seen_articles`` table and index if they do not exist."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_articles (
                    url_hash    TEXT PRIMARY KEY,
                    url         TEXT NOT NULL,
                    title       TEXT,
                    first_seen  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source      TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_seen_articles_first_seen
                ON seen_articles (first_seen)
                """
            )

    @staticmethod
    def _hash_url(url: str) -> str:
        """Return the first 16 hex characters of the SHA-256 digest of *url*."""
        return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def filter_new(self, articles: list[RawArticle]) -> list[RawArticle]:
        """Return only articles whose URLs have not been seen before.

        New articles are inserted into the database within the same
        transaction so that concurrent calls will not produce duplicates.
        """
        new_articles: list[RawArticle] = []

        with sqlite3.connect(self.db_path) as conn:
            for article in articles:
                url_hash = self._hash_url(article.url)

                row = conn.execute(
                    "SELECT 1 FROM seen_articles WHERE url_hash = ?",
                    (url_hash,),
                ).fetchone()

                if row is None:
                    conn.execute(
                        """
                        INSERT INTO seen_articles (url_hash, url, title, source)
                        VALUES (?, ?, ?, ?)
                        """,
                        (url_hash, article.url, article.title, article.source),
                    )
                    new_articles.append(article)

        return new_articles

    def purge_old(self, days: int = 30) -> None:
        """Delete entries older than *days* days from the database."""
        cutoff = datetime.utcnow() - timedelta(days=days)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM seen_articles WHERE first_seen < ?",
                (cutoff.isoformat(),),
            )
