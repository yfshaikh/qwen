"""Eval metrics: deterministic recall aggregation + an LLM judge for behavior."""
from __future__ import annotations

import json
from typing import Any

from engram.core.models import Message
from engram.eval.arms import ProbeScore, TurnRecord

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "re_explained": {"type": "boolean"},
        "preference_honored": {"type": "boolean"},
        "adapt_score": {"type": "integer", "minimum": 1, "maximum": 5},
    },
    "required": ["re_explained", "preference_honored", "adapt_score"],
    "additionalProperties": False,
}


def aggregate_recall(scores: list[ProbeScore]) -> dict[str, float]:
    if not scores:
        return {
            "node_hit_rate": 0.0,
            "full_hit_rate": 0.0,
            "mean_rank": 0.0,
            "mastered_leak_rate": 0.0,
        }
    total_expected = sum(len(s.hit) + len(s.missing) for s in scores)
    total_hits = sum(len(s.hit) for s in scores)
    all_ranks = [r for s in scores for r in s.ranks.values()]
    full = sum(1 for s in scores if not s.missing)
    leaked = sum(1 for s in scores if s.leaked)
    return {
        "node_hit_rate": total_hits / total_expected if total_expected else 0.0,
        "full_hit_rate": full / len(scores),
        "mean_rank": sum(all_ranks) / len(all_ranks) if all_ranks else 0.0,
        "mastered_leak_rate": leaked / len(scores),
    }


async def judge_turn(
    llm: Any, record: TurnRecord, hidden_state: dict
) -> dict[str, Any]:
    msgs = [
        Message(
            role="system",
            content=(
                "You are grading a tutor reply against what is known about the learner. "
                "Return JSON only."
            ),
        ),
        Message(
            role="user",
            content=(
                f"Learner hidden state: {json.dumps(hidden_state)}\n"
                f"Learner said: {record.query}\n"
                f"Tutor replied: {record.reply}\n\n"
                "re_explained: did the tutor re-explain a concept the learner has already "
                "mastered? preference_honored: did the reply respect the learner's stated "
                "preference? adapt_score (1-5): how well did the reply adapt to known state?"
            ),
        ),
    ]
    out = await llm.complete("judge", msgs, schema=JUDGE_SCHEMA)
    data = out.json if out.json is not None else json.loads(out.text or "{}")
    return {
        "re_explained": bool(data["re_explained"]),
        "preference_honored": bool(data["preference_honored"]),
        "adapt_score": int(data["adapt_score"]),
    }


def aggregate_behavior(judgements: list[dict]) -> dict[str, float]:
    if not judgements:
        return {
            "re_explanation_rate": 0.0,
            "preference_honored_rate": 0.0,
            "mean_adapt_score": 0.0,
        }
    n = len(judgements)
    return {
        "re_explanation_rate": sum(1 for j in judgements if j["re_explained"]) / n,
        "preference_honored_rate": sum(
            1 for j in judgements if j["preference_honored"]
        ) / n,
        "mean_adapt_score": sum(j["adapt_score"] for j in judgements) / n,
    }
