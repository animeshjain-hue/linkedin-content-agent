import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Generic, TypeVar

import yaml
from pydantic import BaseModel

PROMPTS_DIR = Path("prompts")

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class Agent(ABC, Generic[InputT, OutputT]):
    @abstractmethod
    def run(self, input_data: InputT) -> OutputT: ...


class _SafeMap(dict):  # type: ignore[type-arg]
    """Returns the placeholder unchanged for any missing key."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_prompt(name: str, **variables: str) -> tuple[str, dict[str, Any]]:
    """Load prompts/{name}.md, parse YAML frontmatter, substitute {var} placeholders.

    Uses regex substitution so literal JSON braces in the template are safe.
    Returns (rendered_text, frontmatter_dict).
    """
    path = PROMPTS_DIR / f"{name}.md"
    content = path.read_text(encoding="utf-8")

    if content.startswith("---"):
        _, front, body = content.split("---", 2)
        front_matter: dict[str, Any] = yaml.safe_load(front) or {}
        template = body.strip()
    else:
        front_matter = {}
        template = content.strip()

    # Replace {variable} placeholders; leave anything not in variables unchanged
    rendered = re.sub(
        r"\{(\w+)\}",
        lambda m: variables.get(m.group(1), m.group(0)),
        template,
    )
    return rendered, front_matter
