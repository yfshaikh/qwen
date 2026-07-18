"""resolve_llm — the LLM residue matcher (roadmap §3.3's bijection matcher).

Deterministic matching first; the LLM decides label IDENTITY only for the
leftover, and every structural assertion stays deterministic on top. Fail-safe
in every direction is plain resolve() behavior.
"""
import json

from engram.eval.checks._match import resolve_llm
from engram.eval.registry import EvalContext


class _MatcherLLM:
    def __init__(self, mapping):
        self._mapping = mapping
        self.calls = 0

    async def complete(self, role, messages, schema=None):
        self.calls += 1

        class _Out:
            text = json.dumps({"mapping": self._mapping})
        _Out.text = json.dumps({"mapping": self._mapping})
        return _Out()


class _Eng:
    def __init__(self, llm):
        self.llm = llm


def _ctx(llm):
    return EvalContext(eng=_Eng(llm) if llm else None, scenario=None,
                       learner_id="x", snapshots=[], transcript=[], clock=None,
                       params={})


def _node(label, type="concept"):
    return {"id": label, "label": label, "type": type, "forgotten_at": None}


async def test_residue_matched_and_noted():
    nodes = [_node("single linear equations"), _node("Slope")]
    llm = _MatcherLLM([{"graph_label": "single linear equations",
                        "expected": "Solving linear equations"}])
    res, notes = await resolve_llm(_ctx(llm), nodes,
                                   ["Solving linear equations", "Slope"],
                                   node_type="concept")
    assert res.missing() == []
    assert "single linear equations" not in res.unmatched
    assert notes == ["llm-matched 'single linear equations' -> 'Solving linear equations'"]


async def test_two_labels_on_one_expected_still_a_duplicate():
    # The matcher must not paper over the dedup bug: both variants map to the
    # same expected concept -> that's honest, and it FAILS as a duplicate.
    nodes = [_node("EM induction"), _node("electromagnetic-induction basics")]
    llm = _MatcherLLM([
        {"graph_label": "EM induction", "expected": "Electromagnetic induction"},
        {"graph_label": "electromagnetic-induction basics",
         "expected": "Electromagnetic induction"},
    ])
    res, _ = await resolve_llm(_ctx(llm), nodes, ["Electromagnetic induction"],
                               node_type="concept")
    assert "Electromagnetic induction" in res.duplicated()


async def test_unknown_labels_in_mapping_are_dropped():
    nodes = [_node("Slope basics")]
    llm = _MatcherLLM([
        {"graph_label": "Slope basics", "expected": "Not An Expected Concept"},
        {"graph_label": "Never In Graph", "expected": "Slope"},
    ])
    res, notes = await resolve_llm(_ctx(llm), nodes, ["Slope"], node_type="concept")
    assert res.missing() == ["Slope"] and notes == []


async def test_garbage_output_degrades_to_deterministic():
    class _Bad:
        async def complete(self, role, messages, schema=None):
            class _Out:
                text = "NOT JSON {"
            return _Out()
    nodes = [_node("mystery label")]
    res, notes = await resolve_llm(_ctx(_Bad()), nodes, ["Slope"], node_type="concept")
    assert res.missing() == ["Slope"] and notes == []
    assert res.unmatched == ["mystery label"]


async def test_no_residue_means_no_llm_call():
    nodes = [_node("Slope")]
    llm = _MatcherLLM([])
    res, notes = await resolve_llm(_ctx(llm), nodes, ["Slope"], node_type="concept")
    assert llm.calls == 0 and res.missing() == [] and notes == []


async def test_no_llm_available_is_plain_resolve():
    nodes = [_node("mystery label")]
    res, notes = await resolve_llm(_ctx(None), nodes, ["Slope"], node_type="concept")
    assert res.missing() == ["Slope"] and notes == []
