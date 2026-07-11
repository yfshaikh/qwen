# tests/eval/test_clock.py
from datetime import datetime, timezone

import pytest

from engram.core.engram import Engram
from engram.core.models import LearningEvent
from engram.eval.clock import SimClock
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage

def _extraction(label: str) -> str:
    return ('{"concepts": [{"label": "%s", "summary": "s",'
            ' "evidence": [{"kind": "asked_about", "content": "q"}]}],'
            ' "preferences": [], "goals": [], "relations": []}' % label)


class _SeqLLM(FakeLLM):
    """FakeLLM returning a queued text per complete() call (then the canned one)."""
    def __init__(self, texts: list[str]):
        super().__init__()
        self._texts = list(texts)

    async def complete(self, role, messages, schema=None):
        out = await super().complete(role, messages, schema)
        if self._texts:
            from engram.core.models import Completion
            return Completion(text=self._texts.pop(0), usage={}, model="seq")
        return out


class _LenEmbedder:
    """Deterministic one-hot on text length: same text -> same vector; texts of
    different lengths -> orthogonal vectors (cosine 0). FakeEmbedder's constant
    vectors are all parallel (cosine 1.0) and would force every candidate to
    merge — useless for decay tests."""
    def __init__(self, dim: int = 1024):
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            v[len(t) % self.dim] = 1.0
            out.append(v)
        return out


def test_simclock_advances_and_rejects_negative():
    c = SimClock()
    t0 = c()
    assert t0 == datetime(2026, 1, 1, tzinfo=timezone.utc)
    c.advance(days=10)
    assert (c() - t0).days == 10
    with pytest.raises(ValueError):
        c.advance(days=-1)


async def test_sim_time_drives_keeper_decay():
    """A node untouched across a large sim gap decays (and crosses the prune
    floor); the second extraction is a DIFFERENT concept with an orthogonal
    embedding so it creates a new node instead of merging into (and thereby
    touching) the old one."""
    clock = SimClock()
    llm = _SeqLLM([_extraction("Limits"), _extraction("Photosynthesis and Chlorophyll")])
    eng = Engram(storage=FakeStorage(), llm=llm, embedder=_LenEmbedder(dim=1024), now=clock)
    await eng.ingest([LearningEvent(learner_id="a", type="utterance", text="what are limits?")])
    await eng.consolidate("a")                       # creates 'Limits' at sim t0
    node = next(n for n in eng.storage.nodes.values() if "Limits" in n.label)
    s0 = node.salience
    clock.advance(days=365)                          # long absence
    await eng.ingest([LearningEvent(learner_id="a", type="utterance", text="plants?")])
    await eng.consolidate("a")
    old = eng.storage.nodes[node.id]
    assert old.salience is not None and old.salience < s0      # decayed on sim time
    assert old.forgotten_at is not None                        # 0.98^365 < prune floor


async def test_default_now_unchanged():
    eng = Engram(storage=FakeStorage(), llm=FakeLLM(), embedder=FakeEmbedder(dim=8))
    assert eng._now is None  # None -> Keeper falls back to real utcnow
