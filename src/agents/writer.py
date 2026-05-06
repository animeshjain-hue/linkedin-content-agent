import json
import re
from typing import Literal

import structlog
from pydantic import BaseModel

from src.agents.base import Agent, render_prompt
from src.brain.similarity import find_similar_posts, format_posts_for_prompt
from src.brain.voice import load_voice_guide
from src.config import config, settings
from src.llm import call_llm

log = structlog.get_logger()


class WriterInput(BaseModel):
    topic_lane: Literal["ai_for_pms", "pm_craft", "healthcare_ai"]
    sub_topic: str
    context_note: str = ""


class DraftPost(BaseModel):
    body: str
    hook: str
    format: Literal["story", "framework", "contrarian", "list", "build_log", "question"]
    rationale: str


class WriterOutput(BaseModel):
    drafts: list[DraftPost]
    prompt_version: str
    model: str
    input_tokens: int
    output_tokens: int


_SYSTEM = (
    "You are an expert LinkedIn ghostwriter. "
    "Follow all instructions exactly and return only valid JSON."
)


class WriterAgent(Agent[WriterInput, WriterOutput]):
    def run(self, input_data: WriterInput) -> WriterOutput:
        voice_guide = load_voice_guide()
        similar = find_similar_posts(
            settings.db_path,
            topic_lane=input_data.topic_lane,
            sub_topic=input_data.sub_topic,
        )
        similar_posts_text = format_posts_for_prompt(similar)

        context_note = (
            f"\nAdditional context: {input_data.context_note}"
            if input_data.context_note
            else ""
        )

        prompt, front = render_prompt(
            "writer",
            voice_guide=voice_guide,
            similar_posts=similar_posts_text,
            topic_lane=input_data.topic_lane,
            sub_topic=input_data.sub_topic,
            context_note=context_note,
        )

        model: str = config["models"]["writer"]
        temperature: float = config["agent_defaults"]["temperature"]
        max_tokens: int = config["agent_defaults"]["max_tokens"]

        log.info(
            "writer_agent_start",
            topic_lane=input_data.topic_lane,
            sub_topic=input_data.sub_topic,
            similar_posts_count=len(similar),
            prompt_version=front.get("version", "unknown"),
        )

        response = call_llm(
            model=model,
            system=_SYSTEM,
            user=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        drafts = _parse_drafts(response.text)

        log.info(
            "writer_agent_done",
            drafts_count=len(drafts),
            prompt_version=front.get("version"),
        )

        return WriterOutput(
            drafts=drafts,
            prompt_version=str(front.get("version", "unknown")),
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )


def _parse_drafts(raw: str) -> list[DraftPost]:
    """Extract JSON from LLM response and parse into DraftPost list."""
    # Strip any accidental markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract the first JSON object if there's surrounding text
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"No valid JSON found in LLM response: {text[:200]}") from None
        data = json.loads(match.group(0))

    return [DraftPost(**d) for d in data["drafts"]]
