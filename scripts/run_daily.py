#!/usr/bin/env python3
"""Daily pipeline: map idea → generate drafts → save to DB → send to Telegram.

Usage:
    uv run --system-certs python scripts/run_daily.py --idea "why leadership matters as you scale as a PM"
    uv run --system-certs python scripts/run_daily.py --topic pm_craft --sub-topic stakeholder_management
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import truststore
import typer
from telegram.ext import Application

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agents.critic import CriticAgent, CriticInput  # noqa: E402
from src.agents.ideator import IdeatorAgent, IdeatorInput  # noqa: E402
from src.agents.mapper import AngleMappingAgent, MapperInput  # noqa: E402
from src.agents.writer import DraftPost, WriterAgent, WriterInput  # noqa: E402
from src.brain.posts import insert_post  # noqa: E402
from src.config import settings  # noqa: E402
from src.llm import configure_logging  # noqa: E402
from src.outputs.telegram_bot import build_app, send_draft  # noqa: E402
from src.schemas import Post  # noqa: E402

cli = typer.Typer(name="run_daily", add_completion=False)


@cli.command()
def main(
    idea: str | None = typer.Option(None, help="Free-text idea, e.g. 'why leadership matters as you scale as a PM'"),
    topic: str | None = typer.Option(None, help="Topic lane override: ai_for_pms | pm_craft | healthcare_ai"),
    sub_topic: str | None = typer.Option(None, help="Sub-topic slug override"),
    context: str = typer.Option("", help="Extra context note (used with --topic/--sub-topic)"),
) -> None:
    """Generate drafts and send to Telegram for review."""
    truststore.inject_into_ssl()
    configure_logging(settings.log_path, settings.log_level)

    # Resolve angle — ideator (default) > free-text mapper > explicit args
    resolved_topic: str
    resolved_sub_topic: str
    resolved_context: str

    if not idea and not topic:
        typer.echo("No idea provided — running Ideator to pick today's angle...")
        ideator_result = IdeatorAgent().run(IdeatorInput())
        if not ideator_result.angles:
            typer.echo("Ideator returned no angles. Provide --idea or --topic to continue.", err=True)
            raise typer.Exit(1)
        top = ideator_result.angles[0]
        typer.echo(f"  Top angle [{top.relevance_score:.2f}]: {top.topic_lane} / {top.sub_topic}")
        typer.echo(f"  Angle:  {top.context_note}")
        typer.echo(f"  Why:    {top.rationale}")
        if top.source_title:
            typer.echo(f"  Source: {top.source_title}")
        typer.echo()
        resolved_topic = top.topic_lane
        resolved_sub_topic = top.sub_topic
        resolved_context = top.context_note
    elif idea:
        typer.echo("Mapping idea to angle...")
        angle = AngleMappingAgent().run(MapperInput(free_text=idea))
        typer.echo(f"  Lane:      {angle.topic_lane}")
        typer.echo(f"  Sub-topic: {angle.sub_topic}")
        typer.echo(f"  Angle:     {angle.context_note}")
        typer.echo(f"  Why:       {angle.rationale}")
        typer.echo()
        resolved_topic = angle.topic_lane
        resolved_sub_topic = angle.sub_topic
        resolved_context = angle.context_note
    elif topic and sub_topic:
        resolved_topic = topic
        resolved_sub_topic = sub_topic
        resolved_context = context
    else:
        typer.echo("Error: provide --topic with --sub-topic.", err=True)
        raise typer.Exit(1)

    typer.echo(f"Generating drafts for {resolved_topic} / {resolved_sub_topic}...")
    result = WriterAgent().run(
        WriterInput(
            topic_lane=resolved_topic,  # type: ignore[arg-type]
            sub_topic=resolved_sub_topic,
            context_note=resolved_context,
        )
    )
    typer.echo(
        f"  {len(result.drafts)} drafts — {result.model} "
        f"({result.input_tokens}in / {result.output_tokens}out tokens)"
    )

    critic = CriticAgent()
    saved: list[tuple[Any, DraftPost, Any]] = []
    for draft in result.drafts:
        score = critic.run(CriticInput(draft=draft))
        post = Post(
            id=uuid4(),
            created_at=datetime.now(tz=UTC),
            posted_at=None,
            status="draft",
            body=draft.body,
            hook=draft.hook,
            topic_lane=resolved_topic,  # type: ignore[arg-type]
            sub_topic=resolved_sub_topic,
            format=draft.format,
            source_input_ids=[],
            prompt_version=result.prompt_version,
            model=result.model,
        )
        insert_post(settings.db_path, post)
        saved.append((post.id, draft, score))

    typer.echo(f"  Saved {len(saved)} drafts to DB. Sending to Telegram...")
    pending = saved[:]

    async def _on_start(bot_app: Application[Any, Any, Any, Any, Any, Any]) -> None:
        for i, (post_id, draft, score) in enumerate(pending, 1):
            await send_draft(bot_app, post_id, i, draft, score)

    typer.echo("Waiting for your review on Telegram (Ctrl+C to quit).")
    build_app(post_init=_on_start).run_polling()


if __name__ == "__main__":
    cli()
