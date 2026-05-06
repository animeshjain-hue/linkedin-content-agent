# Agent Directory

Every agent in this system is a Python class that inherits from `Agent[InputT, OutputT]` in `src/agents/base.py`. Each has one public method. The orchestrator in `src/cli.py` handles all wiring, persistence, and sequencing. Agents do not know about each other.

---

## The base contract

```python
class Agent(ABC, Generic[InputT, OutputT]):
    @abstractmethod
    def run(self, input_data: InputT) -> OutputT: ...
```

This is the entire base class. Single public method. No `__init__` configuration, no shared state, no side effects. The orchestrator calls `agent.run(input)` and gets back a Pydantic model. What to do with that model — persist it, log it, pass it to the next agent — is the orchestrator's problem.

Why single public method:

- **Testability.** You can test any agent by constructing its input model and asserting on its output model. No DB mocks, no HTTP interception, no setup fixtures beyond the model.
- **No side-channel state.** Agents that accumulate state between calls are harder to reason about and harder to run in parallel. A stateless `run()` is trivially safe.
- **Orchestrator owns persistence.** If agents wrote to the DB directly, you could not swap the orchestrator, run agents out of order, or test them without a live DB. The indirection costs nothing and buys testability.

All agent inputs and outputs are Pydantic v2 `BaseModel` subclasses. No raw dicts cross module boundaries.

---

## IdeatorAgent

**File:** `src/agents/ideator.py`  
**Model:** `claude-haiku-4-5-20251001`  
**Runs:** Daily, at the start of the pipeline (before WriterAgent)  
**Prompt:** `prompts/ideator.md` v1.1

**What it does:** Surfaces ranked post angles from the news feed. This is the step that answers "what should I post about today?" without requiring Animesh to decide.

**Input:**

```python
class IdeatorInput(BaseModel):
    max_angles: int = 10
    news_hours: int = 48       # look-back window for news_items table
    refresh_news: bool = True  # fetch RSS feeds before querying
```

**Output:**

```python
class IdeatorOutput(BaseModel):
    angles: list[RankedAngle]   # sorted by relevance_score desc, score >= 0.5
    news_items_used: int
    prompt_version: str
    model: str
    input_tokens: int
    output_tokens: int
```

Each `RankedAngle` carries `topic_lane`, `sub_topic`, `context_note` (the specific hook the Writer should lead with), `rationale` (why this is timely), `relevance_score` (0.0–1.0), and optional `source_title` / `source_url`.

**Lane targeting:** Before rendering the prompt, `_compute_lane_targets()` reads `data/topics.yaml` and computes the expected angle count per lane from the configured weights (`ai_for_pms` 45%, `pm_craft` 35%, `healthcare_ai` 20%). This target string is injected into the prompt as a hard constraint. The model is told to count its angles by lane before returning and replace the weakest over-represented angles with alternatives from under-represented lanes.

**Theme avoidance:** The 15 most recent non-rejected posts are passed in full (lane, sub_topic, hook). The model is told not to repeat lane/sub_topic combinations already in this list.

**`healthcare_ai` restriction:** Angles in this lane are only valid if the news item is directly about Indian healthcare, pharma, or ePharmacy. The prompt explicitly prohibits manufacturing healthcare takes from general AI news.

---

## WriterAgent

**File:** `src/agents/writer.py`  
**Model:** `claude-opus-4-7`  
**Runs:** Daily, after IdeatorAgent selects the top angle  
**Prompt:** `prompts/writer.md` v1.0

**What it does:** Generates two full LinkedIn post drafts from the selected angle. Uses Opus because this is where brand risk is highest — a bad post from a cheap model costs more than it saves.

**Input:**

```python
class WriterInput(BaseModel):
    topic_lane: Literal["ai_for_pms", "pm_craft", "healthcare_ai"]
    sub_topic: str
    context_note: str = ""
```

**Output:**

```python
class WriterOutput(BaseModel):
    drafts: list[DraftPost]  # always 2
    prompt_version: str
    model: str
    input_tokens: int
    output_tokens: int
```

Each `DraftPost`:

```python
class DraftPost(BaseModel):
    body: str
    hook: str   # first 1-2 lines — what the Critic and Telegram UI display
    format: Literal["story", "framework", "contrarian", "list", "build_log", "question"]
    rationale: str  # one sentence: why this hook and format for this topic
```

**Context loaded before the LLM call:**

1. `load_voice_guide()` from `src/brain/voice.py` — reads `data/voice_guide.md`, the canonical document describing how Animesh writes, what he avoids, and what his best posts look like.
2. `find_similar_posts()` from `src/brain/similarity.py` — queries the DB for posts in the same `topic_lane`, preferring `sub_topic` matches. Up to 5 posts are returned and formatted as style reference blocks. These are real posts with real engagement — the highest-reach formats in the 47-post corpus are documented in the voice guide and reinforced here.

The two drafts must be structurally different — different hook type or different format, not paraphrases. The prompt enforces this as a hard constraint.

---

## CriticAgent

**File:** `src/agents/critic.py`  
**Model:** `claude-haiku-4-5-20251001`  
**Runs:** Daily, once per draft (twice per pipeline run)  
**Prompt:** `prompts/critic.md` v1.0  
**Temperature:** 0.0 (deterministic)

**What it does:** Scores each draft on four dimensions and returns a one-sentence verdict. Lower-stakes than the Writer, so Haiku is sufficient. Temperature 0.0 because scoring should be consistent — stochastic scores would make the threshold (currently 8.5 for auto-approve in Phase 2+) meaningless.

**Input:**

```python
class CriticInput(BaseModel):
    draft: DraftPost
```

**Output:**

```python
class CriticScore(BaseModel):
    hook_strength: int      # 1-10
    voice_match: int        # 1-10
    argument_quality: int   # 1-10
    hygiene: int            # 1-10
    verdict: str            # "main strength — main weakness or fix"

    @computed_field
    def overall(self) -> float:
        return (hook_strength + voice_match + argument_quality + hygiene) / 4.0
```

`overall` is a `@computed_field` — it is derived at read time, not stored.

**Scoring rubric (from `critic.md`):**

- **Hook strength:** Must be one of three types: confession/admission ("I was wrong"), knowing question implying the author has seen something others haven't, or a grounded scene. A thesis opener or generic opener is scored low regardless of the content's quality.
- **Voice match:** First person, specific numbers and names, PM lens, ends with a concrete answerable question tied to the reader's experience. "What do you think?" and "share in the comments" are explicitly penalised.
- **Argument quality:** Concrete and specific. A real observation, data point, or lived moment. Generic PM wisdom that applies to anyone scores 6 or below.
- **Hygiene:** Starts at 10, deducts for hashtags inside the body, forbidden phrases, word count outside 150-300, vague closing question, more than one emoji, self-promotion CTAs.

The Critic's score header appears on every Telegram message. Animesh sees the breakdown before he reads the draft. This is intentional — it trains calibration between his gut reaction and the model's score.

---

## AngleMappingAgent

**File:** `src/agents/mapper.py`  
**Model:** `claude-haiku-4-5-20251001`  
**Runs:** On-demand, when `agent run-daily --idea "..."` is invoked  
**Prompt:** `prompts/angle_mapper.md` v1.0  
**Temperature:** 0.3

**What it does:** Maps a free-text idea to a structured angle — `topic_lane`, `sub_topic`, `context_note`, `rationale`. This is the manual-override entry point for days when Animesh has a specific idea (a meeting insight, something from Granola, a spicy take) and does not want to wait for the Ideator to surface it from news.

**Input:**

```python
class MapperInput(BaseModel):
    free_text: str
```

**Output (`Angle`):**

```python
class Angle(BaseModel):
    topic_lane: Literal["ai_for_pms", "pm_craft", "healthcare_ai"]
    sub_topic: str        # snake_case slug, 3-5 words
    context_note: str     # refined angle — sharper than the raw input
    rationale: str        # why this lane and angle choice
```

The `context_note` is what the AngleMappingAgent adds that the raw `--idea` text does not have: a sharper, more specific framing that tells the Writer exactly what the concrete insight or tension to explore is.

`healthcare_ai` is explicitly flagged in the prompt as rare — the agent is told he has zero historical posts in this lane and to treat it as a stretch unless the idea clearly involves health-tech.

---

## EvaluatorAgent

**File:** `src/agents/evaluator.py`  
**Model:** `claude-haiku-4-5-20251001`  
**Runs:** In the voice-match eval suite only (`pytest --run-eval`) — not in the daily pipeline  
**Prompt:** `prompts/voice_eval.md` v1.0  
**Temperature:** 0.0

**What it does:** Scores a WriterAgent output on four dimensions specifically designed for voice fidelity assessment, distinct from the CriticAgent's production scoring. This is the judge in the CI gate for prompt quality.

**Input:**

```python
class EvaluatorInput(BaseModel):
    draft: DraftPost
    voice_guide: str   # full voice_guide.md content
    seed_hooks: str    # sample hooks from real posts — originality reference
```

**Output:**

```python
class EvalScore(BaseModel):
    voice_match: int    # 1-10
    hook_strength: int  # 1-10
    originality: int    # 1-10 — explicitly against the seed hooks corpus
    hygiene: int        # 1-10
    verdict: str

    @computed_field
    def average(self) -> float:
        return (voice_match + hook_strength + originality + hygiene) / 4.0
```

The key difference from `CriticScore` is `originality` — the Evaluator is explicitly shown the real seed hooks and penalises near-paraphrases. The Critic does not have this signal. The Evaluator also has a richer scoring rubric in `voice_eval.md` (detailed deduction rules per violation) compared to the Critic's simpler instructions.

---

## AnalystAgent

**File:** `src/agents/analyst.py`  
**Model:** `claude-haiku-4-5-20251001`  
**Runs:** Weekly — Phase 3, not yet implemented  
**Status:** Stub

Planned inputs: engagement snapshots from `brain.db`, raw post data. Planned output: a weekly report summarising WoW engagement trends, format performance, and experiments to try. The report feeds into the StrategistAgent.

Not implemented until real engagement data is flowing. Building an analyst without data produces fictional analysis and false confidence.

---

## StrategistAgent

**File:** `src/agents/strategist.py`  
**Model:** `claude-opus-4-7`  
**Runs:** Weekly — Phase 3, not yet implemented  
**Status:** Stub  
**Prompt:** `prompts/strategist.md`

Planned inputs: AnalystAgent's weekly report, current `data/strategy_current.md`, `data/topics.yaml`. Planned output: a new `strategy_current.md` — a `StrategyDoc` pydantic model written to disk — covering lane mix targets, preferred formats, preferred posting times, experiments to run next week, and things to avoid based on last week's data.

Uses Opus because the Strategist rewrites the strategy document that drives every subsequent week of content. Cost is justified by the leverage. Opus for Writer and Strategist; Haiku for everything else.
