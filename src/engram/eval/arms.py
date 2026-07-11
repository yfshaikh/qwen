"""Eval arms. Recall-probe arm = deterministic tuning signal; behavior arm
(Task 6) = ON-vs-baseline headline. Scoring is matched by case-insensitive
substring so 'Pass calculus final' matches 'Pass calculus final next month'."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engram.core.recall import Recall, RecallWeights
from engram.core.tokens import heuristic_token_count
from engram.eval.scenario import Probe
from engram.tutor.prompt import compose


@dataclass(slots=True)
class ProbeScore:
    query: str
    hit: list[str]
    missing: list[str]
    ranks: dict[str, int]
    leaked: bool


def _rank_of(expected: str, ordered: list[str]) -> int | None:
    needle = expected.lower()
    for i, label in enumerate(ordered, start=1):
        if needle in label.lower():
            return i
    return None


def score_probe(ordered_labels: list[str], probe: Probe) -> ProbeScore:
    penalty = len(ordered_labels) + 1
    hit: list[str] = []
    missing: list[str] = []
    ranks: dict[str, int] = {}
    for exp in probe.expect_nodes:
        r = _rank_of(exp, ordered_labels)
        ranks[exp] = r if r is not None else penalty
        (hit if r is not None else missing).append(exp)
    leaked = any(_rank_of(m, ordered_labels) == 1 for m in probe.mastered_not_expected)
    return ProbeScore(query=probe.query, hit=hit, missing=missing, ranks=ranks, leaked=leaked)


async def run_recall_arm(
    storage: Any,
    embedder: Any,
    learner_id: str,
    probes: list[Probe],
    weights: RecallWeights,
    *,
    seed_k: int = 8,
    hops: int = 2,
    fanout: int = 10,
    budget: int = 800,
) -> list[tuple[Probe, ProbeScore]]:
    recall = Recall(
        storage,
        embedder,
        heuristic_token_count,
        weights,
        seed_k=seed_k,
        hops=hops,
        fanout=fanout,
    )
    out = []
    for probe in probes:
        res = await recall.run(learner_id, probe.query, budget)
        labels = [n["label"] for n in res.subgraph["nodes"]]
        out.append((probe, score_probe(labels, probe)))
    return out


_MAX_TURNS = 10  # ponytail: mirror Tutor.MAX_TURNS; promote to setting if convos grow


@dataclass(slots=True)
class TurnRecord:
    query: str
    reply: str
    context: str


def format_baseline_context(history: list[dict], n: int = 10) -> str:
    recent = history[-n:]
    return "\n".join(f"{h['role']}: {h['content']}" for h in recent)


async def _tutor_reply(eng: Any, context: str, history: list[dict]) -> str:
    prompt = compose(context, history[-_MAX_TURNS:])
    out = await eng.llm.complete("tutor", prompt)
    return out.text or ""


async def run_behavior_arm(
    eng: Any,
    learner_turns: list[str],
    learner_id: str,
    mode: str,
    *,
    budget: int = 800,
    n: int = 10,
) -> list[TurnRecord]:
    if mode not in ("on", "baseline"):
        raise ValueError(f"mode must be 'on' or 'baseline', got {mode!r}")
    history: list[dict] = []
    records: list[TurnRecord] = []
    for turn in learner_turns:
        history.append({"role": "user", "content": turn})
        if mode == "on":
            context = (await eng.recall(learner_id, turn, budget)).text_block
        else:
            context = format_baseline_context(history, n)
        reply = await _tutor_reply(eng, context, history)
        history.append({"role": "assistant", "content": reply})
        records.append(TurnRecord(query=turn, reply=reply, context=context))
    return records
