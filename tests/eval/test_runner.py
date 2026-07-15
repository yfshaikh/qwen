import importlib
import json

import pytest

import engram.eval.checks  # noqa: F401  (registration)
from engram.core.engram import Engram
from engram.eval.checks import (
    behavior,
    dedup,
    importance,
    integrity,
    lifecycle,
    recall_probes,
)
from engram.eval.clock import SimClock
from engram.eval.registry import clear_registry
from engram.eval.runner import BudgetExceeded, MeteredLLM, execute_run
from engram.eval.scenario import CheckSpec, Probe, Scenario, Session
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


@pytest.fixture(autouse=True)
def _register_checks():
    # test_registry's autouse clear_registry() empties the registry when it runs
    # first in the same process; import caching won't re-fire @check. Reload the
    # check submodules so their decorators re-register for every test here.
    clear_registry()
    for mod in (dedup, importance, recall_probes, behavior, integrity, lifecycle):
        importlib.reload(mod)

EXTRACTION = (
    '{"concepts": [{"label": "Limits", "summary": "s",'
    ' "evidence": [{"kind": "asked_about", "content": "q"}]}],'
    ' "preferences": [], "goals": [], "relations": []}'
)


class _UsageLLM(FakeLLM):
    """FakeLLM that reports token usage so the meter has something to count."""
    async def complete(self, role, messages, schema=None):
        out = await super().complete(role, messages, schema)
        out.usage = {"prompt_tokens": 1000, "completion_tokens": 1000}
        return out


def _eng(llm=None):
    return Engram(storage=FakeStorage(), llm=llm or FakeLLM(canned_text=EXTRACTION),
                  embedder=FakeEmbedder(dim=64))


def _scenario(checks=None, sessions=None):
    return Scenario(
        id="t", persona="p", hidden_state={},
        sessions=sessions or [Session(intent="ask", turns=1),
                              Session(intent="more", turns=1, gap_days=30)],
        probes=[Probe(query="limits", expect_nodes=["Limits"])],
        checks=checks or [CheckSpec(name="integrity")])


async def test_metered_llm_counts_and_caps():
    m = MeteredLLM(_UsageLLM(), price_in_per_m=100.0, price_out_per_m=100.0, max_cost_usd=0.25)
    await m.complete("tutor", [])          # 2000 tokens -> $0.20
    assert m.cost["usd"] == pytest.approx(0.20)
    with pytest.raises(BudgetExceeded):
        await m.complete("tutor", [])      # $0.40 > cap
    assert m.cost["by_role"]["tutor"]["tokens_in"] == 2000


async def test_execute_run_full_offline(tmp_path):
    events = []
    data = await execute_run(_eng(), _scenario(), tmp_path, clock=SimClock(),
                             emit=lambda e: events.append(e))
    assert data["status"] == "passed"
    assert [c["name"] for c in data["checks"]] == ["integrity"]
    assert (tmp_path / "run.json").exists()
    assert len(json.loads((tmp_path / "snapshots" / "session-1.json").read_text())["graph"]["nodes"]) >= 1
    assert (tmp_path / "transcript.jsonl").read_text().strip()
    assert data["transcript"] and data["transcript"][0]["session"] == 0  # inline for the UI
    assert any(e["type"] == "consolidated" for e in events)
    # learner cleaned up
    assert data["learner_deleted"] is True


async def test_execute_run_over_budget(tmp_path):
    eng = _eng(llm=_UsageLLM(canned_text=EXTRACTION))
    data = await execute_run(eng, _scenario(), tmp_path, clock=SimClock(),
                             max_cost_usd=0.0001, price_in_per_m=100.0, price_out_per_m=100.0)
    assert data["status"] == "over_budget"
    assert data["cost"]["usd"] > 0


async def test_execute_run_unknown_check_fails_fast(tmp_path):
    sc = _scenario(checks=[CheckSpec(name="nope")])
    data = await execute_run(_eng(), sc, tmp_path, clock=SimClock())
    assert data["status"] == "error" and "nope" in data["error"]


# --- frozen transcript replay -----------------------------------------------

class _CountingLLM(FakeLLM):
    """Records which roles were called, so a test can assert what DIDN'T run."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.roles: list[str] = []

    async def complete(self, role, messages, schema=None):
        self.roles.append(role)
        return await super().complete(role, messages, schema)


TRANSCRIPT = [{"role": "user", "content": "what is magnetic flux?"},
              {"role": "assistant", "content": "- Phi = B.A.cos(theta)"}]


def _frozen_scenario(checks=None):
    return Scenario(
        id="frozen", persona="p", hidden_state={},
        sessions=[Session(turns=1, transcript=TRANSCRIPT)],
        probes=[Probe(query="flux", expect_nodes=["Limits"])],
        checks=checks or [CheckSpec(name="integrity")])


async def test_frozen_replay_calls_extractor_only(tmp_path):
    """THE point of freezing. A generated session varies three LLMs per turn —
    student, tutor, extractor — so a graph difference is unattributable. Replaying
    the student and tutor text leaves the extractor as the only variable, which is
    what makes a run a measurement rather than a dice roll.
    """
    llm = _CountingLLM(canned_text=EXTRACTION)
    data = await execute_run(_eng(llm=llm), _frozen_scenario(), tmp_path, clock=SimClock())
    assert data["status"] == "passed"
    assert "student" not in llm.roles, "frozen replay must not invoke the student"
    assert "tutor" not in llm.roles, "frozen replay must not invoke the tutor"
    assert "extractor" in llm.roles, "consolidation must still run"


async def test_frozen_replay_ingests_the_authored_text_verbatim(tmp_path):
    llm = _CountingLLM(canned_text=EXTRACTION)
    data = await execute_run(_eng(llm=llm), _frozen_scenario(), tmp_path, clock=SimClock())
    got = [(t["role"], t["content"]) for t in data["transcript"]]
    assert got == [("user", TRANSCRIPT[0]["content"]),
                   ("assistant", TRANSCRIPT[1]["content"])]
    # Both sides land as events, so the extractor sees the same pair a generated
    # run would have produced.
    lines = (tmp_path / "transcript.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2


async def test_frozen_replay_warns_when_temperature_unpinned(tmp_path):
    """A frozen transcript pins the input, leaving sampling as the only variance.
    Unpinned, the fixture still runs but is not a gate — and silently reporting an
    irreproducible number is how a coin flip gets mistaken for a verified fix."""
    events = []
    await execute_run(_eng(), _frozen_scenario(), tmp_path, clock=SimClock(),
                      emit=lambda e: events.append(e))
    warn = [e for e in events if e.get("type") == "error" and "temperature" in e.get("message", "")]
    assert warn and "not reproducible" in warn[0]["message"]


async def test_generated_run_does_not_warn_about_temperature(tmp_path):
    events = []
    await execute_run(_eng(), _scenario(), tmp_path, clock=SimClock(),
                      emit=lambda e: events.append(e))
    assert not [e for e in events
                if e.get("type") == "error" and "temperature" in e.get("message", "")]
