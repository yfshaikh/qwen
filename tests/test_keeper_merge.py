"""Merge-quality tests for Keeper._resolve (spec 2 §3 / known issue #6).

FakeEmbedder's vectors are all parallel (cosine 1.0) or zero, so these tests
use _LenEmbedder: orthogonal one-hot vectors keyed by text length — cosine is
1.0 only for equal-length texts, else 0.0. That isolates the lexical paths.
"""
import json

from engram.core.engram import Engram
from engram.core.models import Completion, LearningEvent, Message
from tests.fakes import FakeStorage, route_subpass


class _LenEmbedder:
    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    async def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * self.dim
            v[len(t) % self.dim] = 1.0
            out.append(v)
        return out


class _SeqLLM:
    """Returns queued responses for 'extractor'; canned 'no' for 'reflector'."""

    def __init__(self, extractions: list[str], reflector_text: str = "no") -> None:
        self._q = list(extractions)
        self._reflector = reflector_text
        self.reflector_calls = 0

    async def complete(self, role: str, messages: list[Message], schema=None) -> Completion:
        if role == "reflector":
            self.reflector_calls += 1
            return Completion(text=self._reflector)
        canned = route_subpass(messages)
        if canned is not None:
            return Completion(text=canned)
        return Completion(text=self._q.pop(0))


def _extraction(*concepts: str) -> str:
    return json.dumps({
        "concepts": [
            {"label": c, "summary": f"about {c}",
             "evidence": [{"kind": "asked_about", "content": f"asked about {c}"}]}
            for c in concepts
        ],
        "preferences": [], "goals": [], "relations": [],
    })


async def _consolidate(llm, storage, learner="L"):
    eng = Engram(storage=storage, llm=llm, embedder=_LenEmbedder())
    await eng.ingest([LearningEvent(learner_id=learner, type="utterance", text="hi")])
    return await eng.consolidate(learner)


async def test_normalized_label_match_merges_across_sessions():
    storage = FakeStorage()
    llm = _SeqLLM([_extraction("Transistors"), _extraction("transistor!")])
    await _consolidate(llm, storage)
    await _consolidate(llm, storage)
    live = await storage.get_live_nodes("L")
    assert [n.label for n in live] == ["Transistors"]  # merged, no reflector needed
    assert llm.reflector_calls == 0


async def test_token_overlap_alone_no_longer_merges():
    # Fix #3 deleted the jaccard branch (measured 0-for-7 on real duplicates).
    # These share 4 of 5 tokens (old jaccard 0.8) but embed orthogonally
    # (_LenEmbedder) and the reflector says no — so they stay SEPARATE now.
    # Near-miss labels are the cosine/reflector layers' job, not lexical's.
    storage = FakeStorage()
    llm = _SeqLLM([_extraction("electromagnetic induction faraday law"),
                   _extraction("electromagnetic induction faraday law basics")])
    await _consolidate(llm, storage)
    await _consolidate(llm, storage)
    live = await storage.get_live_nodes("L")
    assert len(live) == 2


async def test_distinct_labels_low_cosine_stay_separate():
    storage = FakeStorage()
    llm = _SeqLLM([_extraction("Ohm Law"), _extraction("Magnetic Flux")])
    await _consolidate(llm, storage)
    await _consolidate(llm, storage)
    live = await storage.get_live_nodes("L")
    assert len(live) == 2


async def test_same_batch_duplicates_collapse():
    storage = FakeStorage()
    llm = _SeqLLM([_extraction("Limits", "limit")])
    report = await _consolidate(llm, storage)
    live = await storage.get_live_nodes("L")
    assert len(live) == 1
    assert report.merged == 1  # audited merge


async def test_lexical_merge_audited():
    storage = FakeStorage()
    llm = _SeqLLM([_extraction("Transistors"), _extraction("transistor!")])
    await _consolidate(llm, storage)
    await _consolidate(llm, storage)
    ops = [a["op"] for a in await storage.get_audit("L")]
    assert "merge" in ops


async def test_lexical_merge_does_not_cross_node_types():
    """A goal labeled like a concept must not merge into that concept."""
    storage = FakeStorage()
    concept = json.dumps({
        "concepts": [{"label": "electromagnetic induction", "summary": "flux change",
                      "evidence": [{"kind": "asked_about", "content": "what is EM induction"}]}],
        "preferences": [], "goals": [], "relations": [],
    })
    goal = json.dumps({
        "concepts": [], "preferences": [],
        "goals": [{"label": "electromagnetic induction", "summary": "pass the EM midterm",
                   "evidence": [{"kind": "asked_about", "content": "I want to master EM induction"}]}],
        "relations": [],
    })
    llm = _SeqLLM([concept, goal])
    await _consolidate(llm, storage)
    await _consolidate(llm, storage)
    live = await storage.get_live_nodes("L")
    assert sorted(n.type.value for n in live) == ["concept", "goal"]
    assert all(n.label == "electromagnetic induction" for n in live)


# --- canonical label on merge (Option A, 2026-07-13) -------------------------
# FakeEmbedder returns constant (parallel) vectors -> cosine 1.0 -> two same-type
# candidates merge via tau_high regardless of label, so these isolate which label
# survives the merge.
from tests.fakes import FakeEmbedder  # noqa: E402


async def _consolidate_fake(llm, storage, learner="L"):
    eng = Engram(storage=storage, llm=llm, embedder=FakeEmbedder(dim=8))
    await eng.ingest([LearningEvent(learner_id=learner, type="utterance", text="hi")])
    return await eng.consolidate(learner)


async def test_merge_adopts_fuller_label_across_sessions():
    storage = FakeStorage()
    llm = _SeqLLM([_extraction("EM Induction"), _extraction("Electromagnetic Induction")])
    await _consolidate_fake(llm, storage)
    await _consolidate_fake(llm, storage)
    live = await storage.get_live_nodes("L")
    assert len(live) == 1
    assert live[0].label == "Electromagnetic Induction"  # abbreviation lost


async def test_merge_keeps_fuller_when_abbrev_comes_second():
    storage = FakeStorage()
    llm = _SeqLLM([_extraction("Electromagnetic Induction"), _extraction("EM Induction")])
    await _consolidate_fake(llm, storage)
    await _consolidate_fake(llm, storage)
    live = await storage.get_live_nodes("L")
    assert len(live) == 1
    assert live[0].label == "Electromagnetic Induction"  # stability: fuller stays


async def test_same_batch_merge_adopts_fuller_label():
    # Same-batch pair merges via the COSINE layer (fix #3 closed the tmp- hole;
    # FakeEmbedder vectors are all-parallel, cosine 1.0). The fuller label wins.
    storage = FakeStorage()
    llm = _SeqLLM([_extraction("alpha beta gamma delta",
                               "alpha beta gamma delta epsilon")])
    await _consolidate_fake(llm, storage)
    live = await storage.get_live_nodes("L")
    assert len(live) == 1
    assert live[0].label == "alpha beta gamma delta epsilon"


class _TableEmbedder:
    """Substring-keyed vectors so a test can place a pair at an exact cosine."""

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


async def test_same_batch_cosine_merge_tmp_hole_closed():
    # Fix #3: the cosine layer now sees same-batch tmp nodes. Two candidates
    # with NO shared tokens but identical embeddings merge in one batch —
    # before the fix the loop skipped tmp- ids and this minted two nodes
    # ('AC Circuits' / 'AC Circuits (RLC Impedance)', the measured hole).
    storage = FakeStorage()
    llm = _SeqLLM([_extraction("Ohm Law", "Current Voltage Rule")])
    eng = Engram(storage=storage, llm=llm,
                 embedder=_TableEmbedder({}, default=[1.0, 0.0]))
    await eng.ingest([LearningEvent(learner_id="L", type="utterance", text="hi")])
    report = await eng.consolidate("L")
    live = await storage.get_live_nodes("L")
    assert len(live) == 1
    assert report.merged == 1
    assert llm.reflector_calls == 0  # >= tau_high, no reflector needed


async def test_same_batch_reflector_band_reaches_tmp_nodes():
    # cosine 0.8 sits in the tau_low..tau_high band -> the reflector is asked
    # about a same-batch tmp node (pre-fix it never saw one) and its 'yes'
    # merges the pair.
    storage = FakeStorage()
    llm = _SeqLLM([_extraction("Ohm Law", "Current Voltage Rule")],
                  reflector_text="yes")
    eng = Engram(storage=storage, llm=llm,
                 embedder=_TableEmbedder({"Ohm Law": [1.0, 0.0],
                                          "Current Voltage Rule": [0.8, 0.6]},
                                         default=[0.0, 1.0]))
    await eng.ingest([LearningEvent(learner_id="L", type="utterance", text="hi")])
    await eng.consolidate("L")
    live = await storage.get_live_nodes("L")
    assert len(live) == 1
    assert llm.reflector_calls == 1
