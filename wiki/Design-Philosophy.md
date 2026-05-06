# Design Philosophy

Three foundational decisions made before writing a single line of agent code. Each one is a bet about what will compound over time and what will depreciate.

---

## The Brand Brain is the moat

The insight that drove the entire architecture: agents are interchangeable, but the memory layer compounds.

LLMs will change. Claude Opus 4 today, something else in six months. Agent frameworks will change — LangChain v0 to v1 to v2 to something else entirely. What doesn't change, and what gets more valuable the longer the system runs, is the accumulated data: every post Animesh has ever written, every engagement signal on those posts, every piece of voice calibration, every strategic experiment and its result.

That's the Brand Brain. It consists of four components:

**SQLite (`data/brain.db`)** — three tables, each with a deliberate schema:

- `posts` — every generated draft, with its status (`draft`, `approved`, `scheduled`, `posted`, `rejected`), format, topic lane, hook, prompt version, and model. The `prompt_version` column exists specifically so you can later ask "did Critic v1.1 produce better output than v1.0?" without guessing.
- `engagement_snapshots` — reactions, comments, reposts, impressions, and profile view delta, linked by `post_id`. Designed to be populated by the Analyst agent in Phase 3, but the schema is live now so no migration is needed when Phase 3 starts.
- `news_items` — deduplicated by URL hash, with a `relevance_score` column that starts `NULL` and gets written by the Ideator. The `used_in_post_ids` column closes the loop: you can always trace which news item triggered which post.

**`data/voice_guide.md`** — the writing constitution. Derived from analysis of 47 real posts, not invented. Contains: three hook archetypes (confession, question implying insider knowledge, grounded observation), what the corpus shows about format performance (strategy teardowns: 228K impressions; resource roundups: retired), a full forbidden-phrase list (`delve`, `tapestry`, `in today's fast-paced world`, and fourteen others), and example sentences pulled verbatim from high-performing posts for style reference. This file is tracked in git. It is the most important file in the repository.

**`data/topics.yaml`** — the content lane taxonomy. Three lanes with explicit weights: `ai_for_pms` (45%), `pm_craft` (35%), `healthcare_ai` (20%). Each lane has sub-topics that act as angle seeds. The weights reflect intended future direction, not historical behavior — the 47-post corpus is 65% `pm_craft` and nearly zero `ai_for_pms`. The Ideator uses `_compute_lane_targets()` to translate these weights into per-run angle targets, creating a structural correction mechanism.

**`data/strategy_current.md`** — regenerated weekly by the Strategist agent. Contains the lane mix, target post frequency, preferred formats, experiments to run, and formats to avoid based on last week's engagement data. Gitignored because it changes weekly; the history lives in the DB.

**The design implication is strict: optimize the memory layer; swap agents freely.**

The data models in `src/schemas.py` are the most expensive things to change. Every column rename, every status enum extension, every new FK relationship is a SQL migration that has to be written, tested, and applied against the production database. The models have been stable since the first commit. The agents have already been iterated on twice.

The practical rule: when you're tempted to store something "temporarily" in a Python dict or a local file, ask whether this is data that compounds. If it is, it belongs in the DB with a proper column and a migration. If it isn't, keep it ephemeral. Very little is truly ephemeral.

---

## Progressive autonomy — how agents earn trust

The failure mode on the left: full auto-post. One bad post is a brand event. Animesh's name is on every post. The system cannot be trusted with the decision to publish until it has demonstrated — with real engagement data — that its judgment is calibrated.

The failure mode on the right: full human review of everything. At that point you've built a slightly faster copy-paste tool. The automation exists to reduce the cognitive overhead of daily content production, not just to make the drafts appear in a nicer interface.

The solution is progressive autonomy per dimension. The system currently operates at:

| Dimension | Current state | Phase |
|---|---|---|
| News fetch | Fully automated — feedparser polls 5 RSS feeds every 6h | Phase 2 |
| Ideation | Fully automated — IdeatorAgent surfaces 5–10 ranked angles | Phase 2 |
| Writing | Fully automated — WriterAgent generates 2 structurally distinct drafts | Phase 2 |
| Quality gate | Automated — CriticAgent scores hook/voice/argument/hygiene, 0–10 | Phase 2 |
| Approval | Human — Telegram ✅/✏️/❌ on every draft | Phase 2 |
| Scheduling | Automated on approval — Typefully API called immediately | Phase 2 |
| Auto-approval | Configured but inactive — `auto_approve_threshold: 8.5` in config.yaml | Phase 4 |

The Critic score is the trust gate. `auto_approve_threshold` in `config.yaml` is set to 8.5, but the code path that uses it doesn't activate until Phase 4. The reason it's deferred is deliberate: the Critic's judgment cannot be trusted until there is engagement data that validates it. If the Critic consistently scores 9/10 drafts that get 20 reactions and 5-view profile bumps, the threshold needs recalibrating. You cannot recalibrate what you haven't measured.

**The principle: never expand automation in a dimension where you don't have a measurement.**

The measurement for writing quality is the voice-match eval suite in `tests/test_voice_match.py`. Five fixed prompts, Claude-as-judge scoring on voice match, hook strength, originality, and LinkedIn format hygiene. Baseline at system launch: 8.35 overall (VM=7.90, HS=8.80, OR=7.60, HY=9.10). Any prompt version bump that drops the average by more than 0.5 does not ship. This is the gate that makes it safe to iterate on the Writer and Critic prompts without regressing the thing that matters most — that the output sounds like Animesh.

The trust-earning mechanism works in one direction: automation earns trust through demonstrated performance, not through confidence. The Ideator runs fully automated because there's no brand risk in surfacing an irrelevant angle — Animesh sees it in the Telegram message and rejects it. The auto-approval gate stays off because there is brand risk in publishing a post that sounds slightly off, and that risk doesn't have a data-validated mitigation yet.

---

## Why bare Anthropic SDK (not LangChain, CrewAI, or LangGraph)

This is a deliberate choice, not a default. Here is the full argument.

### 1. The prompt is the product — abstractions hide it

In this system, the Writer prompt in `prompts/writer.md` is as important as any Python module. It encodes voice calibration, format rules, and structural conventions distilled from 47 posts of corpus analysis. When something goes wrong — a draft that doesn't sound like Animesh, a format that breaks — the first place to look is the prompt.

Every abstraction layer adds distance between you and the prompt. In LangChain, prompts can be templated, chained, modified by callbacks, and mutated by memory modules before they reach the model. When a LangChain chain produces unexpected output, you debug the framework to find out what the actual prompt was. In the bare SDK, `render_prompt("writer", **vars)` returns the exact string that gets sent to the API. There is no distance.

### 2. Stability matters more than features for a daily-running system

LangChain has had three breaking API changes in 18 months. `from langchain.llms import OpenAI` is a different import than it was a year ago. `LLMChain` is deprecated. The callback interface changed. For a system you run every day, framework churn is a maintenance tax you pay continuously.

The Anthropic SDK has had one significant API change in the same period (the messages API replacing the completions API). The `anthropic.Anthropic().messages.create()` interface has been stable. The `tenacity`-based retry wrapper in `src/llm.py` hasn't needed to change since it was written.

When you're a PM building a system on 2 hours/day, debugging "did LangChain change something in a minor version bump" is not a good use of that time.

### 3. The learning goal is the architecture, not the framework

This system exists for two reasons: to run Animesh's LinkedIn presence, and to learn agentic system design well enough to build a future "PM Operating System" product. Learning agentic design by configuring someone else's abstractions teaches you the abstractions, not the design.

Writing your own orchestration — the `Agent` base class in `src/agents/base.py`, the `render_prompt` utility, the `call_llm` wrapper with retry logic, the run_daily orchestrator that sequences Ideator → Writer → Critic → Telegram — forces you to make explicit every decision that a framework would have made for you implicitly. What does an agent's contract look like? (One public method: `run(InputModel) -> OutputModel`.) Who writes to the database? (The orchestrator, not the agent.) How does retry work? (Exponential backoff via tenacity: 1s/4s/16s, three attempts.)

These are architectural decisions. Making them explicitly, rather than accepting a framework's defaults, is where the learning is.

### 4. For v1, each agent is a single function call

The system currently has five agents: Ideator, Writer, Critic, AngleMapper (a lightweight Haiku call that maps free-text ideas to the content taxonomy), and Evaluator (the voice-match judge). Every one of them is a `render_prompt` call, a `call_llm` call, and a `_parse_*` function that extracts a Pydantic model from JSON. There is no state management between steps, no shared memory within a run, no complex chaining. The orchestrator in `scripts/run_daily.py` handles sequencing with straightforward Python: call Ideator, pass top angle to Writer, pass each draft to Critic, send to Telegram.

LangGraph's directed graph execution model is designed for exactly the kind of stateful multi-step agent orchestration that this system will eventually need — the weekly Analyst → Strategist loop in Phase 3, where the Strategist's prompt depends on the Analyst's output which depends on the previous week's engagement data. But it isn't needed today, and adding it today means carrying the abstraction cost before getting the benefit.

### The honest caveat

At month 3, this gets re-evaluated. The specific trigger conditions:

- If the Strategist/Analyst loop requires complex state management across multiple LLM calls within a single run, LangGraph may earn its abstraction cost.
- If the agent count grows past 8–10 and orchestration logic becomes a significant maintenance burden, a lightweight framework becomes justified.
- If the team grows past one (Animesh), framework conventions reduce onboarding friction in ways that matter.

None of those conditions exist today. The re-evaluation happens with real usage data from three months of production operation, not upfront speculation.

The principle: adopt an abstraction when its cost is justified by demonstrated complexity, not when its existence suggests the complexity might arrive someday.
