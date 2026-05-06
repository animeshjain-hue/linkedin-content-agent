import json
import re

from pydantic import BaseModel, computed_field

from src.agents.base import Agent, render_prompt
from src.agents.writer import DraftPost
from src.config import config
from src.llm import call_llm

_SYSTEM = (
    "You are a strict voice quality judge. "
    "Follow all scoring instructions exactly and return only valid JSON."
)


class EvaluatorInput(BaseModel):
    draft: DraftPost
    voice_guide: str
    seed_hooks: str


class EvalScore(BaseModel):
    voice_match: int
    hook_strength: int
    originality: int
    hygiene: int
    verdict: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def average(self) -> float:
        return (self.voice_match + self.hook_strength + self.originality + self.hygiene) / 4.0


class EvaluatorAgent(Agent[EvaluatorInput, EvalScore]):
    def run(self, input_data: EvaluatorInput) -> EvalScore:
        prompt, _ = render_prompt(
            "voice_eval",
            voice_guide=input_data.voice_guide,
            seed_hooks=input_data.seed_hooks,
            draft_format=input_data.draft.format,
            draft_hook=input_data.draft.hook,
            draft_body=input_data.draft.body,
        )

        model: str = config["models"]["evaluator"]
        max_tokens: int = 600

        response = call_llm(
            model=model,
            system=_SYSTEM,
            user=prompt,
            temperature=0.0,
            max_tokens=max_tokens,
        )

        return _parse_score(response.text)


def _parse_score(raw: str) -> EvalScore:
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"No valid JSON in evaluator response: {text[:200]}") from None
        data = json.loads(match.group(0))

    return EvalScore(**data)
