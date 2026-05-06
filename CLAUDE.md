# CLAUDE.md — LinkedIn Content Agent

> Context file for Claude Code. Read this before any task. Update the **Status Log** at the bottom as work completes.

---

## 1. What we're building

A multi-agent system that runs my (Animesh's) LinkedIn presence with progressively decreasing human involvement.

**End state (month 6):** I write a 5-min voice note in the morning. By evening, posts are drafted, critiqued, scheduled. Weekly, the system analyzes engagement and rewrites its own strategy. I approve only flagged-low-confidence drafts.

**Day 1 state:** Human-in-the-loop on every post. I approve via Telegram before anything ships.

**Why this project:** Learn agentic systems by building one I'll actually use. Same architectural patterns will inform a future "PM Operating System" product.

---

## 2. Product principles (non-negotiable)

1. **My name is on every post.** Quality > volume > automation. Bad content posted consistently damages the brand faster than no content builds it.
2. **The Brand Brain is the moat, agents are interchangeable.** Optimize the memory layer; LLMs and agent frameworks will change.
3. **Progressive autonomy.** The agent earns trust per dimension (voice match, factual accuracy, hook quality). Never a blanket "yes auto-post everything."
4. **Voice fidelity > clever output.** A correct-sounding mediocre post beats a brilliant post that doesn't sound like me.
5. **Real feedback loops only.** Don't build a strategist agent until there's real engagement data flowing in. No simulated learning.

---

## 3. Architecture overview

```
┌─────────────────────────────────────────────────────────────┐
│                      BRAND BRAIN                            │
│  SQLite (posts, engagement, experiments) + voice_guide.md   │
│  + topics.yaml + strategy_current.md                        │
└─────────────────────────────────────────────────────────────┘
        ▲                ▲                ▲
        │                │                │
   ┌────┴────┐      ┌────┴─────┐    ┌─────┴─────┐
   │ INPUTS  │      │  AGENTS  │    │ FEEDBACK  │
   │         │      │          │    │           │
   │ voice   │ ───► │ ideator  │    │ analyst   │
   │ notes   │      │ writer   │    │ (weekly)  │
   │ reading │      │ critic   │    │           │
   │ news/   │      │strategist│    │ strategist│
   │ events  │      └──────────┘    │ (weekly)  │
   │ work    │           │          └───────────┘
   └─────────┘           ▼
                    ┌─────────┐
                    │ HITL via│
                    │ Telegram│
                    └────┬────┘
                         ▼
                    ┌─────────┐
                    │Typefully│
                    │   API   │
                    └─────────┘
```

### Agents (each is a single Python module, callable independently)

| Agent | Frequency | Input | Output |
|---|---|---|---|
| **Ideator** | daily | voice notes, reading queue, news/events feed, current strategy, brand brain | 5-10 ranked post angles with source tag (`voice`, `reading`, `news`) |
| **Writer** | daily | top angle(s), voice guide, similar past posts | 2 full draft variants |
| **Critic** | daily | drafts, voice guide, recent posts | scored drafts + reject/approve |
| **Strategist** | weekly | analyst report, brand brain | next week's `strategy_current.md` |
| **Analyst** | weekly | engagement data, posts table | weekly report + DB updates |

### Inputs

- **Voice notes** — daily 5-min ramble. Whisper transcribes. Highest-leverage input.
- **Reading capture** — Telegram bot forward / email-to-inbox. Stored as raw text + URL.
- **News/events feed** — RSS poll (every 6h) across curated sources: ET Tech, YourStory, Inc42, TechCrunch AI, Hacker News. Feed list lives in `config.yaml`. Ideator scores each item for relevance to active topic lanes before using. This is the trigger for time-sensitive "strategy teardown" posts (empirically the highest-reach format — 228K impressions vs 5K average).
- **Work artifacts** — manual paste/upload of Granola transcripts, sanitized PRDs, Mixpanel investigations.

### Output channels

- **Telegram bot** — daily draft review, approval flow.
- **Typefully API** — scheduled posting on approval.

---

## 4. Tech stack (locked in for v1)

- **Language:** Python 3.11+
- **LLM:** Anthropic SDK directly (`claude-opus-4-7` for Writer/Strategist, `claude-haiku-4-5` for Critic/utility). No LangChain, no CrewAI, no LangGraph for v1 — bare SDK + own glue. Re-evaluate at month 3.
- **DB:** SQLite (file: `data/brain.db`). Schema migrations via plain `.sql` files in `migrations/`.
- **Vector store:** Chroma (local, file-backed). Only for "find similar past posts" lookups.
- **Transcription:** OpenAI Whisper API (or local `whisper.cpp` if cost matters).
- **HITL:** `python-telegram-bot` library.
- **Scheduling:** `apscheduler` for in-process cron. No Celery/Redis for v1.
- **Posting:** Typefully API (https://typefully.com/api).
- **Config:** `.env` for secrets, `config.yaml` for tunables. Never hardcode.
- **News ingestion:** `feedparser` for RSS (no API key needed). Feed URLs configured in `config.yaml`. Deduplicated by URL hash. Upgrade to NewsAPI only if RSS coverage proves insufficient — defer that decision.
- **Logging:** `structlog` → JSON to `logs/agent.log`. Every agent run logs input hash, model, tokens, latency, output hash.
- **Hosting:** Local laptop + cron for month 1. Move to Modal or a $5 droplet when always-on is needed.

---

## 5. Repository structure (prescriptive)

```
linkedin-agent/
├── CLAUDE.md                    # this file
├── README.md                    # human-facing setup
├── .env.example
├── config.yaml
├── pyproject.toml               # use uv or poetry, not bare pip
├── data/
│   ├── brain.db                 # gitignored
│   ├── voice_guide.md           # tracked in git
│   ├── topics.yaml              # tracked in git
│   ├── strategy_current.md      # gitignored (regenerated)
│   └── seed_posts/              # raw exports, gitignored
├── migrations/
│   └── 001_init.sql
├── src/
│   ├── __init__.py
│   ├── brain/                   # the memory layer
│   │   ├── db.py
│   │   ├── posts.py
│   │   ├── voice.py
│   │   └── similarity.py
│   ├── agents/
│   │   ├── base.py              # shared Agent class, prompt loader
│   │   ├── ideator.py
│   │   ├── writer.py
│   │   ├── critic.py
│   │   ├── strategist.py
│   │   └── analyst.py
│   ├── inputs/
│   │   ├── voice_notes.py
│   │   ├── reading.py
│   │   ├── news.py              # RSS fetch, dedup, relevance pre-score
│   │   └── work_artifacts.py
│   ├── outputs/
│   │   ├── telegram_bot.py
│   │   └── typefully.py
│   ├── llm.py                   # single Anthropic client wrapper
│   ├── config.py                # pydantic settings
│   ├── schemas.py               # pydantic models for all data
│   └── cli.py                   # typer-based CLI: `agent ideate`, `agent run-daily`
├── prompts/                     # all prompts live here as .md files
│   ├── ideator.md
│   ├── writer.md
│   ├── critic.md
│   ├── strategist.md
│   └── analyst.md
├── tests/
│   ├── test_brain.py
│   ├── test_voice_match.py      # voice-fidelity eval suite
│   └── fixtures/
└── scripts/
    ├── import_linkedin_export.py
    ├── run_daily.py
    └── run_weekly.py
```

---

## 6. Coding standards

### General
- Python 3.11+, type hints everywhere. `mypy --strict` should pass.
- `ruff` for lint + format. Config in `pyproject.toml`. Run pre-commit.
- Use `pydantic` v2 for all data models. No raw dicts crossing module boundaries.
- Use `pathlib.Path`, never string paths.
- Use `uv` for dependency management.

### Naming
- Modules: `snake_case.py`. Single responsibility.
- Classes: `PascalCase`. Agents end in `Agent` (e.g., `WriterAgent`).
- Functions: `snake_case`, verb-first (`generate_drafts`, not `drafts`).
- Constants: `UPPER_SNAKE`. Live in `config.py` or module top.
- DB tables: `snake_case` plural (`posts`, `engagement_snapshots`).

### Prompts
- All prompts live in `prompts/*.md` — never hardcoded in Python.
- Each prompt file has YAML frontmatter: `model`, `temperature`, `max_tokens`, `version`.
- Prompts use `{variable}` placeholders. Render via a single `render_prompt(name, **vars)` util.
- Version prompts. When we change one, bump the version in frontmatter and log it with the run.

### Agents
- Every agent inherits from `agents/base.py::Agent`.
- Single public method: `run(input: InputModel) -> OutputModel`. No side-channel state.
- Agents do NOT write to the DB directly — they return Pydantic models. The orchestrator persists.
- Agents log: input summary, prompt version, model, tokens, latency, output summary.
- Agents are deterministic given (input, prompt version, model, temperature). Temperature 0.7 default; lower for Critic.

### Error handling
- Anthropic API calls: retry with exponential backoff (3 tries, 1s/4s/16s). Use `tenacity`.
- On final failure, log + raise a typed exception (`AgentError`, `BrainError`, etc.). Never swallow.
- Telegram bot: catch all exceptions at handler boundary, log, send "something broke" to me.
- Daily/weekly cron jobs: wrap in try/except, log failure, send Telegram alert. Never crash silently.

### Testing
- `pytest`. Aim for tests on `brain/` and prompt rendering. Skip exhaustive agent-output tests (LLMs are stochastic) — use a small **voice-match eval suite** instead (see §8).
- Fixtures in `tests/fixtures/` — sample posts, voice guide, engagement data.

### Git
- Conventional commits (`feat:`, `fix:`, `chore:`). One concern per commit.
- Never commit `.env`, `data/brain.db`, `data/seed_posts/`, `logs/`.

---

## 7. Data models (canonical — define in `src/schemas.py`)

```python
# Core entities. Keep these stable; migrations are painful.

class Post:
    id: UUID
    created_at: datetime
    posted_at: datetime | None
    status: Literal["draft", "approved", "scheduled", "posted", "rejected"]
    body: str
    hook: str                  # first 2 lines, the scroll-stopper
    topic_lane: Literal["ai_for_pms", "pm_craft", "healthcare_ai"]
    sub_topic: str
    format: Literal["story", "framework", "contrarian", "list", "build_log", "question"]
    source_input_ids: list[UUID]   # which voice notes / reading items fueled this
    prompt_version: str
    model: str

class EngagementSnapshot:
    post_id: UUID
    captured_at: datetime
    impressions: int | None
    reactions: int
    comments: int
    reposts: int
    profile_views_delta: int | None

class VoiceGuide:                 # loaded from voice_guide.md
    sound_like: list[str]
    dont_sound_like: list[str]
    authority_topics: list[str]
    example_sentences: list[str]
    forbidden_phrases: list[str]  # "delve", "tapestry", "in today's fast-paced world", etc.

class NewsItem:
    id: UUID
    fetched_at: datetime
    source: str                 # feed name, e.g. "et_tech", "hacker_news"
    url: str                    # deduplicated by hash of this
    title: str
    summary: str                # first 500 chars of description tag
    relevance_score: float | None   # set by Ideator; None until scored
    used_in_post_ids: list[UUID]    # backfilled when a post cites this item

class StrategyDoc:                # generated weekly into strategy_current.md
    week_of: date
    lane_mix: dict[str, float]    # {"ai_for_pms": 0.6, ...}
    target_frequency: int          # posts per week
    preferred_formats: list[str]
    preferred_post_times: list[str]
    experiments: list[str]         # "try one contrarian post mid-week"
    avoid: list[str]               # "no list-heavy posts, tanked last week"
    rationale: str
```

---

## 8. Voice-match eval suite

The single most important piece of infrastructure beyond the brain itself.

- `tests/test_voice_match.py` — pytest suite that runs the Writer agent on a fixed set of 5 prompts, then uses Claude (separate call) to score each output 1-10 on:
  - voice match to the guide
  - hook strength
  - originality vs seed posts
  - LinkedIn-format hygiene
- Run before every prompt-version bump. If average score drops > 0.5, don't ship.
- Results logged to `data/eval_history.jsonl`.

---

## 9. Roadmap (phases)

### Phase 1 (Weeks 1-3): Voice + Ideator + Writer + manual review
- Brand brain stood up with seed data
- Telegram bot delivers 2 drafts/day for review
- I copy-paste approved posts to LinkedIn manually
- **Exit criteria:** ≥80% of drafts approved with only minor edits

### Phase 2 (Weeks 4-6): Critic + Typefully scheduling
- Critic agent live with score thresholds
- Approved drafts auto-schedule via Typefully
- **Exit criteria:** posting 3+/week, <15 min/day on the system

### Phase 3 (Weeks 7-12): Analyst + Strategist + closed loop
- Engagement ingestion working (path TBD: Taplio API / scraping / manual export)
- Weekly strategy regenerated with visible WoW evolution
- **Exit criteria:** strategy doc changes meaningfully week-over-week, justified by data

### Phase 4 (Months 4-6): Reduce HITL, add experiments, voice notes
- Voice-note morning input pipeline live
- Auto-approve high-confidence Critic-passed drafts
- Experiments module: deliberate format/hook trials with measurement
- **Exit criteria:** I spend <30 min/week, system posts 4+/week, engagement trending up

---

## 10. Open decisions (defer until needed)

- Engagement data source: Taplio (paid, clean) vs LinkedIn analytics export (manual) vs scraping (fragile). Decide at start of Phase 3.
- Whether to add comment-engagement agent (replies to comments on my posts) — not in v1 scope.
- Whether to extract this as a product for other PMs — revisit after 3 months of personal use.
- Multi-platform (X/Twitter, Substack) — out of scope for v1.

---

## 11. How Claude Code should work in this repo

1. **Always read this file first.** Re-read it when starting a new session.
2. **Check the Status Log (§13)** for what's done and what's next.
3. **One task per session.** Don't blur scope. If a task spawns sub-tasks, surface them and ask.
4. **Update the Status Log** at the end of every completed task. Move from "Next" → "Done" with a one-line note.
5. **Propose, don't presume.** When a decision isn't covered here, ask. Don't invent product behavior.
6. **Run tests before declaring done.** `pytest` + `ruff check` + `mypy --strict` must pass.
7. **Prompts are product.** When editing a prompt, bump its version, run the voice-match eval, summarize the diff.

---

## 12. Animesh-specific context

- Group PM at Tata 1mg, leading ePharmacy & Generics
- Comfortable with: product strategy, multi-agent system design (built several internal at 1mg), Mixpanel/Atlassian/Granola/Drive/Gmail integrations
- Coding posture: medium-touch — Claude Code does most of it, I direct
- Time budget: ~2 hours/day, 7 days/week
- Voice profile (will refine): data-backed, decision-ready, structured, prefers specific recommendations to vague guidance
- Will NOT build in public — the agent ships posts, but the system itself stays private until productized

---

## 13. Status Log

> Update this section as work completes. Format: `[YYYY-MM-DD] task — short note`.

### ✅ Done

- `[2026-04-30] CLAUDE.md created` — initial scope, architecture, standards, roadmap locked in.
- `[2026-04-30] news/events input added` — RSS feed input incorporated into Ideator, §3/§4/§5/§7 updated; feedparser chosen, feed list goes in config.yaml.
- `[2026-05-01] voice_guide.md + topics.yaml enriched to v1` — full 47-post corpus analysis. 9 formats ranked by reach, Hindi dialogue pattern added, resource roundup retired, healthcare_ai flagged as aspirational (zero historical posts).
- `[2026-05-02] Task 1 complete` — seed material reviewed and approved by Animesh.
- `[2026-05-02] Task 2 complete` — uv + Python 3.13, pyproject.toml, ruff/mypy config, full directory structure, src/config.py, .env.example, config.yaml, pre-commit hooks. Exit criterion passes.
- `[2026-05-02] Task 3 complete` — 001_init.sql (posts, engagement_snapshots, news_items), db.py + posts.py with full CRUD, import script ingested 47 seed posts. 10/10 tests pass, ruff clean.
- `[2026-05-01] seed posts saved` — 47 posts + engagement data from Content brain.xlsx → `data/seed_posts/content_brain.md`. LinkedIn native export not available; this xlsx is the source of truth.
- `[2026-05-03] Task 4 complete` — llm.py (retry, structured logging), prompts/writer.md v1, base.py Agent class, WriterAgent, CLI `agent write`. Fixed corporate SSL proxy via truststore + temperature deprecation for Claude 4.x models.
- `[2026-05-03] Task 5 complete` — EvaluatorAgent (haiku judge, voice_eval.md prompt), 5 fixed eval prompts, pytest --run-eval gate, data/eval_history.jsonl. Baseline: overall 8.35 (VM=7.90, HS=8.80, OR=7.60, HY=9.10). Regression threshold −0.5.
- `[2026-05-03] Task 6 complete` — Telegram HITL loop live. telegram_bot.py (✅/✏️/❌ inline buttons, pending-state handler), run_daily.py script + agent run-daily CLI. Exit criterion passed: approved 2 drafts via Telegram, DB shows status=approved.
- `[2026-05-03] AngleMapper live` — free-text --idea arg added to run-daily. Haiku maps idea → topic_lane + sub_topic + context_note. Old --topic/--sub-topic still works. Echo shows mapping before generating.
- `[2026-05-03] Phase 2 started` — CriticAgent (haiku, critic.md v1.0), Typefully stub (wired, skips gracefully until API key set). Pipeline: mapper → writer → critic × 2 → Telegram with score header. Kill old bot with pkill -f "agent run-daily" if Conflict error appears.
- `[2026-05-04] Phase 2 complete` — Critic live, Typefully wired, full pipeline tested end-to-end. Flow: AngleMapper → WriterAgent → CriticAgent × 2 → Telegram HITL → Typefully schedule on approval.
- `[2026-05-05] Task 7 complete` — News feed ingestion + IdeatorAgent live. `src/inputs/news.py` (feedparser, URL-hash dedup, 134 items across 5 feeds on first run). `IdeatorAgent` scores news items against content lanes, returns ranked angles. CLI: `agent fetch-news`, `agent ideate`. `agent run-daily` with no flags now auto-ideates instead of requiring `--idea`.
- `[2026-05-06] Ideator token fix` — raised `ideator_max_tokens` to 4096 in config.yaml; was hitting 2000-token ceiling mid-JSON on first live run.
- `[2026-05-06] Ideator topic diversity fix` — two bugs fixed: (1) recent posts query was filtering `status="posted"` only (1 post visible); changed to `exclude_statuses=["rejected"]` so all 15 recent drafts/approvals are visible. (2) prompt had no lane mix enforcement; now computes lane targets from `topics.yaml` weights and injects as a hard constraint (`{lane_targets}`). Prompt bumped to v1.1.
- `[2026-05-06] Task 8 complete` — Fully automated daily pipeline. `run_daily` now auto-exits via SIGTERM after `--timeout` hours (default 4) so launchd can fire the next day's run without a hung process. launchd plist at `~/Library/LaunchAgents/com.animesh.linkedin-agent.daily.plist` fires at 9am daily, logs to `logs/launchd.log`. Loaded and registered (`state = not running`).

### 🔜 Next (in order)

1. ~~**Task 1 — Gather seed material**~~ ✅ Done — see Status Log.

2. ~~**Task 2 — Project scaffold**~~ ✅ Done — see Status Log.

3. ~~**Task 3 — Brand Brain v0**~~ ✅ Done — see Status Log.

4. ~~**Task 4 — LLM wrapper + first prompt**~~ ✅ Done — see Status Log.

5. ~~**Task 5 — Voice-match eval suite**~~ ✅ Done — see Status Log.

6. ~~**Task 6 — Telegram HITL loop**~~ ✅ Done — see Status Log.

7. ~~**Task 7 — News feed ingestion + Ideator agent**~~ ✅ Done — see Status Log.

8. ~~**Task 8 — Persistent bot service**~~ ✅ Done — see Status Log.

### 🅿️ Parked (revisit later)

- Engagement ingestion (Phase 3)
- Strategist + Analyst (Phase 3)
- Voice notes pipeline (Phase 4)

---

*End of CLAUDE.md*
