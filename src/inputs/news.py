"""RSS news feed ingestion — fetch, dedup by URL, store in news_items table."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import feedparser
import structlog

from src.brain.db import get_connection
from src.config import config, settings
from src.schemas import NewsItem

log = structlog.get_logger()


def _url_to_uuid(url: str) -> UUID:
    """Deterministic UUID from URL so dedup is idempotent across runs."""
    import hashlib

    return UUID(hashlib.md5(url.encode()).hexdigest())  # noqa: S324


def _parse_feed(feed_name: str, feed_url: str) -> list[NewsItem]:
    parsed = feedparser.parse(feed_url)
    items: list[NewsItem] = []
    for entry in parsed.entries:
        url: str = entry.get("link", "").strip()
        if not url:
            continue
        title: str = entry.get("title", "").strip()
        raw_summary: str = entry.get("summary", "") or entry.get("description", "")
        summary = raw_summary[:500].strip()
        items.append(
            NewsItem(
                id=_url_to_uuid(url),
                fetched_at=datetime.now(tz=UTC),
                source=feed_name,
                url=url,
                title=title,
                summary=summary,
            )
        )
    return items


def fetch_all_feeds() -> list[NewsItem]:
    """Fetch every RSS feed in config.yaml and return parsed NewsItems."""
    feeds: list[dict[str, str]] = config["news_feeds"]
    all_items: list[NewsItem] = []
    for feed in feeds:
        try:
            items = _parse_feed(feed["name"], feed["url"])
            log.info("feed_fetched", source=feed["name"], count=len(items))
            all_items.extend(items)
        except Exception as exc:
            log.warning("feed_fetch_failed", source=feed["name"], error=str(exc))
    return all_items


def store_news_items(db_path: Path, items: list[NewsItem]) -> int:
    """Insert new items (skip duplicates by URL). Returns count of newly stored rows."""
    new_count = 0
    with get_connection(db_path) as conn:
        for item in items:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO news_items
                    (id, fetched_at, source, url, title, summary,
                     relevance_score, used_in_post_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(item.id),
                    item.fetched_at.isoformat(),
                    item.source,
                    item.url,
                    item.title,
                    item.summary,
                    item.relevance_score,
                    json.dumps([str(uid) for uid in item.used_in_post_ids]),
                ),
            )
            new_count += cursor.rowcount
    return new_count


def fetch_and_store(db_path: Path | None = None) -> int:
    """Fetch all feeds and persist new items. Returns count of new items stored."""
    target = db_path or settings.db_path
    items = fetch_all_feeds()
    new_count = store_news_items(target, items)
    log.info("news_ingestion_done", total_fetched=len(items), new_stored=new_count)
    return new_count


def get_recent_items(
    db_path: Path,
    *,
    hours: int = 48,
    limit: int = 40,
) -> list[NewsItem]:
    """Return recent news items, newest first."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM news_items
            WHERE fetched_at >= datetime('now', ?)
            ORDER BY fetched_at DESC
            LIMIT ?
            """,
            (f"-{hours} hours", limit),
        ).fetchall()
    return [_row_to_news_item(row) for row in rows]


def update_relevance_score(db_path: Path, item_id: UUID, score: float) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE news_items SET relevance_score = ? WHERE id = ?",
            (score, str(item_id)),
        )


def _row_to_news_item(row: sqlite3.Row) -> NewsItem:
    return NewsItem(
        id=UUID(str(row["id"])),
        fetched_at=datetime.fromisoformat(str(row["fetched_at"])),
        source=str(row["source"]),
        url=str(row["url"]),
        title=str(row["title"]),
        summary=str(row["summary"]),
        relevance_score=float(row["relevance_score"]) if row["relevance_score"] is not None else None,
        used_in_post_ids=[UUID(s) for s in json.loads(str(row["used_in_post_ids"]))],
    )
