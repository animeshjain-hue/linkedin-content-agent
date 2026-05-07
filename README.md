# LinkedIn Content Agent

A multi-agent system that runs a LinkedIn content pipeline end-to-end — news ingestion, ideation, drafting, critique, HITL approval, and scheduled posting — in production daily.

Built by [Animesh Jain](https://www.linkedin.com/in/animeshjain1996/), Group PM at Tata 1mg.

---

## Table of Contents

- [Why I built this](#why-i-built-this)
- [The pipeline](#the-pipeline)
- [Design philosophy](#design-philosophy)
- [Agents](#agents)
- [Prompt engineering](#prompt-engineering)
- [Voice-match eval suite](#voice-match-eval-suite)
- [What I got wrong](#what-i-got-wrong)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Roadmap](#roadmap)
- [The PM Operating System vision](#the-pm-operating-system-vision)

---

## Why I built this

I wanted to learn agentic system design by building something I'd actually use and break. A LinkedIn content pipeline has all the properties that make agents interesting: ambiguous inputs (news, voice notes), hard-to-specify quality constraints (does this sound like me?), a real feedback loop (engagement data), and meaningful consequences for getting it wrong — my name is on every post.

The same architecture — a memory layer that compounds, agents that are interchangeable, progressive autonomy earned through measurable trust — is the skeleton of a "PM Operating System" I plan to build for other PMs. This is the first running instance of that pattern.

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

**Step by step — what happens at 9am every day:**

1. **News ingestion** — `feedparser` hits 5 RSS feeds (ET Tech, YourStory, Inc42, TechCrunch AI, Hacker News). Each item is deduplicated by a URL-hash UUID and stored in the `news_items` table. New items only.

2. **Ideation** — `IdeatorAgent` loads the 40 most recent news items and all non-rejected posts from the last few days (for theme avoidance). It computes lane targets from `topics.yaml` weights (ai_for_pms 45%, pm_craft 35%, healthcare_ai 20%), injects them as a hard constraint into the prompt, and returns 5–10 `RankedAngle` objects scored by relevance. The top angle is selected automatically.

3. **Writing** — `WriterAgent` loads `voice_guide.md` and finds similar past posts via Chroma vector lookup (originality check). It generates 2 draft variants — each with a `body`, `hook`, `format`, and `rationale`.

4. **Critique** — `CriticAgent` scores each draft on four dimensions: `hook_strength`, `voice_match`, `argument_quality`, `hygiene` (each 1–10). Computes an overall average and returns a one-line verdict.

5. **DB persistence** — both drafts saved to the `posts` table with `status="draft"`.

6. **Telegram delivery** — each draft sent with a score header and inline ✅ / ✏️ / ❌ keyboard.

7. **HITL loop** — approve → `status="approved"` → auto-schedule to Typefully. Edit → send new text → approved and scheduled. Reject → `status="rejected"` + optional reason logged.

8. **Auto-exit** — the bot sends `SIGTERM` to itself after 4 hours (configurable) so the next day's launchd run always fires cleanly.

---

## Design philosophy

### The Brand Brain is the moat

The core bet: LLMs and orchestration frameworks will keep changing. What compounds is the accumulated data — post history, engagement signals, voice calibration, topic experiments. The Brand Brain is three layers:

- **SQLite** — `posts`, `engagement_snapshots`, `news_items` tables. Schema stability is the highest-cost constraint to violate; every migration is a production risk.
- **`voice_guide.md`** — writing style, forbidden phrases, format performance ranked by engagement data from 47 historical posts. The more specific, the better the agent matches voice.
- **`topics.yaml`** — three content lanes with explicit weights (`lane_weight`), sub-topic taxonomy, and guidance on when each sub-topic is appropriate.

Design implication: invest in schema stability. Agents are functions; swap them freely. The memory layer is not.

### Progressive autonomy — agents earn trust per dimension

The problem with full auto-post: one bad post is a brand event. The problem with full manual review: you've built a slightly faster copy-paste tool.

Current automation state per pipeline stage:

| Stage | Automation level | Gate |
|---|---|---|
| News fetch | Fully automated | — |
| Ideation | Fully automated | relevance_score ≥ 0.5 |
| Writing | Fully automated | — |
| Quality scoring | Fully automated | Critic scores all 4 dimensions |
| **Approval** | **Human (Telegram)** | ← current boundary |
| Scheduling | Fully automated on approval | — |

`auto_approve_threshold: 8.5` is live in `config.yaml` but the code path is inactive. It activates in Phase 4 — after enough engagement data has been accumulated to validate whether Critic scores actually predict real performance.

### Voice fidelity as the primary constraint

A correct-sounding mediocre post beats a brilliant post that doesn't sound like the author. This is the hardest problem in the system — harder than capability, harder than format, harder than scheduling.

Every prompt change is gated by the voice-match eval suite. If the distribution of outputs drifts away from the voice profile by more than 0.5 average score points, the change doesn't ship. See [Voice-match eval suite](#voice-match-eval-suite).

### Why bare Anthropic SDK — not LangChain, CrewAI, or LangGraph

Four reasons, in order of weight:

1. **Abstraction hides the prompt, and the prompt is the product.** When something breaks in LangChain, you debug the framework. When something breaks here, you debug your logic. For a system where prompt quality is the primary variable, that distinction matters.

2. **Stability over features.** LangChain has had multiple breaking API changes. The Anthropic SDK has had one. For a system running daily, that cost is real.

3. **Learning.** The goal of v1 is to understand agentic system design, not to configure someone else's abstractions. Writing your own orchestration teaches more.

4. **Simplicity.** In v1, each agent is a single `call_llm()` with a rendered prompt. No state machines, no callback chains. The simplest thing that works.

Honest caveat: this gets re-evaluated at month 3 with real usage data. If the Analyst/Strategist loop requires complex state management, LangGraph might earn its abstraction cost. That's a data-driven decision, not an upfront one.

---

## Agents

All agents inherit from `Agent[InputT, OutputT]` in `src/agents/base.py`. Single public method: `run(input_data: InputT) -> OutputT`. No side-channel state. The orchestrator in `cli.py` owns DB persistence — agents return Pydantic models, never write directly.

| Agent | Model | Runs | Input | Output |
|---|---|---|---|---|
| `IdeatorAgent` | Haiku | Daily | News items, recent posts, lane targets | `list[RankedAngle]` sorted by `relevance_score` |
| `WriterAgent` | Opus | Daily | Top angle, voice guide, similar past posts | 2× `DraftPost` (body, hook, format, rationale) |
| `CriticAgent` | Haiku | Daily | `DraftPost` | `CriticScore` (4 dimensions + verdict) |
| `AngleMappingAgent` | Haiku | On-demand | Free-text idea string | `Angle` (topic_lane, sub_topic, context_note) |
| `EvaluatorAgent` | Haiku | Eval suite only | Draft + prompts | Voice-match scores across 4 dimensions |
| `AnalystAgent` | Haiku | Weekly (Phase 3) | Engagement data | Weekly report + DB updates |
| `StrategistAgent` | Opus | Weekly (Phase 3) | Analyst report | `strategy_current.md` |

`AngleMappingAgent` is the fallback path when you have a specific idea and want to bypass the Ideator. It maps free text to a structured `Angle` with a sharpened `context_note` — not just a topic, but the specific hook or contrarian point to lead with.

---

## Prompt engineering

All prompts live in `prompts/*.md` — never hardcoded in Python. Each file has YAML frontmatter:

```yaml
---
model: claude-haiku-4-5-20251001
temperature: 0.7
max_tokens: 2000
version: "1.1"
---
```

`render_prompt(name, **vars)` in `src/agents/base.py` handles loading, frontmatter parsing, and `{variable}` substitution via regex — safe for JSON braces in the prompt body. The `version` field is logged with every agent run, making prompt regressions traceable.

**Key design choices per prompt:**

- **`ideator.md` v1.1** — injects `{lane_targets}` as a hard distribution constraint (computed from `topics.yaml` `lane_weight` × total angles). Without this, the model gravitates to AI news because it maps most cleanly. Also includes a `{recent_posts}` block (all non-rejected statuses, not just `status="posted"`) for real theme avoidance.

- **`writer.md` v1.0** — injects `{similar_posts}` from Chroma vector lookup so the model sees what's already been written on this sub-topic. Instructs two drafts with meaningfully different formats (e.g., one story, one contrarian), not two versions of the same structure.

- **`critic.md` v1.0** — temperature 0.0 for scoring consistency. Each dimension scored 1–10 with explicit rubrics. Returns a one-line `verdict` string that appears in the Telegram message so the human reviewer gets the signal without reading the full score breakdown.

- **`voice_eval.md`** — used only by `EvaluatorAgent` in the eval suite. Scores originality relative to the seed corpus (47 historical posts) — catching when the Writer accidentally reproduces a hook pattern from training data.

**Prompt versioning workflow:** bump the `version` field → run `uv run pytest tests/test_voice_match.py --run-eval` → if average score holds within −0.5, ship. Results append to `data/eval_history.jsonl`.

---

## Voice-match eval suite

The most important piece of infrastructure beyond the brain itself. Lives in `tests/test_voice_match.py`.

**How it works:**

1. Runs `WriterAgent` on 5 fixed prompts (stored in `tests/fixtures/voice_eval_prompts.json`)
2. For each output, calls `EvaluatorAgent` (Claude Haiku, separate call) to score on:
   - `voice_match` — does it sound like the author, not a generic LinkedIn post
   - `hook_strength` — would this stop the scroll
   - `originality` — not recycling patterns from the 47-post seed corpus
   - `hygiene` — LinkedIn format, length, line breaks, no LLM filler phrases
3. Results saved to `data/eval_history.jsonl`

**Established baseline (as of initial calibration):**

| Metric | Score |
|---|---|
| Voice match | 7.90 |
| Hook strength | 8.80 |
| Originality | 7.60 |
| Hygiene | 9.10 |
| **Overall** | **8.35** |

**Regression threshold:** if average drops > 0.5 from baseline after a prompt or model change, don't ship.

The threshold is not tighter because LLMs are stochastic — run-to-run variance on a single prompt can be ±0.3. A 0.5 drop is a signal, not noise.

Why LLM-as-judge: you can't unit test a draft. Standard tests verify code correctness, not voice fidelity. Using a separate Claude call to evaluate Writer output is the closest thing to a human taste gate that scales.

---

## What I got wrong

The failures are more instructive than the successes.

**1. Token limit crash on the first automated run**

The Ideator prompt hit the 2000-token output limit mid-JSON on day one. The LLM was generating 8 detailed angles and truncating in the middle of a string. `json.loads()` crashed.

Root cause: `max_tokens: 2000` was set globally and is fine for the Writer (2 compact drafts) but not for the Ideator (5–10 verbose angles with rationale and source metadata).

Fix: added `ideator_max_tokens: 4096` as a separate key in `config.yaml`. Simple, but required understanding the output size distribution per agent — something you only learn by running it.

**2. The topic diversity failure**

The Ideator kept picking AI/agent topics despite `topics.yaml` targeting 35% pm_craft content. Two bugs compounding:

*Bug 1:* recent posts query used `status="posted"` — but only 1 post in the DB had that status. The model saw a nearly blank recent-history and had almost no theme-avoidance signal. Fix: changed to `exclude_statuses=["rejected"]` — 15 posts visible instead of 1.

*Bug 2:* the prompt passed `topics.yaml` lane weights as context but never said "enforce this distribution." The model took the path of least resistance: AI news maps cleanly to a lane, business news requires inference. Fix: added `{lane_targets}` as a hard constraint computed from `lane_weight × total_angles`.

**3. Corporate SSL proxy**

All Anthropic API calls failed on the first run. The office network uses a custom certificate chain that Python's default SSL doesn't trust.

Fix: `truststore.inject_into_ssl()` before any network call, and `uv run --system-certs` for all CLI invocations. One-line fix that took 40 minutes to diagnose.

**4. The Critic is not yet validated**

This is the current known unknown. The Critic scores every draft, but there's no evidence yet that a score of 8.5 actually predicts LinkedIn performance better than a score of 6.5. The Analyst agent (Phase 3) will correlate Critic scores against real engagement data and recalibrate. Until then, the scores gate the pipeline but the threshold is a prior, not a posterior.

---

## Tech stack

| Component | Tool | Why |
|---|---|---|
| Language | Python 3.13, uv | Modern toolchain, fast dependency resolution |
| LLM — Writer/Strategist | `claude-opus-4-7` | Best reasoning and voice fidelity at higher stakes |
| LLM — Critic/Ideator/utility | `claude-haiku-4-5` | Fast and cheap for scoring and classification |
| LLM client | Anthropic SDK (bare) | No LangChain/CrewAI — own orchestration, re-evaluate month 3 |
| Database | SQLite | Zero infrastructure, file-backed, good enough for one user |
| Vector store | Chroma (local) | Similar-post lookup for originality checks in Writer |
| RSS ingestion | feedparser | No API key needed, covers all five target sources |
| HITL | python-telegram-bot | Low-friction mobile approval flow |
| Scheduling (post) | Typefully API | Native LinkedIn scheduling |
| Scheduling (jobs) | launchd (macOS) | Fires at 9am daily, logs to `logs/launchd.log` |
| Data models | pydantic v2 | Strict typing across all module boundaries |
| Logging | structlog → JSON | Every agent run logs input hash, model, tokens, latency, output hash |
| Lint / types | ruff + mypy --strict | Enforced via pre-commit |

---

## Project structure

```
linkedin-agent/
├── config.yaml                  # tunables: feed URLs, model names, thresholds
├── .env.example                 # secrets template — copy to .env
├── pyproject.toml
├── data/
│   ├── brain.db                 # gitignored — SQLite brain
│   ├── voice_guide.example.md   # tracked — template for your own voice guide
│   ├── topics.yaml              # tracked — content lanes, weights, sub-topics
│   └── eval_history.jsonl       # gitignored — voice-match eval history
├── migrations/
│   └── 001_init.sql             # posts, engagement_snapshots, news_items
├── prompts/                     # all prompts as .md with YAML frontmatter
│   ├── ideator.md               # news → ranked angles (v1.1)
│   ├── writer.md                # angle → 2 draft variants (v1.0)
│   ├── critic.md                # draft → 4-dimension score (v1.0)
│   ├── angle_mapper.md          # free text → structured angle
│   └── voice_eval.md            # eval suite judge prompt
├── src/
│   ├── agents/
│   │   ├── base.py              # Agent ABC, render_prompt(), structured logging
│   │   ├── ideator.py           # RankedAngle list from news feed
│   │   ├── writer.py            # 2 DraftPost variants
│   │   ├── critic.py            # CriticScore (4 dims + verdict)
│   │   ├── mapper.py            # free text → Angle
│   │   ├── evaluator.py         # voice-match judge (eval suite only)
│   │   ├── strategist.py        # stub — Phase 3
│   │   └── analyst.py           # stub — Phase 3
│   ├── brain/
│   │   ├── db.py                # connection, WAL mode, migrations runner
│   │   ├── posts.py             # CRUD: posts + engagement snapshots
│   │   ├── similarity.py        # Chroma vector lookups
│   │   └── voice.py             # load voice_guide.md with clear error if missing
│   ├── inputs/
│   │   ├── news.py              # feedparser, URL-hash dedup, news_items CRUD
│   │   ├── reading.py           # reading queue stub
│   │   ├── voice_notes.py       # Whisper transcription stub
│   │   └── work_artifacts.py    # manual paste / Granola stub
│   ├── outputs/
│   │   ├── telegram_bot.py      # inline keyboard, approval state machine
│   │   └── typefully.py         # schedule on approval
│   ├── llm.py                   # Anthropic client: retry, caching, structured log
│   ├── config.py                # pydantic settings from .env + config.yaml
│   ├── schemas.py               # Post, NewsItem, VoiceGuide, StrategyDoc, etc.
│   └── cli.py                   # typer: agent fetch-news, ideate, write, run-daily
└── tests/
    ├── test_brain.py
    ├── test_voice_match.py      # voice-match eval suite, --run-eval flag
    └── fixtures/
        └── voice_eval_prompts.json
```

---

## Quick start

```bash
# 1. Clone and install
git clone https://github.com/animeshjain-hue/linkedin-content-agent.git
cd linkedin-content-agent
uv sync

# 2. Configure secrets
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TYPEFULLY_API_KEY

# 3. Set up your voice guide (the most important step)
cp data/voice_guide.example.md data/voice_guide.md
# Edit voice_guide.md — add your hooks, example sentences, forbidden phrases

# 4. Run database migrations
uv run python -c "from src.brain.db import run_migrations; from pathlib import Path; run_migrations(Path('data/brain.db'))"

# 5. Fetch news and see what the Ideator surfaces
uv run --system-certs agent ideate

# 6. Run the full daily pipeline
uv run --system-certs agent run-daily
```

On macOS, the 9am launchd job fires automatically once the plist is loaded. See `Configuration` below.

---

## Configuration

**`config.yaml`** — safe to commit, no secrets:

```yaml
models:
  writer: "claude-opus-4-7"
  critic: "claude-haiku-4-5-20251001"
  ideator: "claude-haiku-4-5-20251001"

agent_defaults:
  temperature: 0.7
  critic_temperature: 0.3       # lower = more consistent scores
  max_tokens: 2000
  ideator_max_tokens: 4096      # ideator output is larger (5–10 verbose angles)

content:
  auto_approve_threshold: 8.5   # unused until Phase 4 — needs engagement data first

news_feeds:                     # add/remove feeds here
  - name: et_tech
    url: "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms"
  - name: hacker_news_top
    url: "https://hnrss.org/frontpage"
  # ... (see config.yaml for full list)
```

**`.env`** — never commit (see `.env.example`):

```
ANTHROPIC_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TYPEFULLY_API_KEY=...
OPENAI_API_KEY=...      # for Whisper voice notes (Phase 4)
```

**launchd plist** (macOS) — fires the pipeline at 9am daily:

```bash
# Load (one-time setup)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.animesh.linkedin-agent.daily.plist

# Logs
tail -f logs/launchd.log

# Unload
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.animesh.linkedin-agent.daily.plist
```

---

## Roadmap

**Phase 1 — Voice + Writer + manual review** ✅
Brand brain seeded with 47 historical posts. Telegram bot delivers 2 drafts/day. Posts manually copied to LinkedIn.

**Phase 2 — Critic + Typefully scheduling** ✅
Critic live with 4-dimension scoring. IdeatorAgent pulling from RSS news feed with lane-weighted angle ranking. Approved drafts auto-schedule via Typefully. launchd fires the pipeline at 9am daily without manual invocation.

**Phase 3 — Analyst + Strategist + closed loop** ← Next
Engagement data ingestion (source TBD: Taplio API / LinkedIn export / scraping). Weekly analyst report drives strategy regeneration. Exit criterion: `strategy_current.md` changes meaningfully week-over-week, justified by real data.

**Phase 4 — Reduce HITL, voice notes, experiments**
Voice-note morning input via Whisper transcription. Auto-approve drafts where Critic ≥ 8.5 AND EvaluatorAgent voice-match ≥ 8.0 (both gates independent). Deliberate format experiments with measurement. Target: under 30 min/week, 4+ posts/week.

---

## The PM Operating System vision

The LinkedIn agent is chapter one of something larger.

A PM generates and processes a high volume of structured information daily — customer interviews, PRDs, stakeholder updates, data investigations, competitive analyses. Today that processing is manual and lossy. The patterns, decisions, and context disappear into Slack threads and half-filled Notion docs.

The PM OS is a memory-augmented system that captures work artifacts (meeting transcripts, Mixpanel investigations, PRDs, OKR updates), extracts decisions and context, surfaces relevant prior work at the right moment, and generates first-draft outputs calibrated to the PM's voice and judgment style.

The LinkedIn agent validated the foundational bets:

- The **Brand Brain architecture works** — memory layer compounds, agents are swappable
- **Progressive autonomy is the right trust model** — start with HITL, earn automation per dimension with measurement
- **Voice fidelity is harder than capability** — making an LLM sound like a specific person is a different problem from making it competent
- **Real feedback loops matter** — the Strategist isn't built yet because there's no real engagement data. This is a discipline, not a limitation.

This is not a pivot from PM to engineer. It's a PM using engineering to solve PM problems. The distinction matters.

---

*Built with [Claude Code](https://claude.ai/code). In production since May 2026.*
