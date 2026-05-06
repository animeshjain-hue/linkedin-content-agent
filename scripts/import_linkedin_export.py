"""
Ingest data/seed_posts/content_brain.md into the Brand Brain DB.

Each post is inserted with status='posted', prompt_version='human', model='human'.
Engagement snapshots are inserted for posts that have numeric data.
"""

import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# Make src importable when run from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.brain.db import run_migrations
from src.brain.posts import insert_engagement_snapshot, insert_post
from src.config import settings
from src.schemas import EngagementSnapshot, Post

SEED_PATH = Path("data/seed_posts/content_brain.md")

# Keyword sets for topic/format inference
_AI_KEYWORDS = {
    "chatgpt",
    "llm",
    "gen ai",
    "generative ai",
    "artificial intelligence",
    "claude",
    "gpt",
    "openai",
    "whisper",
    "jio ai",
    "sovereign ai",
}
_TEARDOWN_COMPANIES = {
    "zomato",
    "blinkit",
    "rapido",
    "zepto",
    "swiggy",
    "district",
    "paytm",
    "flipkart",
    "meesho",
    "bigbasket",
}


def infer_topic_lane(body: str) -> str:
    lower = body.lower()
    if any(kw in lower for kw in _AI_KEYWORDS):
        return "ai_for_pms"
    return "pm_craft"


def infer_sub_topic(body: str, topic_lane: str) -> str:
    lower = body.lower()
    if topic_lane == "ai_for_pms":
        if "agentic" in lower or " agent" in lower:
            return "agentic_systems_for_pms"
        if "strategy" in lower or "startup" in lower:
            return "ai_product_strategy"
        return "llm_tooling_critique"
    # pm_craft
    if any(c in lower for c in _TEARDOWN_COMPANIES):
        return "strategy_teardowns"
    if any(kw in lower for kw in ("career", "college", "iit", "gave up", "job market")):
        return "career_and_learning"
    if "b2b" in lower:
        return "b2b_pm_contrarian"
    if any(kw in lower for kw in ("execution", "project management", "jira")):
        return "execution_vs_project_mgmt"
    if any(kw in lower for kw in ("analytics", "data", "metrics", "mixpanel")):
        return "data_and_decisions"
    return "prioritization_in_practice"


def infer_format(body: str) -> str:
    lower = body.lower()
    first_line = body.split("\n")[0].strip()

    if any(phrase in lower for phrase in ("i am frustrated", "please stop", "we need to stop")):
        return "contrarian"
    if first_line.endswith("?"):
        return "question"
    if any(kw in lower for kw in ("buaji", "beta bas", "kuch nahi", "toh tum")):
        return "story"
    if re.search(r"\n[1-9][/\.]", body) or re.search(r"step \d", lower):
        return "list"
    return "story"


def extract_hook(body: str) -> str:
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    return "\n".join(lines[:2])


def parse_seed_file(path: Path) -> list[dict]:  # type: ignore[type-arg]
    content = path.read_text(encoding="utf-8")
    section = content.split("## Full Post Text", 1)[1]

    pattern = re.compile(
        r"### Post \d+ — R:(\d+) C:(\d+) S:(\d+) I:(\d+|N/A)\n\n(.*?)(?=\n---\n|\Z)",
        re.DOTALL,
    )

    posts = []
    for match in pattern.finditer(section):
        reactions, comments, shares, impressions_raw, body = match.groups()
        posts.append(
            {
                "reactions": int(reactions),
                "comments": int(comments),
                "shares": int(shares),
                "impressions": int(impressions_raw) if impressions_raw != "N/A" else None,
                "body": body.strip(),
            }
        )
    return posts


def main() -> None:
    run_migrations(settings.db_path)

    raw_posts = parse_seed_file(SEED_PATH)
    now = datetime.now(tz=UTC)
    inserted = 0

    for raw in raw_posts:
        body: str = raw["body"]
        topic_lane = infer_topic_lane(body)
        post = Post(
            id=uuid4(),
            created_at=now,
            posted_at=None,
            status="posted",
            body=body,
            hook=extract_hook(body),
            topic_lane=topic_lane,  # type: ignore[arg-type]
            sub_topic=infer_sub_topic(body, topic_lane),
            format=infer_format(body),  # type: ignore[arg-type]
            source_input_ids=[],
            prompt_version="human",
            model="human",
        )
        insert_post(settings.db_path, post)

        snapshot = EngagementSnapshot(
            post_id=post.id,
            captured_at=now,
            impressions=raw["impressions"],
            reactions=raw["reactions"],
            comments=raw["comments"],
            reposts=raw["shares"],
            profile_views_delta=None,
        )
        insert_engagement_snapshot(settings.db_path, snapshot)
        inserted += 1

    print(f"Imported {inserted} posts into {settings.db_path}")


if __name__ == "__main__":
    main()
