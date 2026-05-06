# LinkedIn Content Agent

A multi-agent system that runs a LinkedIn content pipeline end-to-end — ideation, drafting, critique, HITL approval, and scheduled posting — in production daily.

---

## Why I built this

I wanted to learn agentic system design by building something I'd actually use and break. A LinkedIn content pipeline has all the properties that make agents interesting: ambiguous inputs (voice notes, news), hard-to-specify quality constraints (voice fidelity), a real feedback loop (engagement data), and meaningful consequences for getting it wrong — my name is on every post.

The same architecture — a memory layer that compounds, agents that are interchangeable, progressive autonomy earned through measurable trust — is the skeleton of a "PM Operating System" I plan to build for other PMs. This is the first running instance of that pattern, not a demo.

---

## The pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                      BRAND BRAIN                            │
│  SQLite (posts, engagement, news_items) + voice_guide.md    │
│  + topics.yaml + strategy_current.md                        │
└─────────────────────────────────────────────────────────────┘
        ▲                ▲                ▲
        │                │                │
   ┌────┴────┐      ┌────┴─────┐    ┌─────┴─────┐
   │ INPUTS  │      │  AGENTS  │    │ FEEDBACK  │
   │ voice   │ ───► │ ideator  │    │ analyst   │
   │ notes   │      │ writer   │    │ (weekly)  │
   │ reading │      │ critic   │    │ strategist│
   │ news/   │      │strategist│    │ (weekly)  │
   │ events  │      └──────────┘    └───────────┘
   └─────────┘           │
                         ▼
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

At 9am a launchd job fires. It fetches RSS news from five sources (ET Tech, YourStory, Inc42, TechCrunch AI, Hacker News), runs the Ideator agent to surface ranked post angles, runs the Writer agent to produce two draft variants, runs the Critic agent to score each draft on voice match and hook strength, then sends both drafts to Telegram with their scores. One tap to approve (✅), request an edit (✏️), or reject (❌). On approval, the post is auto-scheduled via Typefully and goes live on LinkedIn.

![Draft review](docs/telegram-demo.png)

---

## Key design decisions

- **Brand Brain is the moat, not the agents.** LLMs and orchestration frameworks will keep changing. What compounds is the accumulated voice data, engagement history, and topic context stored in the brain. Agents are interchangeable; the memory layer is not. Every architectural choice prioritizes the brain's durability over agent cleverness.

- **Progressive autonomy, not blanket automation.** The Critic agent gates the pipeline with explicit scores across voice match, hook strength, and originality. Auto-approval will be unlocked per dimension as the system earns trust — not as a single "just post it" flag. Bad content published consistently destroys a brand faster than no content builds it.

- **Voice fidelity as the primary constraint.** A correct-sounding mediocre post beats a brilliant post that doesn't sound like the author. The voice-match eval suite (`tests/test_voice_match.py`) runs the Writer on five fixed prompts, scores each output with a separate Claude judge, and acts as a regression gate — if the average score drops more than 0.5 after a prompt change, the change doesn't ship.

- **Real feedback loops only.** The Strategist and Analyst agents are stubbed but not active. They go live when real engagement data (impressions, reactions, comments) flows in consistently. Building a strategist that optimizes against simulated or estimated data is worse than no strategist at all — it compounds in the wrong direction.

---

## Tech stack

| Component | Tool | Why |
|---|---|---|
| Language | Python 3.13, uv | Modern toolchain, fast dependency resolution |
| LLM — Writer/Strategist | `claude-opus-4-7` | Best reasoning and voice fidelity at higher stakes |
| LLM — Critic/Ideator/utility | `claude-haiku-4-5` | Fast and cheap for scoring and classification tasks |
| LLM client | Anthropic SDK (bare) | No LangChain/CrewAI/LangGraph — own glue, re-evaluate at month 3 |
| Database | SQLite | Zero infrastructure, file-backed, good enough for one user |
| Vector store | Chroma (local) | Similar-post lookup for originality checks |
| RSS ingestion | feedparser | No API key, covers all five target sources |
| HITL | python-telegram-bot | Low-friction mobile approval flow |
| Scheduling (post) | Typefully API | Native LinkedIn scheduling, cleaner than direct API |
| Scheduling (jobs) | apscheduler + launchd | In-process cron, no Redis/Celery for v1 |
| Data models | pydantic v2 | Strict typing across all module boundaries |
| Logging | structlog → JSON | Every agent run logs input hash, model, tokens, latency, output hash |
| Lint / types | ruff + mypy --strict | Enforced via pre-commit |

---

## Project structure

```
linkedin-agent/
├── CLAUDE.md                    # architecture, decisions, status log
├── config.yaml                  # tunables: feed URLs, schedule times, thresholds
├── .env.example                 # secrets template
├── pyproject.toml
├── data/
│   ├── brain.db                 # gitignored — SQLite brain
│   ├── voice_guide.md           # tracked — tone, forbidden phrases, example sentences
│   ├── topics.yaml              # tracked — active topic lanes and sub-topics
│   └── eval_history.jsonl       # voice-match eval scores over time
├── migrations/
│   └── 001_init.sql             # posts, engagement_snapshots, news_items
├── prompts/                     # all prompts as .md with YAML frontmatter
│   ├── writer.md
│   ├── critic.md
│   ├── ideator.md
│   ├── voice_eval.md
│   └── strategist.md
├── src/
│   ├── agents/
│   │   ├── base.py              # shared Agent class, prompt loader, structured logging
│   │   ├── ideator.py           # angles from news + reading queue
│   │   ├── writer.py            # 2 draft variants
│   │   ├── critic.py            # scores drafts, gates pipeline
│   │   ├── mapper.py            # free-text idea → topic_lane + sub_topic
│   │   ├── evaluator.py         # voice-match judge (eval suite only)
│   │   ├── strategist.py        # weekly strategy (Phase 3)
│   │   └── analyst.py           # weekly engagement analysis (Phase 3)
│   ├── brain/
│   │   ├── db.py                # connection, migrations runner
│   │   ├── posts.py             # CRUD for posts + engagement snapshots
│   │   ├── similarity.py        # Chroma lookups for similar past posts
│   │   └── voice.py             # load and parse voice_guide.md
│   ├── inputs/
│   │   ├── news.py              # RSS fetch, URL dedup, relevance pre-score
│   │   ├── reading.py           # reading queue ingestion
│   │   ├── voice_notes.py       # Whisper transcription
│   │   └── work_artifacts.py    # manual paste / Granola transcripts
│   ├── outputs/
│   │   ├── telegram_bot.py      # inline buttons, approval state machine
│   │   └── typefully.py         # schedule on approval
│   ├── llm.py                   # Anthropic client with retry + logging
│   ├── config.py                # pydantic settings, loaded from .env + config.yaml
│   ├── schemas.py               # canonical pydantic models: Post, NewsItem, etc.
│   └── cli.py                   # typer CLI: agent ideate, agent write, agent run-daily
├── scripts/
│   ├── run_daily.py             # orchestrates full daily pipeline
│   ├── run_weekly.py            # analyst + strategist
│   └── import_linkedin_export.py
└── tests/
    ├── test_brain.py
    ├── test_voice_match.py      # voice-match eval suite, --run-eval flag
    └── fixtures/
```

---

## Quick start

```bash
# 1. Clone and install
git clone https://github.com/animeshjain/linkedin-content-agent.git
cd linkedin-content-agent
uv sync

# 2. Configure secrets
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TYPEFULLY_API_KEY

# 3. Set up your voice guide
cp data/voice_guide.example.md data/voice_guide.md
# Edit voice_guide.md — this is the most important file in the repo

# 4. Run database migrations
uv run python -m src.brain.db

# 5. Run the daily pipeline with a seed idea
uv run agent run-daily --idea "why most AI product roadmaps are theatre"

# 6. Or let the Ideator surface angles from the news feed
uv run agent ideate
```

The pipeline will generate two drafts and send them to your Telegram bot for approval.

---

## Wiki

Full documentation lives in the [GitHub Wiki](../../wiki). Key pages:

- [**Voice Guide Setup**](../../wiki/Voice-Guide-Setup) — how to write a voice guide that actually constrains the writer
- [**Adding RSS Feeds**](../../wiki/Adding-RSS-Feeds) — configuring sources in `config.yaml`, dedup behavior
- [**Prompt Versioning**](../../wiki/Prompt-Versioning) — frontmatter schema, how to bump a version, running the eval gate
- [**Telegram Bot Setup**](../../wiki/Telegram-Bot-Setup) — BotFather setup, getting your chat ID, approval flow walkthrough
- [**Typefully Integration**](../../wiki/Typefully-Integration) — API key, scheduling behavior, what happens on rejection
- [**launchd Scheduling**](../../wiki/launchd-Scheduling) — plist setup for the 9am job on macOS
- [**Voice-Match Eval Suite**](../../wiki/Voice-Match-Eval-Suite) — how the eval works, baseline scores, regression threshold
- [**Phase 3 Engagement Ingestion**](../../wiki/Phase-3-Engagement-Ingestion) — options (Taplio, manual export, scraping), decision deferred

---

## Roadmap

**Phase 1 — Voice + Writer + manual review** ✅ Done
Brand brain seeded with 47 historical posts. Telegram bot delivers 2 drafts/day. Posts manually copied to LinkedIn.

**Phase 2 — Critic + Typefully scheduling** ✅ Done
Critic agent live with score thresholds gating the pipeline. Approved drafts auto-schedule via Typefully. Full pipeline: Ideator → Writer → Critic → Telegram → Typefully.

**Phase 3 — Analyst + Strategist + closed loop** ← Next
Engagement data ingestion (source TBD: Taplio API / LinkedIn export / scraping). Weekly analyst report driving strategy regeneration. Exit criterion: strategy doc changes meaningfully week-over-week, justified by real data.

**Phase 4 — Reduce HITL, voice notes, experiments**
Voice-note morning input pipeline. Auto-approve high-Critic-score drafts. Deliberate format experiments with measurement. Target: under 30 min/week, 4+ posts/week.

---

## The meta-point

This was built by a Group PM at Tata 1mg using Claude Code as a development partner. It is not a tutorial project or a portfolio demo — it runs in production and real posts go out through it. The architecture decisions were made the way product decisions get made: with explicit constraints, documented tradeoffs, and an exit criterion before moving to the next phase.
