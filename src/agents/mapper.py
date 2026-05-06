import json
import re
from typing import Literal

from pydantic import BaseModel

from src.agents.base import Agent, render_prompt
from src.config import config
from src.llm import call_llm

_SYSTEM = (
    "You are a content strategist. "
    "Follow all instructions exactly and return only valid JSON."
)


class MapperInput(BaseModel):
    free_text: str


class Angle(BaseModel):
    topic_lane: Literal["ai_for_pms", "pm_craft", "healthcare_ai"]
    sub_topic: str
    context_note: str
    rationale: str


class AngleMappingAgent(Agent[MapperInput, Angle]):
    def run(self, input_data: MapperInput) -> Angle:
        prompt, _ = render_prompt("angle_mapper", free_text=input_data.free_text)
        model: str = config["models"]["mapper"]

        response = call_llm(
            model=model,
            system=_SYSTEM,
            user=prompt,
            temperature=0.3,
            max_tokens=300,
        )

        return _parse_angle(response.text)


def _parse_angle(raw: str) -> Angle:
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"No valid JSON in mapper response: {text[:200]}") from None
        data = json.loads(match.group(0))

    return Angle(**data)
