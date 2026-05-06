"""Telegram bot — human-in-the-loop draft review."""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.agents.critic import CriticScore
from src.agents.writer import DraftPost
from src.brain.posts import get_post, update_post_body, update_post_status
from src.config import settings
from src.outputs.typefully import schedule_post

log = structlog.get_logger()

# Single-user state: chat_id → (state, post_id)
_pending: dict[int, tuple[str, UUID]] = {}


def _score_line(score: CriticScore) -> str:
    return (
        f"Score {score.overall:.1f}/10 · "
        f"Hook {score.hook_strength} · "
        f"Voice {score.voice_match} · "
        f"Sub {score.argument_quality} · "
        f"Clean {score.hygiene}"
    )


def _draft_text(draft_num: int, draft: DraftPost, score: CriticScore | None) -> str:
    header = f"── DRAFT {draft_num} [{draft.format}] ──"
    if score is not None:
        header += f"\n{_score_line(score)}\n\"{score.verdict}\""
    return f"{header}\n\n{draft.body}"


def _keyboard(post_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{post_id}"),
        InlineKeyboardButton("✏️ Edit", callback_data=f"edit:{post_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject:{post_id}"),
    ]])


async def send_draft(
    app: Application,  # type: ignore[type-arg]
    post_id: UUID,
    draft_num: int,
    draft: DraftPost,
    score: CriticScore | None = None,
) -> None:
    await app.bot.send_message(
        chat_id=int(settings.telegram_chat_id),
        text=_draft_text(draft_num, draft, score),
        reply_markup=_keyboard(post_id),
    )
    log.info("draft_sent", draft_num=draft_num, post_id=str(post_id),
             score=round(score.overall, 1) if score else None)


async def _button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    await query.answer()

    action, post_id_str = query.data.split(":", 1)
    post_id = UUID(post_id_str)
    chat_id = query.message.chat.id

    if action == "approve":
        update_post_status(settings.db_path, post_id, "approved")
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(chat_id=chat_id, text="✅ Approved.")
        log.info("draft_approved", post_id=str(post_id))

        # Schedule to Typefully if key is configured
        post = get_post(settings.db_path, post_id)
        if post:
            draft_id = await schedule_post(post.body, settings.typefully_api_key)
            if draft_id:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"📅 Scheduled to Typefully (id: {draft_id})",
                )

    elif action == "edit":
        _pending[chat_id] = ("awaiting_edit", post_id)
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Send me your edited version.",
        )
        log.info("draft_edit_requested", post_id=str(post_id))

    elif action == "reject":
        _pending[chat_id] = ("awaiting_rejection", post_id)
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Rejection reason? (or send 'skip')",
        )
        log.info("draft_reject_requested", post_id=str(post_id))


def _strip_draft_header(text: str) -> str:
    """Remove the Telegram header block if the user accidentally pastes the whole message."""
    if not text.startswith("──"):
        return text
    # Header ends after the blank line that separates it from the post body
    parts = text.split("\n\n", 1)
    return parts[1].strip() if len(parts) > 1 else text


async def _text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return
    chat_id = update.message.chat_id
    if chat_id not in _pending:
        return

    state, post_id = _pending.pop(chat_id)
    text = _strip_draft_header(update.message.text.strip())

    if state == "awaiting_edit":
        update_post_body(settings.db_path, post_id, text)
        update_post_status(settings.db_path, post_id, "approved")
        await update.message.reply_text("✅ Saved and approved.")
        log.info("draft_edited_approved", post_id=str(post_id))

        # Schedule edited version to Typefully
        draft_id = await schedule_post(text, settings.typefully_api_key)
        if draft_id:
            await update.message.reply_text(f"📅 Scheduled to Typefully (id: {draft_id})")

    elif state == "awaiting_rejection":
        reason = "" if text.lower() == "skip" else text
        update_post_status(settings.db_path, post_id, "rejected")
        await update.message.reply_text("❌ Rejected.")
        log.info("draft_rejected", post_id=str(post_id), reason=reason)


def build_app(
    post_init: Callable[[Application[Any, Any, Any, Any, Any, Any]], Coroutine[Any, Any, None]] | None = None,
) -> Application[Any, Any, Any, Any, Any, Any]:
    builder = Application.builder().token(settings.telegram_bot_token)
    if post_init is not None:
        builder = builder.post_init(post_init)
    app: Application[Any, Any, Any, Any, Any, Any] = builder.build()
    app.add_handler(CallbackQueryHandler(_button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text_handler))
    return app
