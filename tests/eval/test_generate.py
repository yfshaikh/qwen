from engram.core.engram import Engram
from engram.eval.fixtures import generate_fixture, student_prompt
from engram.eval.scenario import Scenario, Session, Probe
from tests.fakes import FakeEmbedder, FakeLLM, FakeStorage


def _scenario():
    return Scenario(id="t", persona="p", hidden_state={"goal": "g"},
                    sessions=[Session(intent="ask", turns=2)],
                    probes=[Probe(query="q", expect_nodes=["X"], mastered_not_expected=[])])


def test_student_prompt_includes_persona_and_intent():
    msgs = student_prompt(_scenario(), "ask about limits", "user: hi")
    blob = " ".join(m.content for m in msgs)
    assert "ask about limits" in blob and "p" in blob


async def test_generate_fixture_produces_transcript_and_graph():
    eng = Engram(storage=FakeStorage(), llm=FakeLLM(canned_text="ok"), embedder=FakeEmbedder())
    fx = await generate_fixture(eng, _scenario(), runid="r1")
    assert fx["scenario_id"] == "t"
    # 1 session x 2 student turns -> 2 user + 2 assistant turns
    assert sum(1 for t in fx["sessions"][0]["turns"] if t["role"] == "user") == 2
    assert "graph" in fx and "nodes" in fx["graph"]
    # gen learner was torn down
    assert eng.storage.nodes == {}
    assert eng.storage.events == []
