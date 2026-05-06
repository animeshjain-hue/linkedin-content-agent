# Prompt Engineering

The prompt is the product. Every word in `prompts/writer.md` is a product decision. This page documents the prompt system — how prompts are stored, rendered, versioned, and evaluated — and covers each prompt file in detail.

---

## The prompt file convention

All prompts live in `prompts/*.md`. No prompt text is hardcoded in Python. This is non-negotiable: if a prompt is in Python, it cannot be version-controlled independently of code, cannot be read and edited without understanding the surrounding Python, and cannot be bumped without touching agent logic.

Every prompt file has YAML frontmatter:

```yaml
---
model: claude-haiku-4-5-20251001
temperature: 0.7
max_tokens: 2000
version: "1.1"
---

Prompt body starts here.
```

Fields:

| Field | Purpose |
|---|---|
| `model` | The intended model. `call_llm()` reads this from config, not frontmatter — frontmatter is documentation. |
| `temperature` | Documented intent. Claude 4.x models (opus-4, haiku-4, sonnet-4) ignore this parameter — `call_llm()` omits it for these models. |
| `max_tokens` | Hard cap. Config values override for specific agents (e.g., `ideator_max_tokens: 4096`). |
| `version` | Semantic string. Logged with every agent run, stored in `posts.prompt_version`, referenced in eval history. |

The `version` field is the traceability mechanism. If a post approved three weeks from now has a quality problem, querying `SELECT prompt_version FROM posts WHERE id = ?` tells you exactly which prompt version generated it. Bumping version without running the eval suite is prohibited.

---

## The render_prompt utility

`render_prompt(name, **variables)` in `src/agents/base.py` is the single function that loads and renders all prompts.

```python
def render_prompt(name: str, **variables: str) -> tuple[str, dict[str, Any]]:
    path = PROMPTS_DIR / f"{name}.md"
    content = path.read_text(encoding="utf-8")

    if content.startswith("---"):
        _, front, body = content.split("---", 2)
        front_matter = yaml.safe_load(front) or {}
        template = body.strip()
    else:
        front_matter = {}
        template = content.strip()

    rendered = re.sub(
        r"\{(\w+)\}",
        lambda m: variables.get(m.group(1), m.group(0)),
        template,
    )
    return rendered, front_matter
```

Three design decisions worth noting:

**Regex substitution instead of `str.format()`.** Python's `str.format()` interprets `{` as a format marker, which means any JSON example in the prompt body — like the output schema examples that every prompt includes — breaks the render. The regex approach matches only `{word}` — single alphanumeric identifiers — and leaves `{"key": "value"}` untouched.

**Missing keys are preserved, not raised.** The `_SafeMap` fallback returns `"{key}"` for any variable not in `variables`. This means a partial render produces an obvious indicator in the rendered text rather than a silent KeyError at call time.

**Frontmatter is returned, not consumed.** The caller — usually the agent's `run()` method — receives the `front_matter` dict. It reads `front.get("version", "unknown")` and includes it in the output model. The render function does not look at model or temperature — it only does loading and substitution.

---

## ideator.md — v1.1

**Model:** `claude-haiku-4-5-20251001`  
**Temperature:** 0.7 (omitted for Claude 4.x)  
**Max tokens:** 4096 (from `config.yaml::agent_defaults.ideator_max_tokens`)

**Variables injected:**
- `{topics_yaml}` — full contents of `data/topics.yaml`
- `{news_items}` — formatted list of up to 40 news items (number, source, title, URL, summary[:300])
- `{recent_posts}` — up to 15 recent non-rejected posts formatted as `[status] [lane/sub_topic] hook`
- `{lane_targets}` — computed string from topics.yaml weights, e.g. "- ai_for_pms: ~5 of 10 angles (weight 45%)"

**What it produces:** A JSON object with an `angles` array. Each angle has `topic_lane`, `sub_topic`, `context_note`, `rationale`, `relevance_score`, `source_title`, `source_url`.

**Key prompt decisions:**

The `{lane_targets}` block is marked as a hard constraint in the prompt text: *"Count your angles by lane before returning. If you have too many ai_for_pms angles, replace the weakest ones with pm_craft alternatives."* Without this, the model consistently over-produces `ai_for_pms` angles because the news feed skews toward AI stories.

The `context_note` field is what separates v1.1 from a naive implementation. The model is not just asked to identify a topic — it is asked to write the specific hook the Writer should lead with: the contrarian point, the data observation, or the story lead. The IdeatorAgent is effectively doing a third of the Writer's job by sharpening the angle before any writing starts.

The `healthcare_ai` lane has an explicit guard: *"only include if the news is directly about Indian healthcare, pharma, or ePharmacy."* This is because Animesh has zero historical posts in this lane and the corpus provides no voice reference for it. Manufacturing healthcare takes from general AI news would produce drafts with no corpus grounding.

`relevance_score` below 0.5 — skip it. This prevents the model from padding the response with weak angles.

Version bumped from 1.0 to 1.1 when `lane_targets` enforcement was tightened and the `context_note` instruction was made more specific. The eval did not regress.

---

## writer.md — v1.0

**Model:** `claude-opus-4-7`  
**Temperature:** 0.7 (omitted for Claude 4.x)  
**Max tokens:** 2000

**Variables injected:**
- `{voice_guide}` — full contents of `data/voice_guide.md`
- `{similar_posts}` — up to 5 posts from the corpus, formatted as `[Hook: '...' | Format: ...]` blocks
- `{topic_lane}` — one of `ai_for_pms`, `pm_craft`, `healthcare_ai`
- `{sub_topic}` — snake_case slug
- `{context_note}` — the Ideator's angle or the AngleMappingAgent's refinement

**What it produces:** A JSON object with a `drafts` array of exactly 2 `DraftPost` objects.

**Key prompt decisions:**

The prompt opens with a specific, grounding statement: *"You are writing a LinkedIn post for Animesh Jain — Group PM at Tata 1mg, leading ePharmacy & Generics. He has 5.5k+ followers. His posts are read by PMs, founders, and operators in the Indian startup ecosystem."* This is not boilerplate. It sets the audience (Indian startup ecosystem, not generic global LinkedIn), the authority base (ePharmacy, Generics — specific enough to ground the voice), and the reach context (5.5k followers — established enough to have standards, not so large that everything needs to be safe).

The `{similar_posts}` injection is where the corpus does the most work. These are real posts with real engagement. The prompt instructs the Writer to *"study the hook structure, sentence rhythm, argument build, and how he ends"* — not just to use them as topic templates. Format performance data embedded in the voice guide (strategy teardowns at 228K impressions, resource roundups retired) is the mechanism by which past engagement shapes future writing.

The two-draft constraint enforces structural diversity: *"different hook type OR different format, not paraphrases of each other."* Without this, the model produces near-identical drafts that differ only in word choice, giving Animesh no real choice.

The closing question rule is specific: *"End with a specific, answerable question grounded in the reader's own experience — not 'what do you think?' or 'share in the comments!'"* This is derived from Animesh's actual post endings. Vague closing questions are a pattern the Critic penalises — having the Writer avoid them is cheaper than having the Critic catch them.

The JSON output schema is shown verbatim in the prompt body. Because `render_prompt` uses regex substitution, the JSON braces in the schema are preserved without escaping.

---

## critic.md — v1.0

**Model:** `claude-haiku-4-5-20251001`  
**Temperature:** Not set (0.0 enforced in `CriticAgent.run()`)  
**Max tokens:** 250

**Variables injected:**
- `{draft_format}` — the format declared by the Writer
- `{draft_body}` — the full post body

**What it produces:** A JSON object with `hook_strength`, `voice_match`, `argument_quality`, `hygiene` (each 1-10) and `verdict`.

**Key prompt decisions:**

The three hook types are enumerated explicitly with examples: confession/admission ("I was wrong"), knowing question ("Did you notice..."), grounded scene ("I just noticed..."). The prompt then lists what is never acceptable: *"thesis opener ('Great PMs do X'), generic opener ('In today's world', 'As a PM, I often think'), motivational poster without a story."* This level of specificity is what separates a useful critic from one that gives everyone a 7.

The hygiene dimension uses a deduction model rather than a holistic score. The Evaluator's `voice_eval.md` makes this explicit (deduct −3 for hashtags, −3 for forbidden phrases, etc.). The Critic's `critic.md` describes the same logic in prose. Haiku is reliable enough at this structured scoring task that the simpler prose instruction is sufficient.

The scoring calibration instruction is critical: *"Be critical — 7 means good, 8 means strong, 9 means excellent, 10 is rare."* Without this, models systematically inflate scores. A 7 from the Critic should feel like a draft worth sending; a 6 should feel like it needs work. The auto-approve threshold in config (8.5) is calibrated against this rubric, not a naive 1-10 scale.

Max tokens is 250 because the output is a small JSON object with a one-sentence verdict. Haiku can produce this in under 100 tokens. The 250 cap is a safety buffer, not a target.

---

## angle_mapper.md — v1.0

**Model:** `claude-haiku-4-5-20251001`  
**Temperature:** 0.3 (low — the mapping should be deterministic, not creative)  
**Max tokens:** 300

**Variables injected:**
- `{free_text}` — Animesh's raw idea as typed on the CLI

**What it produces:** A JSON object with `topic_lane`, `sub_topic` (snake_case slug), `context_note`, `rationale`.

**Key prompt decisions:**

The three lanes are described with enough specificity that the model makes the right call even on ambiguous inputs. `pm_craft` is described as "his strongest lane by volume." `healthcare_ai` is flagged as "rare — he has zero historical posts here." This prior knowledge prevents the model from enthusiastically assigning healthcare_ai to everything even tangentially health-related.

The `context_note` requirement is what makes this agent useful rather than trivial. Given `--idea "why leadership matters as you scale as a PM"`, a naive implementation would just return `topic_lane: pm_craft`. The mapper is expected to refine this into something like: *"Explore the specific inflection point where individual PM influence plateaways and the PM's leverage shifts from doing to enabling — use the 0-to-1 vs 1-to-10 framing from his Tata 1mg experience."* That `context_note` is what the Writer actually uses.

---

## voice_eval.md — v1.0

**Model:** `claude-haiku-4-5-20251001`  
**Temperature:** 0.0  
**Max tokens:** 600

**Variables injected:**
- `{voice_guide}` — full voice guide text
- `{seed_hooks}` — hooks from the 10 most recent posts (originality reference corpus)
- `{draft_format}` — format declared by the Writer
- `{draft_hook}` — extracted first lines of the draft
- `{draft_body}` — full post body

**What it produces:** A JSON object with `voice_match`, `hook_strength`, `originality`, `hygiene` (each 1-10) and `verdict`.

**Key difference from critic.md:** The `originality` dimension explicitly cross-references the `{seed_hooks}` corpus. A score of 1-3 means "near-paraphrase of one of the seed posts." This is the dimension that catches stylistic plagiarism — the model generating a structurally identical post to something in the corpus, just with different topic words substituted. The Critic does not have this signal.

The hygiene deduction model in `voice_eval.md` is fully enumerated with point values (−3, −2, −1) which makes it more auditable than the Critic's prose description. Both reach the same conclusions; the explicit deduction model in the Evaluator is more consistent across runs at temperature 0.0.

Max tokens is 600 because the eval suite collects `verdict` strings for display in the eval table, and sometimes the verdict is more detailed than the Critic's one-sentence format.

---

## Versioning workflow

When changing a prompt:

1. Make the change in `prompts/<name>.md`.
2. Bump the `version` field in frontmatter (e.g., `"1.0"` → `"1.1"`).
3. Run `uv run pytest tests/test_voice_match.py --run-eval -v -s`.
4. Check the output table. If `OVERALL` dropped more than 0.5 from the last baseline in `data/eval_history.jsonl`, do not ship the new version — revert or iterate.
5. If the score holds, commit. The new version string will appear in all future `posts.prompt_version` values.

The eval history in `data/eval_history.jsonl` is the audit log. Each entry records `prompt_version`, `model`, `run_at`, per-dimension averages, and per-draft detail. Established baseline at system init: `overall_avg: 8.35` (VM=7.90, HS=8.80, OR=7.60, HY=9.10).
