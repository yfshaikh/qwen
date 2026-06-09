"""Deterministic ablation harness: Engram memory arm vs last-N-events baseline.

Loads a YAML scenario (sessions of raw events + the canned extraction the
Memory Keeper should produce per session), replays it through:

- **memory arm** — ``EngramService`` over ``InMemoryStorage`` with a scripted
  ``FakeLLM`` (canned extractor payloads, ``HashingEmbedder`` vectors). Each
  session is ingested then consolidated; probes call ``recall()`` and inspect
  the structured subgraph.
- **baseline arm** — no consolidation; "context" is simply the last N raw
  events. It re-explains a concept unless explicit mastery evidence for it is
  still inside that window.

Everything is offline and deterministic: no network, no LLM, no database.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from engram.adapters.llm.embeddings import HashingEmbedder
from engram.adapters.storage.memory import InMemoryStorage
from engram.core.models import Completion, LearningEvent, Message
from engram.core.service import EngramService
from tests.fakes import FakeLLM

DEFAULT_SCENARIO = Path(__file__).resolve().parent / "scenarios" / "derivatives.yaml"

# Embedding dim for the deterministic HashingEmbedder (matches the unit tests'
# small-but-collision-safe choice for a handful of concept labels).
EMBED_DIM = 256


# --------------------------------------------------------------------------- #
# Results model
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ProbeDecision:
    """Both arms' decisions for one probed concept."""

    concept: str
    mastered: bool  # scenario ground truth: was this mastered in a prior session?
    memory_reexplained: bool
    baseline_reexplained: bool
    memory_hit: bool  # memory arm surfaced the concept in its recall context
    baseline_hit: bool  # baseline window mentions the concept at all


@dataclass(slots=True)
class ArmMetrics:
    arm: str
    reexplain_rate_of_mastered: float  # lower is better
    prior_session_recall_hits: int  # higher is better (out of total_probes)


@dataclass(slots=True)
class EvalResults:
    scenario: str
    learner_id: str
    mastery_threshold: float
    baseline_window: int
    total_probes: int
    mastered_probes: int
    probes: list[ProbeDecision]
    memory: ArmMetrics
    baseline: ArmMetrics


# --------------------------------------------------------------------------- #
# Mechanical tutor policies (the thing under ablation)
# --------------------------------------------------------------------------- #
def _find_node(nodes: list[dict[str, Any]], concept: str) -> dict[str, Any] | None:
    """The recalled subgraph node whose label matches the probe concept."""
    wanted = concept.strip().lower()
    for node in nodes:
        if str(node.get("label", "")).strip().lower() == wanted:
            return node
    return None


def memory_should_reexplain(
    nodes: list[dict[str, Any]], concept: str, threshold: float
) -> bool:
    """Memory arm: skip re-explaining iff recall surfaces the concept with
    ``mastery >= threshold``; otherwise (absent or low/unknown mastery) re-explain."""
    node = _find_node(nodes, concept)
    if node is None:
        return True
    mastery = node.get("mastery")
    return not (isinstance(mastery, (int, float)) and mastery >= threshold)


def memory_context_hit(nodes: list[dict[str, Any]], concept: str) -> bool:
    """Memory arm surfaced the probe concept at all."""
    return _find_node(nodes, concept) is not None


def _signal_mastery(event: LearningEvent, concept: str) -> float | None:
    signals = event.signals or {}
    if str(signals.get("concept", "")).strip().lower() != concept.strip().lower():
        return None
    mastery = signals.get("mastery")
    return float(mastery) if isinstance(mastery, (int, float)) else None


def baseline_should_reexplain(
    window: list[LearningEvent], concept: str, threshold: float
) -> bool:
    """Baseline arm: re-explain UNLESS the last-N window still contains explicit
    mastery evidence (``signals.concept == X and signals.mastery >= threshold``)."""
    for event in window:
        mastery = _signal_mastery(event, concept)
        if mastery is not None and mastery >= threshold:
            return False
    return True


def baseline_context_hit(window: list[LearningEvent], concept: str) -> bool:
    """Baseline arm surfaced the probe concept at all (text or signals)."""
    wanted = concept.strip().lower()
    for event in window:
        if wanted in (event.text or "").lower():
            return True
        if str((event.signals or {}).get("concept", "")).strip().lower() == wanted:
            return True
    return False


# --------------------------------------------------------------------------- #
# Scenario loading + scripted LLM
# --------------------------------------------------------------------------- #
def load_scenario(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        scenario = yaml.safe_load(fh)
    if not isinstance(scenario, dict):
        raise ValueError(f"scenario file {path} did not parse to a mapping")
    return scenario


def _scripted_llm(extractions: list[dict[str, Any]]) -> FakeLLM:
    """FakeLLM whose extractor returns each session's canned payload in order."""
    seq = iter(extractions)

    def responder(role: str, messages: list[Message], schema: dict | None) -> Completion:
        if role == "extractor":
            return Completion(
                json=copy.deepcopy(next(seq)), model="scripted", usage={"total_tokens": 0}
            )
        return Completion(text="ok")

    return FakeLLM(responder=responder, embedder=HashingEmbedder(EMBED_DIM))


def _event(learner_id: str, raw: dict[str, Any]) -> LearningEvent:
    return LearningEvent(
        learner_id=learner_id,
        type=str(raw.get("type", "utterance")),
        text=raw.get("text"),
        signals=dict(raw.get("signals") or {}),
    )


# --------------------------------------------------------------------------- #
# The harness
# --------------------------------------------------------------------------- #
async def run_eval(scenario_path: str | Path = DEFAULT_SCENARIO) -> EvalResults:
    """Run both arms over the scenario and compute the ablation metrics."""
    scenario = load_scenario(scenario_path)
    learner_id = str(scenario["learner_id"])
    threshold = float(scenario.get("mastery_threshold", 0.6))
    window_n = int(scenario.get("baseline_window", 10))
    budget = int(scenario.get("recall_budget", 600))
    sessions: list[dict[str, Any]] = scenario["sessions"]
    probes: list[dict[str, Any]] = scenario["probes"]

    # Memory arm: ingest each session, consolidate at session end.
    llm = _scripted_llm([session["extraction"] for session in sessions])
    service = EngramService(InMemoryStorage(), llm, embed_dim=EMBED_DIM)

    all_events: list[LearningEvent] = []
    for session in sessions:
        events = [_event(learner_id, raw) for raw in session["events"]]
        await service.ingest(events)
        await service.consolidate(learner_id)
        all_events.extend(events)

    # Baseline arm: no consolidation — context is just the last N raw events.
    window = all_events[-window_n:]

    decisions: list[ProbeDecision] = []
    for probe in probes:
        concept = str(probe["concept"])
        mastered = bool(probe["mastered"])
        recall = await service.recall(learner_id, concept, budget=budget)
        nodes = recall.subgraph.get("nodes", [])
        decisions.append(
            ProbeDecision(
                concept=concept,
                mastered=mastered,
                memory_reexplained=memory_should_reexplain(nodes, concept, threshold),
                baseline_reexplained=baseline_should_reexplain(window, concept, threshold),
                memory_hit=memory_context_hit(nodes, concept),
                baseline_hit=baseline_context_hit(window, concept),
            )
        )

    mastered_probes = [d for d in decisions if d.mastered]

    def _rate(flags: list[bool]) -> float:
        return (sum(flags) / len(flags)) if flags else 0.0

    memory = ArmMetrics(
        arm="memory",
        reexplain_rate_of_mastered=_rate([d.memory_reexplained for d in mastered_probes]),
        prior_session_recall_hits=sum(d.memory_hit for d in decisions),
    )
    baseline = ArmMetrics(
        arm="baseline",
        reexplain_rate_of_mastered=_rate([d.baseline_reexplained for d in mastered_probes]),
        prior_session_recall_hits=sum(d.baseline_hit for d in decisions),
    )
    return EvalResults(
        scenario=str(scenario.get("name", Path(scenario_path).stem)),
        learner_id=learner_id,
        mastery_threshold=threshold,
        baseline_window=window_n,
        total_probes=len(decisions),
        mastered_probes=len(mastered_probes),
        probes=decisions,
        memory=memory,
        baseline=baseline,
    )
