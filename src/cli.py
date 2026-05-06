import asyncio
import os
import signal
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import truststore
import typer
from telegram.ext import Application

from src.config import settings
from src.llm import configure_logging

app = typer.Typer(name="agent", help="LinkedIn content agent CLI.")


async def _shutdown_after(hours: int) -> None:
    """Send SIGTERM to self after N hours — lets run_polling() exit gracefully."""
    await asyncio.sleep(hours * 3600)
    os.kill(os.getpid(), signal.SIGTERM)


@app.command()
def write(
    topic: str = typer.Option(..., help="Topic lane: ai_for_pms | pm_craft | healthcare_ai"),
    sub_topic: str = typer.Option(..., help="Sub-topic, e.g. agentic_systems_for_pms"),
    context: str = typer.Option("", help="Optional context note to guide the angle"),
) -> None:
    """Generate 2 draft post variants for a topic."""
    from src.agents.writer import WriterAgent, WriterInput

    truststore.inject_into_ssl()
    configure_logging(settings.log_path, settings.log_level)

    result = WriterAgent().run(
        WriterInput(
            topic_lane=topic,  # type: ignore[arg-type]
            sub_topic=sub_topic,
            context_note=context,
        )
    )

    typer.echo(f"\n{'='*60}")
    typer.echo(f"Model: {result.model} | Tokens: {result.input_tokens}in / {result.output_tokens}out")
    typer.echo(f"Prompt version: {result.prompt_version}")
    typer.echo(f"{'='*60}\n")

    for i, draft in enumerate(result.drafts, 1):
        typer.echo(f"── DRAFT {i} [{draft.format}] ──")
        typer.echo(f"Rationale: {draft.rationale}")
        typer.echo()
        typer.echo(draft.body)
        typer.echo()


@app.command()
def fetch_news() -> None:
    """Pull latest RSS feeds and store new items in the brain DB."""
    from src.inputs.news import fetch_and_store

    truststore.inject_into_ssl()
    configure_logging(settings.log_path, settings.log_level)

    new_count = fetch_and_store(settings.db_path)
    typer.echo(f"Fetched feeds — {new_count} new items stored.")


@app.command()
def ideate(
    hours: int = typer.Option(48, help="Look back this many hours for news items"),
    no_refresh: bool = typer.Option(False, help="Skip fetching fresh feeds; use DB only"),
) -> None:
    """Fetch news and surface ranked post angles via the Ideator agent."""
    from src.agents.ideator import IdeatorAgent, IdeatorInput

    truststore.inject_into_ssl()
    configure_logging(settings.log_path, settings.log_level)

    typer.echo("Running ideator...")
    result = IdeatorAgent().run(
        IdeatorInput(news_hours=hours, refresh_news=not no_refresh)
    )

    typer.echo(
        f"\nModel: {result.model} | Tokens: {result.input_tokens}in / {result.output_tokens}out"
    )
    typer.echo(f"News items evaluated: {result.news_items_used}")
    typer.echo(f"Angles surfaced: {len(result.angles)}\n")

    for i, angle in enumerate(result.angles, 1):
        typer.echo(f"{'─'*60}")
        typer.echo(f"#{i}  [{angle.relevance_score:.2f}] {angle.topic_lane} / {angle.sub_topic}")
        typer.echo(f"Angle:    {angle.context_note}")
        typer.echo(f"Why now:  {angle.rationale}")
        if angle.source_title:
            typer.echo(f"Source:   {angle.source_title}")
            typer.echo(f"          {angle.source_url}")
        typer.echo()


@app.command()
def run_daily(
    idea: str | None = typer.Option(None, help="Free-text idea, e.g. 'why leadership matters as you scale as a PM'"),
    topic: str | None = typer.Option(None, help="Topic lane override: ai_for_pms | pm_craft | healthcare_ai"),
    sub_topic: str | None = typer.Option(None, help="Sub-topic slug override"),
    context: str = typer.Option("", help="Extra context note (used with --topic/--sub-topic)"),
    timeout: int = typer.Option(4, help="Auto-exit after this many hours if no Telegram response"),
) -> None:
    """Generate drafts and send to Telegram for review.

    With no flags: auto-fetches news, ideates, picks the top angle.
    With --idea: maps free text to an angle.
    With --topic + --sub-topic: uses those directly.
    """
    from src.agents.critic import CriticAgent, CriticInput
    from src.agents.ideator import IdeatorAgent, IdeatorInput
    from src.agents.mapper import AngleMappingAgent, MapperInput
    from src.agents.writer import DraftPost, WriterAgent, WriterInput
    from src.brain.posts import insert_post
    from src.outputs.telegram_bot import build_app, send_draft
    from src.schemas import Post

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
        asyncio.create_task(_shutdown_after(timeout))

    typer.echo(f"Waiting for your review on Telegram (auto-exit in {timeout}h).")
    build_app(post_init=_on_start).run_polling()


if __name__ == "__main__":
    app()
