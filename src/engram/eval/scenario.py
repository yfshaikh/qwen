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
class CheckSpec:
    name: str
    params: dict = field(default_factory=dict)


@dataclass(slots=True)
class Session:
    intent: str
    turns: int = 3
    gap_days: float = 0.0


@dataclass(slots=True)
class Scenario:
    id: str
    persona: str
    hidden_state: dict
    sessions: list[Session]
    probes: list[Probe]
    checks: list[CheckSpec] = field(default_factory=list)
    # Acceptable surface variants per expected concept label, so recall/lifecycle
    # checks verify concept retention rather than the LLM's cosmetic label pick
    # (which merges canonicalize but can still vary). {canonical: [variant, ...]}.
    aliases: dict[str, list[str]] = field(default_factory=dict)


def alias_forms(expected: str, aliases: dict[str, list[str]] | None) -> list[str]:
    """All acceptable surface forms for an expected label: the label itself plus
    any declared aliases (canonical-key lookup is case-insensitive)."""
    forms = [expected]
    for key, variants in (aliases or {}).items():
        if key.lower() == expected.lower():
            forms.extend(variants)
    return forms


def load_scenario(path: str | Path) -> Scenario:
    data = yaml.safe_load(Path(path).read_text()) or {}
    if not data.get("id"):
        raise ValueError("scenario missing required field: id")
    if not data.get("probes"):
        raise ValueError("scenario missing required field: probes")
    sessions = []
    for s in data.get("sessions", []):
        gap = float(s.get("gap_days", 0.0))
        if gap < 0:
            raise ValueError("gap_days must be >= 0")
        sessions.append(Session(intent=s["intent"], turns=int(s.get("turns", 3)),
                                gap_days=gap))
    checks = []
    for c in data.get("checks", []) or []:
        if isinstance(c, str):
            checks.append(CheckSpec(name=c))
        else:
            c = dict(c)
            name = c.pop("name", None)
            if not name:
                raise ValueError("check entry missing 'name'")
            checks.append(CheckSpec(name=name, params=c))
    probes = [Probe(query=p["query"],
                    expect_nodes=list(p.get("expect_nodes", [])),
                    mastered_not_expected=list(p.get("mastered_not_expected", [])))
              for p in data["probes"]]
    aliases = {str(k): [str(x) for x in (v or [])]
               for k, v in (data.get("aliases") or {}).items()}
    return Scenario(id=data["id"], persona=data.get("persona", ""),
                    hidden_state=data.get("hidden_state", {}),
                    sessions=sessions, probes=probes, checks=checks, aliases=aliases)
