# Human-in-the-Loop Design

## Why HITL at all

My name is on every post. The Critic scores a draft 8.5/10. That score is based on a prompt calibrated against 47 seed posts and a voice guide I wrote by hand. It has not been validated against what actually performs on LinkedIn. A score of 8.5 might predict strong engagement, or it might not — there is no data yet to know.

Full automation before that validation loop closes is brand risk. One post that sounds off — slightly too clever, slightly too formal, wrong cultural register — does more damage than a week of missed posts does. The HITL loop exists to prevent that until the Critic earns the right to be trusted.

---

## Design principle 1: Approval should take under 30 seconds

If reviewing a draft takes longer than 30 seconds, the draft is wrong — not the approval UX.

The Telegram message is designed for a fast decision. The score line (`Score 7.8/10 · Hook 8 · Voice 7 · Sub 8 · Clean 8`) gives a quantitative read in one glance. The Critic's `verdict` (a single sentence in quotes below the score line) gives the qualitative override. The post body follows immediately. Three buttons. Done.

If I find myself re-reading a draft multiple times before deciding, the Writer or Critic is generating ambiguous output that should be fixed upstream. The right response is to reject, note why, and fix the prompt — not to spend more time deciding.

---

## Design principle 2: The edit flow handles 80% of "close but not quite" cases

Most drafts that aren't approved outright need a single paragraph tweaked, a hook rewritten, or one sentence cut. Tapping ✏️ Edit, making the change in the Telegram message field, and sending it handles all of that in the same interface.

The bot's `_text_handler` in `src/outputs/telegram_bot.py` calls `update_post_body()` and `update_post_status(..., "approved")` as a single atomic operation, then immediately schedules to Typefully. There is no separate confirmation step — edited means approved.

One safety detail: `_strip_draft_header()` detects if the full Telegram message was accidentally copied (the one starting with `── DRAFT`) and strips the header, saving only the post body.

---

## Design principle 3: Rejection friction should be zero

The bot prompts "Rejection reason? (or send 'skip')". The reason is optional — sending `skip` is a full, valid rejection. The reason is logged to `logs/agent.log` via structlog under event `draft_rejected`.

Friction on rejection trains bad behavior: if rejecting is annoying, I reject less, which means worse signal in the DB and less pressure on the Writer to improve. The rejection path is one tap + one message (or one tap + the word "skip").

---

## Design principle 4: The bot exits cleanly so tomorrow's run isn't blocked

Telegram's Bot API enforces a hard constraint: only one polling instance per bot token at a time. If yesterday's process is still running when launchd fires at 9am, the new process immediately gets a `Conflict` error and fails.

The launchd plist sends SIGTERM to the process after the session ends. The `python-telegram-bot` Application handles SIGTERM cleanly — it drains in-flight handlers and exits. The 4-hour window is the practical outer bound: if no Telegram interaction has happened by 1pm, the process exits to ensure tomorrow's 9am run is unblocked.

If SIGTERM doesn't fire cleanly for any reason, the fix is manual:

```bash
pkill -f "agent run-daily"
```

---

## Design principle 5: Conflict error means old process still running

This error message in the logs:

```
telegram.error.Conflict: Conflict: terminated by other getUpdates request
```

means exactly one thing: a previous `agent run-daily` process is still alive. Fix:

```bash
pkill -f "agent run-daily"
# then re-trigger
uv run --system-certs python scripts/run_daily.py
```

---

## The future state: Phase 4 auto-approval

The current gate is: every draft goes to Telegram. No exceptions.

Phase 4 adds auto-approval for drafts that pass both independent gates simultaneously:

1. Critic overall score >= `auto_approve_threshold` (currently `8.5` in `config.yaml`)
2. EvaluatorAgent voice-match score >= `8.0` (the separate eval suite in `tests/test_voice_match.py`)

Both gates must pass. A draft that scores 9.2 overall but 7.8 on voice match does not auto-approve — voice fidelity is the single hardest thing to get right and the single most important.

The threshold of 8.5 is not currently calibrated against real engagement data. It will be recalibrated at the start of Phase 3 when the Analyst agent begins correlating Critic scores against actual impressions and reactions. Until that calibration happens, the number is a guess, and auto-approval stays off.

The trigger for switching auto-approve on is not a timeline ("after 6 weeks") — it is a data condition: Critic scores correlate with engagement at r > 0.6 over a minimum of 20 posted samples.
