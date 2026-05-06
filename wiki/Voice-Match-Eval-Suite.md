# Voice-Match Eval Suite

The most important piece of infrastructure in this system, after the brain itself.

LLMs are stochastic. You cannot write a unit test that asserts `draft.body == expected_text`. But you can test whether the distribution of outputs produced by the WriterAgent has drifted away from the voice profile. That is what the eval suite does.

**File:** `tests/test_voice_match.py`  
**Run it:** `uv run pytest tests/test_voice_match.py --run-eval -v -s`  
**Eval history:** `data/eval_history.jsonl`  
**Fixtures:** `tests/fixtures/voice_eval_prompts.json`

---

## What it does

The suite runs the full WriterAgent on 5 fixed input prompts and then uses the EvaluatorAgent (Claude Haiku at temperature 0.0) to score each output on 4 dimensions. The scores are aggregated, compared against the last run's baseline, and the test fails if the overall average dropped more than 0.5.

The 5 fixed prompts cover different lanes and sub_topics. They are fixed — they do not change run to run. This is what makes the comparison meaningful. If you change the prompts between runs, you are comparing different inputs, not measuring drift.

---

## The dimensions

**`voice_match` (1–10):** Does this post sound unmistakably like Animesh? The rubric in `voice_eval.md` is specific:

- 10: Unmistakably him — specific hook type, PM lens on real details, ends with a concrete answerable question tied to the reader's experience
- 7–9: Mostly his voice but has a generic sentence or two
- 4–6: Structurally correct but reads like a template
- 1–3: Generic LinkedIn content with no fingerprint

**`hook_strength` (1–10):** Does the opening earn the reader's attention? Three valid hook types:

1. Confession/admission: "I was wrong about something", "I messed this up"
2. Knowing question implying the author has seen something others have not
3. Grounded scene that pulls the reader in: "Last week a founder told me...", "I just noticed..."

Opening with a thesis statement, a generic opener ("In today's world", "As a PM, I often think"), or an empty motivational line scores 1–3 regardless of the content's quality.

**`originality` (1–10):** Is this a fresh angle, or a structural paraphrase of something already in the corpus? The EvaluatorAgent is given `seed_hooks` — hooks from the 10 most recent real posts — and explicitly asked to score against this reference:

- 10: Fresh angle and specific insight not present in the seed hooks
- 7–9: Familiar format, genuinely new angle
- 4–6: Similar setup/punchline to an existing post
- 1–3: Near-paraphrase of one of the seed posts

This is the dimension the production CriticAgent does not have. The Critic does not see the seed corpus — it only evaluates the draft in isolation. The Evaluator is the one that catches structural plagiarism.

**`hygiene` (1–10):** Starts at 10, deducts per violation:

| Violation | Deduction |
|---|---|
| Hashtags inside post body | −3 |
| Any forbidden phrase used | −3 per phrase |
| Word count clearly outside 150–300 words | −2 |
| Vague closing question | −2 |
| More than one emoji in body | −1 |
| Self-promotion CTA ("follow me for more") | −1 |

Forbidden phrases: `delve`, `tapestry`, `game-changer`, `paradigm shift`, `in today's fast-paced world`, `I hope this resonates`, `in conclusion`, `at the end of the day`, `let that sink in`, `synergy`.

---

## The regression gate

After scoring all drafts across all 5 prompts, the suite computes:

```python
overall = mean(score.average for score in all_scores)
```

It then checks `data/eval_history.jsonl` for the most recent prior run. If `overall < prior_avg - 0.5`, the test fails with:

```
AssertionError: Voice score regressed: 7.85 vs baseline 8.35
(threshold −0.5). Do not bump prompt version until score recovers.
```

This is a hard gate. If the score regresses, the new prompt version does not ship. You revert or iterate.

The threshold is 0.5, not 0.1, because LLM output is genuinely stochastic — run-to-run variance on the same prompt can be 0.2–0.3 points. A threshold tight enough to catch every small regression would also fire on noise. 0.5 is calibrated to catch meaningful drift while ignoring natural variation.

The baseline is appended, not overwritten. Every run is a new line in `eval_history.jsonl`. The test always compares against the last line. This means the baseline naturally advances as the system improves — but it also means a single bad run becomes the new baseline if you do not catch it. Run the eval manually when in doubt; do not trust a single automated run as the definitive baseline.

---

## The eval history record

Each run appends a JSON line to `data/eval_history.jsonl`:

```json
{
  "run_at": "2026-05-03T14:22:11+00:00",
  "prompt_version": "1.0",
  "model": "claude-opus-4-7",
  "n_prompts": 5,
  "n_drafts": 10,
  "avg_voice_match": 7.90,
  "avg_hook_strength": 8.80,
  "avg_originality": 7.60,
  "avg_hygiene": 9.10,
  "overall_avg": 8.35,
  "per_draft": [
    {
      "topic_lane": "ai_for_pms",
      "sub_topic": "agentic_systems_for_pms",
      "format": "framework",
      "hook": "I spent 3 months building an internal agent at 1mg...",
      "voice_match": 8,
      "hook_strength": 9,
      "originality": 7,
      "hygiene": 9,
      "average": 8.25,
      "verdict": "Strong Tata 1mg grounding and PM lens — the closing question is slightly broad"
    }
  ]
}
```

The `per_draft` array is the most actionable part of the record. If `voice_match` is consistently lower than `hook_strength` across multiple runs, the Writer prompt needs more specific voice guidance, not better hook instructions. If `originality` is dropping run over run, the corpus may be repeating structural patterns that the model is learning to mimic.

---

## Established baseline

System init baseline (first run, May 2026):

| Dimension | Score |
|---|---|
| voice_match | 7.90 |
| hook_strength | 8.80 |
| originality | 7.60 |
| hygiene | 9.10 |
| **overall** | **8.35** |

Regression gate fires below **7.85**.

The high hygiene score (9.10) reflects that the Writer prompt's mechanical constraints (word count, no hashtags, no forbidden phrases) are well-specified and the model reliably follows them. The lower originality score (7.60) is expected — the corpus of 47 seed posts creates structural patterns the model has absorbed, and some drift toward familiar formats is inevitable. Improving originality without losing voice fidelity is the main tension to manage in future prompt iterations.

---

## When to run the eval suite

**Before every prompt version bump.** This is mandatory. If you change `prompts/writer.md` and do not run the eval, you have no basis for claiming the change did not regress voice quality. The eval takes roughly 3–5 minutes and costs approximately $0.10–0.15 in API calls (5 prompts × 2 drafts × 1 Writer call + 10 Evaluator calls).

**After changing the voice guide.** `data/voice_guide.md` is injected into the Writer prompt. A change to the voice guide is effectively a change to the prompt. Run the eval.

**After a model version change.** If Anthropic updates `claude-opus-4-7` or you switch the Writer to a different model, run the eval before using the new model in production.

**Not in CI.** The eval suite is marked `@pytest.mark.eval` and only runs with `--run-eval`. It should not run in a standard `pytest` invocation — it costs money and time on every push. The gate is a human-initiated check before shipping prompt changes, not an automated per-commit gate.

---

## Why this matters more than standard unit tests

Consider the alternative: unit tests on agent output. You would need to either:

1. Mock the LLM — which tests nothing about actual output quality, only that the code calls the API correctly.
2. Record expected outputs and assert equality — which fails on every legitimate improvement (prompt gets better, drafts change, test fails).
3. Test structural properties only (is the output valid JSON? does it have two drafts?) — which is useful but catches zero voice quality issues.

The eval suite is the correct answer to "how do I test an LLM agent?" You cannot test the output. You can test whether the output's quality distribution is stable across a fixed set of inputs. That is what this does.

The EvaluatorAgent as judge pattern (using a separate LLM call to score LLM output) is imperfect — a judge model has its own biases, and two models agreeing does not mean the output is actually good. But it is far more useful than no gate at all, and the biases are stable across runs — a consistent judge still catches regression.
