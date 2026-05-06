from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class Post(BaseModel):
    id: UUID
    created_at: datetime
    posted_at: datetime | None = None
    status: Literal["draft", "approved", "scheduled", "posted", "rejected"]
    body: str
    hook: str
    topic_lane: Literal["ai_for_pms", "pm_craft", "healthcare_ai"]
    sub_topic: str
    format: Literal["story", "framework", "contrarian", "list", "build_log", "question"]
    source_input_ids: list[UUID] = []
    prompt_version: str
    model: str


class EngagementSnapshot(BaseModel):
    post_id: UUID
    captured_at: datetime
    impressions: int | None = None
    reactions: int
    comments: int
    reposts: int
    profile_views_delta: int | None = None


class VoiceGuide(BaseModel):
    sound_like: list[str]
    dont_sound_like: list[str]
    authority_topics: list[str]
    example_sentences: list[str]
    forbidden_phrases: list[str]


class StrategyDoc(BaseModel):
    week_of: date
    lane_mix: dict[str, float]
    target_frequency: int
    preferred_formats: list[str]
    preferred_post_times: list[str]
    experiments: list[str]
    avoid: list[str]
    rationale: str


class NewsItem(BaseModel):
    id: UUID
    fetched_at: datetime
    source: str
    url: str
    title: str
    summary: str
    relevance_score: float | None = None
    used_in_post_ids: list[UUID] = []
