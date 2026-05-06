"""IdeatorAgent — surface ranked post angles from the news feed."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Literal

import structlog
import yaml
from pydantic import BaseModel

from src.agents.base import Agent, render_prompt
from src.brain.posts import list_posts
from src.config import config, settings
from src.inputs.news import fetch_and_store, get_recent_items
from src.llm import call_llm
from src.schemas import NewsItem

log = structlog.get_logger()

_SYSTEM = (
    "You are a content strategist. "
    "Follow all instructions exactly and return only valid JSON."
)


class IdeatorInput(BaseModel):
    max_angles: int = 10
    news_hours: int = 48
    refresh_news: bool = True


class RankedAngle(BaseModel):
    topic_lane: Literal["ai_for_pms", "pm_craft", "healthcare_ai"]
    sub_topic: str
    context_note: str
    rationale: str
    relevance_score: float
    source_title: str = ""
    source_url: str = ""


class IdeatorOutput(BaseModel):
    angles: list[RankedAngle]
    news_items_used: int
    prompt_version: str
    model: str
    input_tokens: int
    output_tokens: int


class IdeatorAgent(Agent[IdeatorInput, IdeatorOutput]):
    def run(self, input_data: IdeatorInput) -> IdeatorOutput:
        if input_data.refresh_news:
            new_count = fetch_and_store(settings.db_path)
            log.info("news_refreshed", new_items=new_count)

        news_items = get_recent_items(
            settings.db_path,
            hours=input_data.news_hours,
            limit=40,
        )

        # All non-rejected posts from recent days — gives the model real theme avoidance signal
        recent_posts = list_posts(
            settings.db_path,
            exclude_statuses=["rejected"],
            limit=15,
        )

        topics_path = Path("data") / "topics.yaml"
        topics_text = topics_path.read_text(encoding="utf-8")
        lane_targets = _compute_lane_targets(topics_path, input_data.max_angles)

        news_text = _format_news_items(news_items)
        recent_posts_text = _format_recent_posts(recent_posts)

        prompt, front = render_prompt(
            "ideator",
            topics_yaml=topics_text,
            news_items=news_text,
            recent_posts=recent_posts_text,
            lane_targets=lane_targets,
        )

        model: str = config["models"]["ideator"]
        temperature: float = config["agent_defaults"]["temperature"]
        max_tokens: int = config["agent_defaults"].get("ideator_max_tokens", 4096)

        log.info(
            "ideator_agent_start",
            news_items_count=len(news_items),
            recent_posts_count=len(recent_posts),
            prompt_version=front.get("version", "unknown"),
        )

        response = call_llm(
            model=model,
            system=_SYSTEM,
            user=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        angles = _parse_angles(response.text)[: input_data.max_angles]

        log.info(
            "ideator_agent_done",
            angles_count=len(angles),
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

        return IdeatorOutput(
            angles=angles,
            news_items_used=len(news_items),
            prompt_version=str(front.get("version", "unknown")),
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )


def _format_news_items(items: list[NewsItem]) -> str:
    if not items:
        return "No recent news items available."
    parts: list[str] = []
    for i, item in enumerate(items, 1):
        parts.append(
            f"{i}. [{item.source}] {item.title}\n"
            f"   URL: {item.url}\n"
            f"   Summary: {item.summary[:300]}"
        )
    return "\n\n".join(parts)


def _format_recent_posts(posts: list) -> str:  # type: ignore[type-arg]
    if not posts:
        return "No recent content."
    lines: list[str] = []
    for post in posts:
        lines.append(f"- [{post.status}] [{post.topic_lane} / {post.sub_topic}] {post.hook}")
    return "\n".join(lines)


def _compute_lane_targets(topics_path: Path, total: int) -> str:
    """Return a human-readable lane target string derived from lane_weights in topics.yaml."""
    data = yaml.safe_load(topics_path.read_text(encoding="utf-8"))
    lanes: dict[str, dict[str, float]] = data.get("lanes", {})
    lines: list[str] = []
    for lane, info in lanes.items():
        weight = float(info.get("lane_weight", 0.0))
        target = math.ceil(weight * total)
        lines.append(f"- {lane}: ~{target} of {total} angles (weight {int(weight*100)}%)")
    return "\n".join(lines)


def _parse_angles(raw: str) -> list[RankedAngle]:
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"No valid JSON in ideator response: {text[:200]}") from None
        data = json.loads(match.group(0))

    angles = [RankedAngle(**a) for a in data["angles"]]
    return sorted(angles, key=lambda a: a.relevance_score, reverse=True)
