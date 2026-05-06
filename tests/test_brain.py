from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from src.brain.db import run_migrations
from src.brain.posts import (
    get_post,
    insert_engagement_snapshot,
    insert_post,
    list_posts,
)
from src.schemas import EngagementSnapshot, Post

MIGRATIONS_DIR = Path("migrations")


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    run_migrations(path, MIGRATIONS_DIR)
    return path


def _post(**overrides: object) -> Post:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "created_at": datetime.now(tz=UTC),
        "posted_at": None,
        "status": "posted",
        "body": "Test post body with enough content.",
        "hook": "Test post body",
        "topic_lane": "pm_craft",
        "sub_topic": "career_and_learning",
        "format": "story",
        "source_input_ids": [],
        "prompt_version": "human",
        "model": "human",
    }
    defaults.update(overrides)
    return Post(**defaults)


# --- migration ---


def test_migration_creates_tables(db: Path) -> None:
    from src.brain.db import _table_exists, get_connection

    with get_connection(db) as conn:
        assert _table_exists(conn, "posts")
        assert _table_exists(conn, "engagement_snapshots")
        assert _table_exists(conn, "news_items")
        assert _table_exists(conn, "schema_migrations")


def test_migration_is_idempotent(db: Path) -> None:
    # Running migrations a second time should not raise
    run_migrations(db, MIGRATIONS_DIR)


# --- insert / get ---


def test_insert_and_get_post(db: Path) -> None:
    post = _post()
    insert_post(db, post)
    fetched = get_post(db, post.id)
    assert fetched is not None
    assert fetched.id == post.id
    assert fetched.body == post.body
    assert fetched.topic_lane == "pm_craft"


def test_get_nonexistent_post_returns_none(db: Path) -> None:
    assert get_post(db, uuid4()) is None


def test_insert_preserves_optional_fields(db: Path) -> None:
    post = _post(posted_at=datetime(2025, 1, 1, tzinfo=UTC), source_input_ids=[uuid4()])
    insert_post(db, post)
    fetched = get_post(db, post.id)
    assert fetched is not None
    assert fetched.posted_at is not None
    assert len(fetched.source_input_ids) == 1


# --- list ---


def test_list_posts_returns_all(db: Path) -> None:
    for _ in range(3):
        insert_post(db, _post())
    assert len(list_posts(db)) == 3


def test_list_posts_filter_status(db: Path) -> None:
    insert_post(db, _post(status="posted"))
    insert_post(db, _post(status="draft"))
    results = list_posts(db, status="posted")
    assert len(results) == 1
    assert results[0].status == "posted"


def test_list_posts_filter_topic_lane(db: Path) -> None:
    insert_post(db, _post(topic_lane="pm_craft"))
    insert_post(db, _post(topic_lane="ai_for_pms"))
    results = list_posts(db, topic_lane="ai_for_pms")
    assert len(results) == 1
    assert results[0].topic_lane == "ai_for_pms"


def test_list_posts_limit(db: Path) -> None:
    for _ in range(5):
        insert_post(db, _post())
    assert len(list_posts(db, limit=3)) == 3


# --- engagement snapshot ---


def test_insert_engagement_snapshot(db: Path) -> None:
    post = _post()
    insert_post(db, post)
    snapshot = EngagementSnapshot(
        post_id=post.id,
        captured_at=datetime.now(tz=UTC),
        impressions=5000,
        reactions=48,
        comments=3,
        reposts=0,
    )
    insert_engagement_snapshot(db, snapshot)

    from src.brain.db import get_connection

    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT * FROM engagement_snapshots WHERE post_id = ?", (str(post.id),)
        ).fetchone()
    assert row is not None
    assert row["reactions"] == 48
    assert row["impressions"] == 5000
