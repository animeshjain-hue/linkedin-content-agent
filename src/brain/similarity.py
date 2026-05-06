from pathlib import Path

from src.brain.posts import list_posts
from src.schemas import Post


def find_similar_posts(
    db_path: Path,
    topic_lane: str,
    sub_topic: str,
    limit: int = 5,
) -> list[Post]:
    """Return up to `limit` posts, preferring sub_topic match within the lane."""
    candidates = list_posts(db_path, topic_lane=topic_lane)
    matching = [p for p in candidates if p.sub_topic == sub_topic]
    others = [p for p in candidates if p.sub_topic != sub_topic]
    return (matching + others)[:limit]


def format_posts_for_prompt(posts: list[Post]) -> str:
    """Render posts as compact reference blocks for injection into a prompt."""
    if not posts:
        return "(no similar posts found in corpus)"

    blocks: list[str] = []
    for p in posts:
        blocks.append(f"[Hook: {p.hook!r} | Format: {p.format}]\n{p.body}")

    return "\n\n---\n\n".join(blocks)
