"""Start over option B: keep starred/noted papers; drop the rest."""

from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)


def keep_starred_and_noted(self) -> Dict:
    """Start over (option B): drop unmarked papers; keep starred/noted.

    Keeps any article that is starred or has a non-empty (trimmed) note.
    Child rows cascade via FK for deleted articles. Staging is dropped.
    Idempotent when only annotated papers remain.

    Returns:
        dict with deleted, remaining, kept counts.
    """
    with self._lock:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM articles")
        before = int(cursor.fetchone()[0] or 0)
        # Keys to keep: starred OR non-whitespace note
        cursor.execute(
            """
            SELECT article_id, source FROM notes
            WHERE starred = 1 OR TRIM(COALESCE(note, '')) != ''
            """
        )
        keep = {(r[0], r[1]) for r in cursor.fetchall()}
        if not keep:
            # Nothing annotated — clear everything (same as clear_all path)
            cursor.execute("DELETE FROM key_points")
            cursor.execute("DELETE FROM notes")
            cursor.execute("DELETE FROM screening")
            cursor.execute("DELETE FROM clusters")
            cursor.execute("DELETE FROM embeddings")
            cursor.execute("DELETE FROM articles")
            cursor.execute(f"DROP TABLE IF EXISTS {self.STAGING_TABLE}")
            self.conn.commit()
            return {"deleted": before, "remaining": 0, "kept": 0}

        # Delete articles not in keep set; FKs cascade children
        cursor.execute("SELECT article_id, source FROM articles")
        all_keys = [(r[0], r[1]) for r in cursor.fetchall()]
        drop = [k for k in all_keys if k not in keep]
        if drop:
            cursor.executemany(
                "DELETE FROM articles WHERE article_id = ? AND source = ?",
                drop,
            )
        # Clean whitespace-only unstarred notes that should not linger.
        cursor.execute(
            """
            DELETE FROM notes
            WHERE starred = 0 AND TRIM(COALESCE(note, '')) = ''
            """
        )
        cursor.execute(f"DROP TABLE IF EXISTS {self.STAGING_TABLE}")
        self.conn.commit()
        cursor.execute("SELECT COUNT(*) FROM articles")
        remaining = int(cursor.fetchone()[0] or 0)
        deleted = max(0, before - remaining)
        logger.info(
            "keep_starred_and_noted: deleted=%d remaining=%d kept=%d",
            deleted, remaining, len(keep),
        )
        return {
            "deleted": deleted,
            "remaining": remaining,
            "kept": len(keep),
        }


def install() -> None:
    """Attach keep_starred_and_noted onto ArticleDatabase if missing."""
    from app.storage.database import ArticleDatabase
    if not getattr(ArticleDatabase, "keep_starred_and_noted", None):
        ArticleDatabase.keep_starred_and_noted = keep_starred_and_noted  # type: ignore[attr-defined]
