"""Scenario definitions for the eval harness (authored input to `gen`)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(slots=True)
class Probe:
    query: str
    expect_nodes: list[str] = field(default_factory=list)
    mastered_not_expected: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Session:
    intent: str
    turns: int = 3


@dataclass(slots=True)
class Scenario:
    id: str
    persona: str
    hidden_state: dict
    sessions: list[Session]
    probes: list[Probe]


def load_scenario(path: str | Path) -> Scenario:
    data = yaml.safe_load(Path(path).read_text()) or {}
    if not data.get("id"):
        raise ValueError("scenario missing required field: id")
    if not data.get("probes"):
        raise ValueError("scenario missing required field: probes")
    sessions = [Session(intent=s["intent"], turns=int(s.get("turns", 3)))
                for s in data.get("sessions", [])]
    probes = [Probe(query=p["query"],
                    expect_nodes=list(p.get("expect_nodes", [])),
                    mastered_not_expected=list(p.get("mastered_not_expected", [])))
              for p in data["probes"]]
    return Scenario(id=data["id"], persona=data.get("persona", ""),
                    hidden_state=data.get("hidden_state", {}),
                    sessions=sessions, probes=probes)
