import json
from datetime import datetime, timedelta, timezone

from engram.core.keeper import Keeper, KeeperParams
from engram.core.models import Node, NodeType
from tests.fakes import FakeLLM, FakeStorage


class _StubEmbedder:
    """Maps text substrings to fixed vectors for deterministic linking."""

    def __init__(self, table, default):
        self.table = table
        self.default = default

    async def embed(self, texts):
        out = []
        for t in texts:
            vec = self.default
            for key, v in self.table.items():
                if key in t:
                    vec = v
            out.append(list(vec))
        return out


FIXED_NOW = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)


def _clock():
    return FIXED_NOW


def _extraction(concepts):
    return json.dumps({"concepts": concepts, "preferences": [], "goals": [], "relations": []})


async def _ingest(fs, learner):
    from engram.core.models import LearningEvent

    return await fs.insert_events(
        [LearningEvent(learner_id=learner, type="utterance", text="t")]
    )


def _keeper(fs, llm, embedder):
    return Keeper(fs, llm, embedder, KeeperParams(), clock=_clock)


async def test_creates_new_node_with_mastery_from_evidence():
    fs = FakeStorage()
    await _ingest(fs, "a")
    llm = FakeLLM(canned_text=_extraction(
        [{"label": "Limits", "summary": "s",
          "evidence": [{"kind": "quiz_correct", "content": "ok", "importance": 0.8}]}]
    ))
    emb = _StubEmbedder({"Limits": [1.0, 0.0]}, default=[0.0, 1.0])
    report = await _keeper(fs, llm, emb).consolidate("a")

    assert report.nodes_created == 1
    node = next(iter(fs.nodes.values()))
    assert node.label == "Limits"
    assert node.mastery == 1.0          # first obs from quiz_correct
    assert node.confidence == 0.4       # 0.3 -> +0.1
    assert (await fs.get_pending_events("a")) == []  # watermarked


async def test_links_to_existing_above_tau_high():
    fs = FakeStorage()
    existing = await fs.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="Limits",
             mastery=0.5, salience=0.5, confidence=0.5, embedding=[1.0, 0.0],
             last_seen_at=FIXED_NOW)
    )
    await _ingest(fs, "a")
    llm = FakeLLM(canned_text=_extraction(
        [{"label": "Limits", "summary": "s",
          "evidence": [{"kind": "quiz_correct", "content": "ok"}]}]
    ))
    emb = _StubEmbedder({"Limits": [1.0, 0.0]}, default=[0.0, 1.0])
    report = await _keeper(fs, llm, emb).consolidate("a")

    assert report.nodes_created == 0          # attached, not created
    assert len(fs.nodes) == 1
    assert fs.nodes[existing].mastery == 0.3 * 1.0 + 0.7 * 0.5  # EWMA blend


async def test_contradiction_logs_resolve_audit():
    fs = FakeStorage()
    await fs.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="Limits",
             mastery=0.2, salience=0.5, confidence=0.5, embedding=[1.0, 0.0],
             last_seen_at=FIXED_NOW)
    )
    await _ingest(fs, "a")
    llm = FakeLLM(canned_text=_extraction(
        [{"label": "Limits", "summary": "s",
          "evidence": [{"kind": "demonstrated", "content": "did it"}]}]
    ))
    emb = _StubEmbedder({"Limits": [1.0, 0.0]}, default=[0.0, 1.0])
    await _keeper(fs, llm, emb).consolidate("a")
    assert any(a.op == "resolve_contradiction" for a in fs.audit)


async def test_decays_untouched_node_and_prunes_below_floor():
    fs = FakeStorage()
    stale = await fs.insert_node(
        Node(learner_id="a", type=NodeType.CONCEPT, label="Old",
             salience=0.06, embedding=[0.0, 1.0],
             last_seen_at=FIXED_NOW - timedelta(days=10))  # 0.06*0.98^10 ≈ 0.049 < floor
    )
    await _ingest(fs, "a")
    # extraction mentions a different concept -> 'Old' is untouched
    llm = FakeLLM(canned_text=_extraction(
        [{"label": "Fresh", "summary": "s", "evidence": []}]
    ))
    emb = _StubEmbedder({"Fresh": [1.0, 0.0]}, default=[0.5, 0.5])
    await _keeper(fs, llm, emb).consolidate("a")

    node = fs.nodes[stale]
    assert node.salience < 0.06               # decayed
    assert node.forgotten_at is not None      # below floor -> soft-deleted


async def test_lock_held_returns_skipped():
    fs = FakeStorage()
    keeper = _keeper(fs, FakeLLM(canned_text=_extraction([])), _StubEmbedder({}, [0.0, 1.0]))
    async with fs.consolidation_lock("a"):
        report = await keeper.consolidate("a")
    assert report.skipped is True


async def test_no_pending_events_is_noop():
    fs = FakeStorage()
    report = await _keeper(
        fs, FakeLLM(canned_text=_extraction([])), _StubEmbedder({}, [0.0, 1.0])
    ).consolidate("a")
    assert report.processed_events == 0 and report.nodes_created == 0
