"""Voice-match eval suite.

Runs WriterAgent on 5 fixed prompts, scores each draft with EvaluatorAgent,
logs to data/eval_history.jsonl, and asserts no regression vs prior run.

Usage:
    pytest --run-eval tests/test_voice_match.py -v -s
"""
import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import pytest

from src.agents.evaluator import EvalScore, EvaluatorAgent, EvaluatorInput
from src.agents.writer import WriterAgent, WriterInput
from src.brain.posts import list_posts
from src.brain.voice import load_voice_guide
from src.config import settings

EVAL_HISTORY_PATH = Path("data/eval_history.jsonl")
FIXTURES_PATH = Path("tests/fixtures/voice_eval_prompts.json")
REGRESSION_THRESHOLD = 0.5


def _load_prompts() -> list[dict[str, str]]:
    return json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _last_baseline() -> dict[str, Any] | None:
    if not EVAL_HISTORY_PATH.exists():
        return None
    lines = [ln for ln in EVAL_HISTORY_PATH.read_text(encoding="utf-8").strip().splitlines() if ln]
    return json.loads(lines[-1]) if lines else None


def _append_result(record: dict[str, Any]) -> None:
    EVAL_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVAL_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _format_table(per_draft: list[dict[str, Any]]) -> str:
    rows = [f"  {'topic':<30} {'fmt':<12} {'VM':>3} {'HS':>3} {'OR':>3} {'HY':>3} {'AVG':>5}"]
    rows.append("  " + "-" * 60)
    for d in per_draft:
        label = f"{d['sub_topic'][:28]}"
        rows.append(
            f"  {label:<30} {d['format']:<12} "
            f"{d['voice_match']:>3} {d['hook_strength']:>3} "
            f"{d['originality']:>3} {d['hygiene']:>3} "
            f"{d['average']:>5.2f}"
        )
    return "\n".join(rows)


@pytest.mark.eval
def test_voice_match_suite() -> None:
    prompts = _load_prompts()
    voice_guide = load_voice_guide()
    seed_hooks = "\n".join(
        f"- {p.hook.splitlines()[0]!r}"
        for p in list_posts(settings.db_path, limit=10)
    )

    writer = WriterAgent()
    evaluator = EvaluatorAgent()

    prior = _last_baseline()

    all_scores: list[EvalScore] = []
    per_draft: list[dict[str, Any]] = []
    last_writer_result = None

    for prompt_data in prompts:
        writer_input = WriterInput(**prompt_data)  # type: ignore[arg-type]
        writer_result = writer.run(writer_input)
        last_writer_result = writer_result

        for draft in writer_result.drafts:
            score = evaluator.run(
                EvaluatorInput(
                    draft=draft,
                    voice_guide=voice_guide,
                    seed_hooks=seed_hooks,
                )
            )
            all_scores.append(score)
            per_draft.append(
                {
                    "topic_lane": prompt_data["topic_lane"],
                    "sub_topic": prompt_data["sub_topic"],
                    "format": draft.format,
                    "hook": draft.hook[:80],
                    "voice_match": score.voice_match,
                    "hook_strength": score.hook_strength,
                    "originality": score.originality,
                    "hygiene": score.hygiene,
                    "average": round(score.average, 2),
                    "verdict": score.verdict,
                }
            )

    assert last_writer_result is not None
    prompt_version = last_writer_result.prompt_version
    model = last_writer_result.model

    avg_vm = mean(s.voice_match for s in all_scores)
    avg_hs = mean(s.hook_strength for s in all_scores)
    avg_or = mean(s.originality for s in all_scores)
    avg_hy = mean(s.hygiene for s in all_scores)
    overall = mean(s.average for s in all_scores)

    record: dict[str, Any] = {
        "run_at": datetime.now(tz=UTC).isoformat(),
        "prompt_version": prompt_version,
        "model": model,
        "n_prompts": len(prompts),
        "n_drafts": len(all_scores),
        "avg_voice_match": round(avg_vm, 2),
        "avg_hook_strength": round(avg_hs, 2),
        "avg_originality": round(avg_or, 2),
        "avg_hygiene": round(avg_hy, 2),
        "overall_avg": round(overall, 2),
        "per_draft": per_draft,
    }
    _append_result(record)

    print(f"\n{'=' * 62}")
    print(f"Voice eval  prompt_v={prompt_version}  model={model}  drafts={len(all_scores)}")
    print("  VM=voice_match  HS=hook_strength  OR=originality  HY=hygiene")
    print(_format_table(per_draft))
    print(f"{'─' * 62}")
    print(f"  Averages:  VM={avg_vm:.2f}  HS={avg_hs:.2f}  OR={avg_or:.2f}  HY={avg_hy:.2f}  OVERALL={overall:.2f}")
    if prior and prior.get("overall_avg"):
        print(f"  Baseline:  {prior['overall_avg']:.2f}  (run_at={prior['run_at'][:10]})")
    print(f"{'=' * 62}")

    if prior and prior.get("overall_avg"):
        prior_avg = float(prior["overall_avg"])
        assert overall >= prior_avg - REGRESSION_THRESHOLD, (
            f"Voice score regressed: {overall:.2f} vs baseline {prior_avg:.2f} "
            f"(threshold −{REGRESSION_THRESHOLD}). "
            f"Do not bump prompt version until score recovers."
        )
