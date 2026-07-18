"""Edge dedup in the Keeper link step (spec 2 §6 / known issue #5).

Relations now arrive via the dedicated edge pass (roadmap §3.1 fix #2): each
consolidation makes a main extractor call (concepts), an evidence call (fix #8,
answered inline with inert JSON here), then an edge call — so _SeqLLM queues a
[main, edge] pair per consolidation. `_extraction(relations)` builds that pair;
the reconcile behavior under test is unchanged.
"""
import json

from engram.core.engram import Engram
from engram.core.models import Completion, EdgeType, LearningEvent, Message
from tests.fakes import FakeStorage


class _OrthoEmbedder:
    """Distinct labels -> orthogonal vectors. FakeEmbedder's vectors are all
    parallel (cosine 1.0 between ANY two texts), which after fix #3 closed the
    tmp- hole would cosine-merge Limitzz and Continuity within a batch — these
    tests need two distinct nodes to hang edges between."""

    async def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 8
            v[len(t) % 8] = 1.0  # deterministic; 'Limitzz s' and 'Continuity s' differ
            out.append(v)
        return out


class _SeqLLM:
    def __init__(self, extractions: list[str]) -> None:
        self._q = [text for pair in extractions for text in pair] \
            if extractions and isinstance(extractions[0], tuple) else list(extractions)

    async def complete(self, role: str, messages: list[Message], schema=None) -> Completion:
        if role == "reflector":
            return Completion(text="no")
        if messages and "attribute assessment evidence" in messages[0].content:
            return Completion(text='{"evidence": []}')
        return Completion(text=self._q.pop(0))


def _extraction(relations: list[dict]) -> tuple[str, str]:
    main = json.dumps({
        "concepts": [
            {"label": "Limitzz", "summary": "s",
             "evidence": [{"kind": "asked_about", "content": "q"}]},
            {"label": "Continuity", "summary": "s",
             "evidence": [{"kind": "asked_about", "content": "q"}]},
        ],
        "preferences": [], "goals": [],
    })
    return main, json.dumps({"relations": relations})


async def _consolidate(llm, storage, learner="L"):
    eng = Engram(storage=storage, llm=llm, embedder=_OrthoEmbedder())
    await eng.ingest([LearningEvent(learner_id=learner, type="utterance", text="hi")])
    return await eng.consolidate(learner)


async def test_same_batch_conflicting_types_keep_strongest():
    storage = FakeStorage()
    llm = _SeqLLM([_extraction([
        {"source_label": "Limitzz", "target_label": "Continuity", "type": "relates_to"},
        {"source_label": "Continuity", "target_label": "Limitzz", "type": "prerequisite"},
    ])])
    await _consolidate(llm, storage)
    edges = [e for e in storage.edges if e.learner_id == "L"]
    assert len(edges) == 1
    assert edges[0].type == EdgeType.PREREQUISITE
    by_label = {n.label: n.id for n in await storage.get_live_nodes("L")}
    # Winning proposal was Continuity -> Limitzz (direction must stick).
    assert edges[0].source_id == by_label["Continuity"]
    assert edges[0].target_id == by_label["Limitzz"]


async def test_existing_edge_upgraded_in_place():
    storage = FakeStorage()
    llm = _SeqLLM([
        _extraction([{"source_label": "Limitzz", "target_label": "Continuity",
                      "type": "relates_to"}]),
        _extraction([{"source_label": "Continuity", "target_label": "Limitzz",
                      "type": "prerequisite"}]),
    ])
    await _consolidate(llm, storage)
    await _consolidate(llm, storage)
    edges = [e for e in storage.edges if e.learner_id == "L"]
    assert len(edges) == 1
    assert edges[0].type == EdgeType.PREREQUISITE
    by_label = {n.label: n.id for n in await storage.get_live_nodes("L")}
    assert edges[0].source_id == by_label["Continuity"]
    assert edges[0].target_id == by_label["Limitzz"]
    ops = [a["rationale"] for a in await storage.get_audit("L") if a["op"] == "link"]
    assert any("upgraded" in (r or "") for r in ops)


async def test_existing_same_type_is_noop_no_new_row():
    storage = FakeStorage()
    rel = [{"source_label": "Limitzz", "target_label": "Continuity", "type": "relates_to"}]
    llm = _SeqLLM([_extraction(rel), _extraction(rel)])
    await _consolidate(llm, storage)
    await _consolidate(llm, storage)
    edges = [e for e in storage.edges if e.learner_id == "L"]
    assert len(edges) == 1  # re-proposal did not add a duplicate row
    assert edges[0].weight == 1.0  # capped; extraction edges start at the cap


async def test_existing_same_type_below_cap_bumps_weight():
    storage = FakeStorage()
    # Pre-seed an edge below the weight cap, then re-propose the same relation.
    rel = [{"source_label": "Limitzz", "target_label": "Continuity", "type": "relates_to"}]
    llm = _SeqLLM([_extraction(rel), _extraction(rel)])
    await _consolidate(llm, storage)
    storage.edges[0].weight = 0.5
    await _consolidate(llm, storage)
    edges = [e for e in storage.edges if e.learner_id == "L"]
    assert len(edges) == 1
    assert abs(edges[0].weight - 0.6) < 1e-9


async def test_same_batch_double_proposal_bumps_weight_once():
    storage = FakeStorage()
    rel = {"source_label": "Limitzz", "target_label": "Continuity", "type": "relates_to"}
    llm = _SeqLLM([_extraction([rel]), _extraction([rel, rel])])
    await _consolidate(llm, storage)
    storage.edges[0].weight = 0.5
    # Snapshot the stored edge object identity — planner must not mutate it.
    stored = storage.edges[0]
    await _consolidate(llm, storage)
    edges = [e for e in storage.edges if e.learner_id == "L"]
    assert len(edges) == 1
    assert abs(edges[0].weight - 0.6) < 1e-9  # +0.1 once, not twice
    assert stored.weight == 0.6  # apply wrote through; in-place planner mutation avoided


class _RecordingSeqLLM(_SeqLLM):
    def __init__(self, extractions):
        super().__init__(extractions)
        self.calls: list[list[Message]] = []

    async def complete(self, role, messages, schema=None):
        if role != "reflector":
            self.calls.append(messages)
        return await super().complete(role, messages, schema)


async def test_edge_pass_sees_known_edges_and_final_labels():
    storage = FakeStorage()
    llm = _RecordingSeqLLM([
        _extraction([{"source_label": "Limitzz", "target_label": "Continuity",
                      "type": "prerequisite"}]),
        _extraction([]),
    ])
    await _consolidate(llm, storage)
    await _consolidate(llm, storage)
    # 2 consolidations x (main + evidence + edge) = 6 non-reflector calls
    assert len(llm.calls) == 6
    edge_prompts = [c[1].content for c in llm.calls
                    if "infer directed relations" in c[0].content]
    assert len(edge_prompts) == 2
    second_edge_prompt = edge_prompts[1]
    assert "RELATIONS ALREADY RECORDED" in second_edge_prompt
    assert "Limitzz --prerequisite--> Continuity" in second_edge_prompt
    assert "CONCEPTS:" in second_edge_prompt


async def test_single_concept_skips_edge_pass():
    storage = FakeStorage()
    only = json.dumps({"concepts": [{"label": "Limitzz", "summary": "s",
                                     "evidence": [{"kind": "asked_about", "content": "q"}]}],
                       "preferences": [], "goals": []})
    llm = _RecordingSeqLLM([only])  # queue holds ONE response; an edge call would pop-crash
    report = await _consolidate(llm, storage)
    assert report.nodes_created == 1
    # main + evidence (a single concept can still be assessed), NO edge call
    assert len(llm.calls) == 2
    assert not any("infer directed relations" in c[0].content for c in llm.calls)


async def test_edge_pass_failure_degrades_to_no_edges():
    storage = FakeStorage()
    main, _ = _extraction([])
    llm = _SeqLLM([main, "NOT JSON {"])
    report = await _consolidate(llm, storage)
    assert report.nodes_created == 2  # consolidation itself survived
    assert [e for e in storage.edges if e.learner_id == "L"] == []
    ops = [a["rationale"] for a in await storage.get_audit("L")]
    assert any("edge pass failed" in (r or "") for r in ops)


async def test_weaker_proposal_does_not_downgrade():
    storage = FakeStorage()
    llm = _SeqLLM([
        _extraction([{"source_label": "Limitzz", "target_label": "Continuity",
                      "type": "prerequisite"}]),
        _extraction([{"source_label": "Limitzz", "target_label": "Continuity",
                      "type": "relates_to"}]),
    ])
    await _consolidate(llm, storage)
    await _consolidate(llm, storage)
    edges = [e for e in storage.edges if e.learner_id == "L"]
    assert len(edges) == 1
    assert edges[0].type == EdgeType.PREREQUISITE
