import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from src.brain.db import get_connection
from src.schemas import EngagementSnapshot, Post


def insert_post(db_path: Path, post: Post) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO posts
                (id, created_at, posted_at, status, body, hook, topic_lane,
                 sub_topic, format, source_input_ids, prompt_version, model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(post.id),
                post.created_at.isoformat(),
                post.posted_at.isoformat() if post.posted_at else None,
                post.status,
                post.body,
                post.hook,
                post.topic_lane,
                post.sub_topic,
                post.format,
                json.dumps([str(uid) for uid in post.source_input_ids]),
                post.prompt_version,
                post.model,
            ),
        )


def get_post(db_path: Path, post_id: UUID) -> Post | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (str(post_id),)).fetchone()
    return _row_to_post(row) if row else None


def list_posts(
    db_path: Path,
    *,
    status: str | None = None,
    exclude_statuses: list[str] | None = None,
    topic_lane: str | None = None,
    limit: int | None = None,
) -> list[Post]:
    clauses: list[str] = []
    params: list[object] = []

    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if exclude_statuses:
        placeholders = ",".join("?" * len(exclude_statuses))
        clauses.append(f"status NOT IN ({placeholders})")
        params.extend(exclude_statuses)
    if topic_lane is not None:
        clauses.append("topic_lane = ?")
        params.append(topic_lane)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    limit_clause = f"LIMIT {limit}" if limit is not None else ""

    query = f"SELECT * FROM posts {where} ORDER BY created_at DESC {limit_clause}"

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    return [_row_to_post(row) for row in rows]


def update_post_status(db_path: Path, post_id: UUID, status: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute("UPDATE posts SET status = ? WHERE id = ?", (status, str(post_id)))


def update_post_body(db_path: Path, post_id: UUID, body: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute("UPDATE posts SET body = ? WHERE id = ?", (body, str(post_id)))


def insert_engagement_snapshot(db_path: Path, snapshot: EngagementSnapshot) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO engagement_snapshots
                (id, post_id, captured_at, impressions, reactions, comments,
                 reposts, profile_views_delta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                str(snapshot.post_id),
                snapshot.captured_at.isoformat(),
                snapshot.impressions,
                snapshot.reactions,
                snapshot.comments,
                snapshot.reposts,
                snapshot.profile_views_delta,
            ),
        )


def _row_to_post(row: sqlite3.Row) -> Post:
    return Post(
        id=UUID(str(row["id"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        posted_at=datetime.fromisoformat(str(row["posted_at"])) if row["posted_at"] else None,
        status=str(row["status"]),  # type: ignore[arg-type]
        body=str(row["body"]),
        hook=str(row["hook"]),
        topic_lane=str(row["topic_lane"]),  # type: ignore[arg-type]
        sub_topic=str(row["sub_topic"]),
        format=str(row["format"]),  # type: ignore[arg-type]
        source_input_ids=[UUID(s) for s in json.loads(str(row["source_input_ids"]))],
        prompt_version=str(row["prompt_version"]),
        model=str(row["model"]),
    )
