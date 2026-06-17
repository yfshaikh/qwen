"""YAML seed loader — hand-build a learner graph before the Keeper exists.

Reusable for tests, the eval harness, and demo graphs. Embeds node text and
evidence content via the injected embedder so seeded vectors share the query
vector space.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from engram.core.models import (
    Edge,
    EdgeType,
    Evidence,
    EvidenceKind,
    Node,
    NodeType,
)


async def seed_graph(storage: Any, embedder: Any, yaml_path: str | Path) -> dict[str, str]:
    """Load a YAML graph, embed + write it, return {node_key: node_id}."""
    data = yaml.safe_load(Path(yaml_path).read_text())
    learner_id = data["learner_id"]
    key_to_id: dict[str, str] = {}

    for nd in data.get("nodes", []):
        text = nd["label"] + (f" {nd['summary']}" if nd.get("summary") else "")
        embedding = (await embedder.embed([text]))[0]
        node = Node(
            learner_id=learner_id,
            type=NodeType(nd["type"]),
            label=nd["label"],
            summary=nd.get("summary"),
            mastery=nd.get("mastery"),
            confidence=nd.get("confidence"),
            salience=nd.get("salience"),
            embedding=embedding,
            source_refs=nd.get("source_refs", []),
        )
        node_id = await storage.insert_node(node)
        key_to_id[nd["key"]] = node_id

        for ev in nd.get("evidence", []):
            ev_embedding = (
                (await embedder.embed([ev["content"]]))[0] if ev.get("content") else None
            )
            await storage.insert_evidence(
                Evidence(
                    node_id=node_id,
                    kind=EvidenceKind(ev["kind"]),
                    content=ev.get("content"),
                    source_ref=ev.get("source_ref"),
                    embedding=ev_embedding,
                    importance=ev.get("importance"),
                )
            )

    for ed in data.get("edges", []):
        await storage.insert_edge(
            Edge(
                learner_id=learner_id,
                source_id=key_to_id[ed["source"]],
                target_id=key_to_id[ed["target"]],
                type=EdgeType(ed["type"]),
                weight=ed.get("weight", 1.0),
            )
        )

    return key_to_id
