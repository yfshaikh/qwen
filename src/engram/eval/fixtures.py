"""Fixture I/O: snapshot a learner's graph, freeze to JSON, and load it back
under a fresh learner id (remapping node ids). No LLM here."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engram.core.models import Edge, EdgeType, Evidence, EvidenceKind, LearningEvent, Message, Node, NodeType
from engram.eval.arms import _tutor_reply
from engram.eval.scenario import Scenario

_EVIDENCE_PER_NODE = 50  # ponytail: cap; nodes carry few evidence rows, raise if that changes


def node_to_dict(n: Node) -> dict[str, Any]:
    return {
        "id": n.id, "type": n.type.value, "label": n.label, "summary": n.summary,
        "mastery": n.mastery, "confidence": n.confidence, "salience": n.salience,
        "embedding": n.embedding,
    }


def edge_to_dict(e: Edge) -> dict[str, Any]:
    return {"source": e.source_id, "target": e.target_id, "type": e.type.value, "weight": e.weight}


def evidence_to_dict(ev: Evidence) -> dict[str, Any]:
    return {"kind": ev.kind.value, "content": ev.content, "source_ref": ev.source_ref,
            "importance": ev.importance, "embedding": ev.embedding}


async def snapshot_graph(storage: Any, learner_id: str) -> dict[str, Any]:
    nodes = await storage.get_live_nodes(learner_id)
    node_ids = [n.id for n in nodes if n.id]
    edges = await storage.get_edges(learner_id, node_ids)
    ev_map = await storage.top_evidence(node_ids, _EVIDENCE_PER_NODE)
    return {
        "nodes": [node_to_dict(n) for n in nodes],
        "edges": [edge_to_dict(e) for e in edges],
        "evidence": {nid: [evidence_to_dict(ev) for ev in ev_map.get(nid, [])] for nid in node_ids},
    }


def save_fixture(path: str | Path, *, scenario_id: str, sessions: list, graph: dict) -> None:
    Path(path).write_text(json.dumps(
        {"scenario_id": scenario_id, "sessions": sessions, "graph": graph}, indent=2))


def load_fixture(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


async def load_graph_into(storage: Any, graph: dict, learner_id: str) -> dict[str, str]:
    idmap: dict[str, str] = {}
    for nd in graph["nodes"]:
        new_id = await storage.insert_node(Node(
            learner_id=learner_id, type=NodeType(nd["type"]), label=nd["label"],
            summary=nd.get("summary"), mastery=nd.get("mastery"),
            confidence=nd.get("confidence"), salience=nd.get("salience"),
            embedding=nd.get("embedding"),
        ))
        idmap[nd["id"]] = new_id
    for ed in graph["edges"]:
        await storage.insert_edge(Edge(
            learner_id=learner_id, source_id=idmap[ed["source"]], target_id=idmap[ed["target"]],
            type=EdgeType(ed["type"]), weight=ed.get("weight", 1.0),
        ))
    for old_id, evs in graph.get("evidence", {}).items():
        for ev in evs:
            await storage.insert_evidence(Evidence(
                node_id=idmap[old_id], kind=EvidenceKind(ev["kind"]), content=ev.get("content"),
                source_ref=ev.get("source_ref"), importance=ev.get("importance"),
                embedding=ev.get("embedding"),
            ))
    return idmap


def student_prompt(scenario: "Scenario", intent: str, transcript: str) -> list["Message"]:
    return [
        Message(role="system", content=(
            f"You ROLE-PLAY a student, never the tutor. Persona: {scenario.persona}\n"
            f"Hidden state (stay consistent, reveal naturally): {scenario.hidden_state}\n"
            f"Right now your intent: {intent}\n"
            "Emit ONLY your next short message to the tutor.")),
        Message(role="user", content=f"Conversation so far:\n{transcript or '(none)'}\n\nYour next message:"),
    ]


async def generate_fixture(eng: Any, scenario: "Scenario", runid: str) -> dict[str, Any]:
    learner_id = f"eval:{scenario.id}:{runid}"
    sessions_out: list[dict] = []
    history: list[dict] = []
    try:
        for session in scenario.sessions:
            turns: list[dict] = []
            for _ in range(session.turns):
                transcript = "\n".join(f"{h['role']}: {h['content']}" for h in history)
                out = await eng.llm.complete("student", student_prompt(scenario, session.intent, transcript))
                user = (out.text or "").strip()
                history.append({"role": "user", "content": user})
                reply = await _tutor_reply(eng, "", history)
                history.append({"role": "assistant", "content": reply})
                turns.append({"role": "user", "content": user})
                turns.append({"role": "assistant", "content": reply})
                await eng.ingest([
                    LearningEvent(learner_id=learner_id, type="utterance", text=user),
                    LearningEvent(learner_id=learner_id, type="tutor_explanation", text=reply),
                ])
            sessions_out.append({"turns": turns})
        await eng.consolidate(learner_id)
        graph = await snapshot_graph(eng.storage, learner_id)
    finally:
        await eng.storage.delete_learner(learner_id)
    return {"scenario_id": scenario.id, "sessions": sessions_out, "graph": graph}
