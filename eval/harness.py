"""Deterministic ablation harness: graph memory vs. a last-N-events baseline.

Runs the SAME scripted multi-session learner arc through two arms and compares a
pair of deterministic metrics:

* **Memory arm** -- ingest each session's events, ``consolidate()`` at session
  end (the graph synthesizes mastery and decays old salience). At probe time it
  calls ``recall(learner, concept)`` and inspects the returned subgraph: a
  concept that surfaces with ``mastery >= mastery_threshold`` is treated as
  known, so the tutor SKIPS re-explanation.
* **Baseline arm** -- no consolidation. "Context" is the last ``baseline_window``
  raw events. The tutor re-explains a concept UNLESS that window still holds
  explicit mastery evidence for it. Because later sessions push earlier mastery
  evidence out of the window, the baseline re-explains mastered-but-old concepts;
  memory does not.

Everything is offline and deterministic: a scripted ``FakeLLM`` returns each
session's canned extraction in order (so the Keeper never reasons), and the
``HashingEmbedder`` gives reproducible vectors for linking + recall.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engram.adapters.llm.embeddings import HashingEmbedder
from engram.adapters.storage.memory import InMemoryStorage
from engram.core.models import Completion, LearningEvent, Message
from engram.core.service import EngramService
from tests.fakes import FakeLLM

# Embedding width for the harness. Small + fixed -> fast and deterministic.
EVAL_DIM = 128

# Default scenario shipped with the harness.
DEFAULT_SCENARIO = Path(__file__).parent / "scenarios" / "derivatives.yaml"


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ArmResult:
    """One arm's tutor decisions + the metrics derived from them."""

    name: str
    # concept -> would the tutor re-explain it at probe time?
    reexplain: dict[str, bool] = field(default_factory=dict)
    # concept -> did this arm's context surface the prior concept at all?
    recall_hit: dict[str, bool] = field(default_factory=dict)
    # concept -> mastery the arm believed (for reporting; None if unknown)
    mastery: dict[str, float | None] = field(default_factory=dict)

    @property
    def reexplain_rate_of_mastered(self) -> float:
        """Fraction of MASTERED probe concepts this arm would re-explain."""
        vals = [self.reexplain[c] for c in self._mastered]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def prior_session_recall_hits(self) -> int:
        """Count of probes whose prior concept this arm's context surfaced."""
        return sum(1 for hit in self.recall_hit.values() if hit)

    # populated by the harness so the rate property knows the mastered set.
    _mastered: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvalResult:
    learner_id: str
    persona: str
    mastery_threshold: float
    baseline_window: int
    probes: list[dict[str, Any]]
    memory: ArmResult
    baseline: ArmResult

    @property
    def mastered_concepts(self) -> list[str]:
        return [p["concept"] for p in self.probes if p.get("mastered")]

    def as_dict(self) -> dict[str, Any]:
        """Plain-dict view (JSON-friendly) for logging or assertions."""

        def arm(a: ArmResult) -> dict[str, Any]:
            return {
                "name": a.name,
                "reexplain": dict(a.reexplain),
                "recall_hit": dict(a.recall_hit),
                "mastery": dict(a.mastery),
                "reexplain_rate_of_mastered": a.reexplain_rate_of_mastered,
                "prior_session_recall_hits": a.prior_session_recall_hits,
            }

        return {
            "learner_id": self.learner_id,
            "persona": self.persona,
            "mastery_threshold": self.mastery_threshold,
            "baseline_window": self.baseline_window,
            "mastered_concepts": self.mastered_concepts,
            "memory": arm(self.memory),
            "baseline": arm(self.baseline),
        }


# --------------------------------------------------------------------------- #
# Scenario loading
# --------------------------------------------------------------------------- #
def load_scenario(path: str | Path | None = None) -> dict[str, Any]:
    """Load a scenario YAML (defaults to the bundled derivatives arc)."""
    p = Path(path) if path else DEFAULT_SCENARIO
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"scenario {p} did not parse to a mapping")
    data.setdefault("mastery_threshold", 0.6)
    data.setdefault("baseline_window", 10)
    data.setdefault("persona", "")
    return data


def _events(raw_events: list[dict[str, Any]], learner_id: str) -> list[LearningEvent]:
    """Build LearningEvents from a session's raw event dicts."""
    out: list[LearningEvent] = []
    for e in raw_events:
        out.append(
            LearningEvent(
                learner_id=learner_id,
                type=str(e.get("type", "utterance")),
                text=e.get("text"),
                refs=dict(e.get("refs") or {}),
                signals=dict(e.get("signals") or {}),
            )
        )
    return out


def _scripted_llm(extractions: list[dict[str, Any]]) -> FakeLLM:
    """A FakeLLM whose extractor returns each session's extraction in order.

    Mirrors the pattern in tests/test_keeper.py + tests/test_service.py: the
    extractor role yields the next queued payload as ``Completion.json`` so the
    Keeper's one LLM call is fully canned; the embedder is the deterministic
    HashingEmbedder so linking + recall are reproducible.
    """
    seq = iter(extractions)

    def responder(role: str, messages: list[Message], schema: dict | None) -> Completion:
        if role == "extractor":
            return Completion(json=next(seq), model="fake-extractor", usage={"total_tokens": 7})
        return Completion(text="ok")

    return FakeLLM(responder=responder, embedder=HashingEmbedder(EVAL_DIM))


# --------------------------------------------------------------------------- #
# Tutor policies (the mechanical, deterministic decision per arm)
# --------------------------------------------------------------------------- #
def _word_in_text(word: str, text: str | None) -> bool:
    """True if ``word`` appears as a whole word (case-insensitive) in ``text``."""
    if not text:
        return False
    return re.search(rf"\b{re.escape(word.lower())}\b", text.lower()) is not None


def _event_references(event: LearningEvent, concept: str) -> bool:
    """Does a raw event mention this concept (by signal tag or in its text)?"""
    if str(event.signals.get("concept", "")).lower() == concept.lower():
        return True
    return _word_in_text(concept, event.text)


def _event_is_mastery_evidence(
    event: LearningEvent, concept: str, threshold: float
) -> bool:
    """A raw event is mastery evidence for C iff it tags C with mastery>=thresh."""
    if str(event.signals.get("concept", "")).lower() != concept.lower():
        return False
    mastery = event.signals.get("mastery")
    try:
        return mastery is not None and float(mastery) >= threshold
    except (TypeError, ValueError):
        return False


def memory_should_reexplain(
    concept: str, subgraph: dict[str, Any], threshold: float
) -> tuple[bool, float | None, bool]:
    """Memory-arm policy from a recall subgraph.

    Returns ``(should_reexplain, mastery, surfaced)``. The tutor SKIPS the
    re-explanation when recall surfaces a node for ``concept`` whose synthesized
    ``mastery`` is at or above ``threshold``.
    """
    node = next(
        (
            n
            for n in subgraph.get("nodes", [])
            if str(n.get("label", "")).lower() == concept.lower()
        ),
        None,
    )
    if node is None:
        return True, None, False  # not in memory -> re-explain
    mastery = node.get("mastery")
    surfaced = True
    if mastery is None:
        return True, None, surfaced
    return (float(mastery) < threshold), float(mastery), surfaced


def baseline_should_reexplain(
    concept: str, window: list[LearningEvent], threshold: float
) -> tuple[bool, float | None, bool]:
    """Baseline-arm policy from the last-N raw-event window.

    Returns ``(should_reexplain, mastery, surfaced)``. The tutor re-explains
    UNLESS the window still contains explicit mastery evidence for the concept.
    ``surfaced`` is whether the window references the concept at all.
    """
    surfaced = any(_event_references(e, concept) for e in window)
    mastery_events = [
        e for e in window if _event_is_mastery_evidence(e, concept, threshold)
    ]
    if mastery_events:
        # Best (max) mastery signal in the window, for reporting.
        best = max(float(e.signals["mastery"]) for e in mastery_events)
        return False, best, surfaced
    return True, None, surfaced


# --------------------------------------------------------------------------- #
# The two arms
# --------------------------------------------------------------------------- #
async def _run_memory_arm(scenario: dict[str, Any]) -> ArmResult:
    """Ingest + consolidate per session, then probe via recall()."""
    learner_id = scenario["learner_id"]
    threshold = float(scenario["mastery_threshold"])
    sessions = scenario["sessions"]

    llm = _scripted_llm([s["extraction"] for s in sessions])
    svc = EngramService(InMemoryStorage(), llm, embed_dim=EVAL_DIM)

    for session in sessions:
        await svc.ingest(_events(session["events"], learner_id))
        await svc.consolidate(learner_id)

    arm = ArmResult(name="memory")
    arm._mastered = [p["concept"] for p in scenario["probes"] if p.get("mastered")]
    for probe in scenario["probes"]:
        concept = probe["concept"]
        result = await svc.recall(learner_id, concept)
        reexplain, mastery, surfaced = memory_should_reexplain(
            concept, result.subgraph, threshold
        )
        arm.reexplain[concept] = reexplain
        arm.recall_hit[concept] = surfaced
        arm.mastery[concept] = mastery
    return arm


async def _run_baseline_arm(scenario: dict[str, Any]) -> ArmResult:
    """No consolidation; context is the last-N raw events across all sessions."""
    learner_id = scenario["learner_id"]
    threshold = float(scenario["mastery_threshold"])
    window_size = int(scenario["baseline_window"])
    sessions = scenario["sessions"]

    # The naive agent just accumulates raw events, then keeps the last N.
    all_events: list[LearningEvent] = []
    for session in sessions:
        all_events.extend(_events(session["events"], learner_id))
    window = all_events[-window_size:]

    arm = ArmResult(name=f"baseline(last_{window_size})")
    arm._mastered = [p["concept"] for p in scenario["probes"] if p.get("mastered")]
    for probe in scenario["probes"]:
        concept = probe["concept"]
        reexplain, mastery, surfaced = baseline_should_reexplain(
            concept, window, threshold
        )
        arm.reexplain[concept] = reexplain
        arm.recall_hit[concept] = surfaced
        arm.mastery[concept] = mastery
    return arm


async def run_eval(scenario: dict[str, Any] | str | Path | None = None) -> EvalResult:
    """Run both arms over a scenario and return the comparison.

    ``scenario`` may be an already-loaded dict, a path to a YAML file, or None
    (the bundled derivatives arc).
    """
    if not isinstance(scenario, dict):
        scenario = load_scenario(scenario)

    memory = await _run_memory_arm(scenario)
    baseline = await _run_baseline_arm(scenario)
    return EvalResult(
        learner_id=scenario["learner_id"],
        persona=scenario.get("persona", ""),
        mastery_threshold=float(scenario["mastery_threshold"]),
        baseline_window=int(scenario["baseline_window"]),
        probes=list(scenario["probes"]),
        memory=memory,
        baseline=baseline,
    )
