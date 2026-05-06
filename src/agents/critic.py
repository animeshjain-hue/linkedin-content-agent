import json
import re

from pydantic import BaseModel, computed_field

from src.agents.base import Agent, render_prompt
from src.agents.writer import DraftPost
from src.config import config
from src.llm import call_llm

_SYSTEM = (
    "You are a strict content critic. "
    "Follow all scoring instructions exactly and return only valid JSON."
)


class CriticInput(BaseModel):
    draft: DraftPost


class CriticScore(BaseModel):
    hook_strength: int
    voice_match: int
    argument_quality: int
    hygiene: int
    verdict: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall(self) -> float:
        return (self.hook_strength + self.voice_match + self.argument_quality + self.hygiene) / 4.0


class CriticAgent(Agent[CriticInput, CriticScore]):
    def run(self, input_data: CriticInput) -> CriticScore:
        prompt, _ = render_prompt(
            "critic",
            draft_format=input_data.draft.format,
            draft_body=input_data.draft.body,
        )

        model: str = config["models"]["critic"]

        response = call_llm(
            model=model,
            system=_SYSTEM,
            user=prompt,
            temperature=0.0,
            max_tokens=250,
        )

        return _parse_score(response.text)


def _parse_score(raw: str) -> CriticScore:
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"No valid JSON in critic response: {text[:200]}") from None
        data = json.loads(match.group(0))

    return CriticScore(**data)
