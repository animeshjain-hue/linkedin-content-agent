import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings

log = structlog.get_logger()


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


def configure_logging(log_path: Path, level: str = "INFO") -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_level = getattr(logging, level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:10]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    reraise=True,
)
def call_llm(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
) -> LLMResponse:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    t0 = time.monotonic()

    # Claude 4.x models (opus-4-7, sonnet-4-6, etc.) have deprecated temperature
    create_kwargs: dict[str, object] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if not model.startswith("claude-opus-4") and not model.startswith("claude-sonnet-4") and not model.startswith("claude-haiku-4"):
        create_kwargs["temperature"] = temperature

    message = client.messages.create(**create_kwargs)  # type: ignore[arg-type]

    latency_ms = int((time.monotonic() - t0) * 1000)
    text_block = next((b for b in message.content if b.type == "text"), None)
    text = text_block.text if text_block else ""  # type: ignore[union-attr]

    log.info(
        "llm_call",
        model=model,
        input_hash=_sha(user),
        output_hash=_sha(text),
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        latency_ms=latency_ms,
    )

    return LLMResponse(
        text=text,
        model=model,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        latency_ms=latency_ms,
    )
