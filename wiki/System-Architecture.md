# System Architecture

The daily pipeline runs start-to-finish without manual input. Here is exactly what happens, in order, from the launchd trigger to a post sitting in Typefully's queue.

---

## The 9am trigger

A launchd plist fires `uv run python -m src.cli run-daily` at 07:00 local time (configurable in `config.yaml` under `schedule.daily_run_time`). No flags. The system picks its own angle from the news feed. If the IdeatorAgent returns nothing — no news, no relevant angles above the 0.5 threshold — the process exits with a log warning and a Telegram alert. Animesh can then rerun manually with `--idea` or `--topic`/`--sub-topic` to force a specific direction.

The auto-exit timer is set to 4 hours by default (`--timeout 4`). If Animesh does not respond on Telegram within that window, the bot sends itself `SIGTERM` via `os.kill(os.getpid(), signal.SIGTERM)`. This ensures that tomorrow's launchd run fires cleanly rather than colliding with a stuck polling loop from the day before.

---

## Pipeline overview

```
launchd (07:00)
    │
    ▼
[1] News ingestion          feedparser hits 5 RSS feeds
    │                       dedup by URL-hash UUID
    │                       store new rows in news_items table
    ▼
[2] IdeatorAgent            loads 40 most recent news_items (48h window)
    │                       loads 15 most recent non-rejected posts
    │                       computes lane targets from topics.yaml weights
    │                       renders ideator.md → claude-haiku-4-5
    │                       returns RankedAngle list, sorted by relevance_score
    ▼
[3] Top angle selection     angles[0] — the highest-scored angle
    │
    ▼
[4] WriterAgent             loads voice_guide.md
    │                       Chroma vector lookup → up to 5 similar past posts
    │                       renders writer.md → claude-opus-4-7
    │                       returns 2 DraftPost variants (body, hook, format, rationale)
    ▼
[5] CriticAgent × 2         renders critic.md for each draft → claude-haiku-4-5
    │                       returns CriticScore (hook, voice, argument, hygiene, 1-10 each)
    │                       computes overall = mean of 4 dimensions
    ▼
[6] DB persistence          cli.py orchestrator inserts each draft as Post(status="draft")
    │                       agents did NOT write to DB — they returned Pydantic models
    ▼
[7] Telegram delivery       send_draft() sends each draft with score header
    │                       inline keyboard: ✅ Approve / ✏️ Edit / ❌ Reject
    │                       bot enters run_polling() — blocks until action or timeout
    ▼
[8] HITL decision
    ├── Approve → update_post_status(post_id, "approved")
    │             schedule_post(body) → Typefully next-free-slot
    │
    ├── Edit    → bot asks for new text
    │             update_post_body() + update_post_status("approved")
    │             schedule_post() → Typefully
    │
    └── Reject  → bot asks for optional reason
                  update_post_status("rejected")
                  reason logged, not stored in DB (yet)
```

---

## Step 1: News ingestion

`src/inputs/news.py` fetches five RSS feeds configured in `config.yaml`:

| Feed name | Source |
|---|---|
| `et_tech` | Economic Times Tech |
| `yourstory` | YourStory |
| `inc42` | Inc42 |
| `techcrunch_ai` | TechCrunch AI |
| `hacker_news_top` | HN frontpage via hnrss.org |

Each entry is parsed into a `NewsItem`. The `id` is a deterministic UUID derived from `hashlib.md5(url.encode())`. This means the same article fetched on two different runs produces the same UUID — so `INSERT OR IGNORE` in SQLite is the dedup mechanism. No separate seen-URLs table, no timestamp comparison. Dedup is idempotent.

Summary is truncated at 500 characters (the RSS description tag, which varies by feed). No full-text fetch at ingestion time — the Ideator works from titles and summaries only.

`fetch_and_store()` returns the count of newly inserted rows. This is logged with `structlog` as `news_ingestion_done`.

---

## Step 2: Ideation

`IdeatorAgent.run()` receives an `IdeatorInput` (default: `news_hours=48`, `refresh_news=True`, `max_angles=10`).

Three things are loaded before the prompt is rendered:

1. **News items** — up to 40 items from the last 48 hours, newest first.
2. **Recent posts** — up to 15 non-rejected posts from `brain.db`, used for theme avoidance. The Ideator is told not to repeat lane/sub_topic combinations already in this list.
3. **Lane targets** — computed from `data/topics.yaml`. The weights are: `ai_for_pms` 45%, `pm_craft` 35%, `healthcare_ai` 20%. For a request of 10 angles, that is roughly 5 ai_for_pms, 4 pm_craft, 1 healthcare_ai. This is a hard constraint in the prompt — if the model over-indexes on one lane, it is told to replace the weakest angles with alternatives from underrepresented lanes.

`healthcare_ai` angles are only valid if the news item is directly about Indian healthcare, pharma, or ePharmacy. The prompt explicitly prohibits manufacturing healthcare takes from general AI news.

The model returns a JSON array of `RankedAngle` objects. These are sorted by `relevance_score` descending. Anything below 0.5 is excluded at the prompt level (the model is instructed not to include them). The Python parser takes the top `max_angles` after sorting.

---

## Step 3: Top angle selection

`run_daily` in `src/cli.py` takes `ideator_result.angles[0]` — the highest-scored angle. This angle's `topic_lane`, `sub_topic`, and `context_note` are passed to the Writer.

There is no consensus mechanism or secondary scoring at this stage. The Ideator's own `relevance_score` is the ranking signal. This is intentional — adding a secondary filter here before the full Writer pipeline is ready would be premature optimization. Revisit in Phase 3 when engagement data is flowing.

---

## Step 4: Writing

`WriterAgent.run()` receives `WriterInput(topic_lane, sub_topic, context_note)`.

Before calling the LLM:
- `load_voice_guide()` reads `data/voice_guide.md` and returns it as a formatted string for prompt injection.
- `find_similar_posts()` queries the DB for posts in the same `topic_lane`, preferring `sub_topic` matches. Up to 5 posts are returned, formatted as `[Hook: '...' | Format: ...]` blocks separated by `---`. These are the Writer's style reference — real posts Animesh has written, with engagement data that the voice guide's format rankings were derived from.

The Writer uses `claude-opus-4-7`. Temperature is inherited from `config.yaml` (`agent_defaults.temperature`, currently 0.7). Note: Claude 4.x models (opus-4, sonnet-4, haiku-4) have deprecated the `temperature` parameter — `call_llm()` detects the model prefix and omits the parameter for these models.

Two drafts are required. The prompt enforces that the two drafts must be meaningfully different — different hook type or different format, not paraphrases.

---

## Step 5: Critique

`CriticAgent.run()` is called once per draft. It receives the `DraftPost` and renders `critic.md` with `draft_format` and `draft_body`.

The Critic uses `claude-haiku-4-5` at temperature 0.0 (deterministic). It returns:

| Dimension | What it measures |
|---|---|
| `hook_strength` | Is this one of the three valid hook types (confession, knowing question, grounded scene)? |
| `voice_match` | First person, specific numbers, PM lens, ends with a concrete answerable question? |
| `argument_quality` | Concrete and specific — not generic PM wisdom that applies to anyone? |
| `hygiene` | No hashtags, 150-300 words, no forbidden phrases, no vague closing question? |

`overall` is a `@computed_field` — the arithmetic mean of the four dimensions. It is not stored in the DB directly; it is computed at read time from the four stored integers.

The Critic's `verdict` is a single sentence: main strength, then main weakness or what to fix.

---

## Step 6: DB persistence

The orchestrator in `src/cli.py` is the only writer to the DB. Agents return Pydantic models. This is the contract that keeps agents testable and composable.

Each `DraftPost` + its `WriterOutput` metadata is assembled into a `Post` schema object and inserted via `brain/posts.py::insert_post()`. Status is `"draft"` at insertion. The `prompt_version` field comes from the prompt's YAML frontmatter — this is how you trace which prompt version generated a given post, even months later.

---

## Step 7: Telegram delivery

`send_draft()` sends each post as a Telegram message with a score header:

```
── DRAFT 1 [framework] ──
Score 7.8/10 · Hook 8 · Voice 7 · Sub 8 · Clean 8
"Strong PM lens but the hook opens with a thesis — rephrase as a question or scene"

[post body]

[✅ Approve]  [✏️ Edit]  [❌ Reject]
```

The bot enters `run_polling()` and stays alive until an action is received or the 4-hour timeout fires.

---

## Step 8: HITL loop

All state is in-memory during the bot session. `_pending: dict[int, tuple[str, UUID]]` maps `chat_id` to `(state, post_id)`. This works because the system is single-user.

**Approve:** `update_post_status(post_id, "approved")` then `schedule_post(body, api_key)` → Typefully API creates a draft in the next free slot for the connected LinkedIn account.

**Edit:** Bot transitions to `"awaiting_edit"` state. The next message from Animesh replaces the post body (`update_post_body()`), sets status to `"approved"`, and schedules to Typefully. The bot also strips its own header block if Animesh accidentally pastes the whole message.

**Reject:** Bot transitions to `"awaiting_rejection"`. The next message is logged as a rejection reason. Status is set to `"rejected"`. Rejected posts are excluded from future IdeatorAgent theme-avoidance lists.

---

## Key interfaces

**All agents return Pydantic models.** No agent writes to the database directly. The orchestrator (`src/cli.py::run_daily`) owns all persistence. This means any agent can be tested in isolation by mocking its input model — no DB setup required.

**All prompts are .md files with YAML frontmatter.** No prompt text is hardcoded in Python. The `prompt_version` from frontmatter is logged with every agent run and stored in the `posts` table. Regressions are traceable to the exact prompt version.

**`call_llm()` in `src/llm.py` is the single Anthropic client wrapper.** All agents go through it. It handles tenacity retry (3 attempts, exponential backoff: 1s/4s/16s), structlog logging of input hash, output hash, tokens, and latency, and the Claude 4.x temperature deprecation workaround.
