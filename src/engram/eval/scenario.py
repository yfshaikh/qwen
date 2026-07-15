"""Scenario definitions for the eval harness (authored input to `gen`)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    """One session. Either GENERATED (an `intent` the LLM student improvises from)
    or FROZEN (a verbatim `transcript` that gets replayed). Exactly one of the two.

    Frozen sessions exist because a generated one varies three LLMs per turn —
    student, tutor, extractor — so a graph difference is unattributable. Freezing
    the student and tutor text leaves the extractor as the only variable, which is
    what makes a run a measurement. See docs/superpowers/roadmap.md §3.3.
    """
    intent: str = ""
    turns: int = 3
    gap_days: float = 0.0
    transcript: list[dict] | None = None

    @property
    def frozen(self) -> bool:
        return self.transcript is not None


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
    # Authored ground truth for a frozen benchmark: concepts, edges, mastery arcs,
    # abstention targets. Deliberately top-level rather than spread across each
    # check's params (the established CheckSpec pattern) because these are not
    # per-check config — they are ONE ground truth that `edges`, `mastery`, and
    # `abstention` all read the same concept identities from. Splitting it would
    # let the copies drift apart, which for a benchmark is the whole ballgame.
    # Config (thresholds) still lives on CheckSpec; ground truth lives here.
    expect: dict = field(default_factory=dict)

    @property
    def frozen(self) -> bool:
        """True when every session is a replayed transcript (no student LLM)."""
        return bool(self.sessions) and all(s.frozen for s in self.sessions)


def alias_forms(expected: str, aliases: dict[str, list[str]] | None) -> list[str]:
    """All acceptable surface forms for an expected label: the label itself plus
    any declared aliases (canonical-key lookup is case-insensitive)."""
    forms = [expected]
    for key, variants in (aliases or {}).items():
        if key.lower() == expected.lower():
            forms.extend(variants)
    return forms


_VALID_ROLES = {"user", "assistant"}


def _parse_transcript(raw: Any, si: int) -> list[dict]:
    """Validate a frozen session's turns. Strict on purpose: a malformed fixture
    that silently loads produces a run whose result means nothing."""
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"session {si}: 'transcript' must be a non-empty list")
    turns = []
    for i, t in enumerate(raw):
        if not isinstance(t, dict):
            raise ValueError(f"session {si} turn {i}: not a mapping")
        role, content = t.get("role"), t.get("content")
        if role not in _VALID_ROLES:
            raise ValueError(
                f"session {si} turn {i}: role must be one of {sorted(_VALID_ROLES)}, got {role!r}")
        if not content or not str(content).strip():
            raise ValueError(f"session {si} turn {i}: empty content")
        turns.append({"role": role, "content": str(content)})
    # Replay ingests each exchange as an (utterance, tutor_explanation) pair, so a
    # dangling turn would silently drop. Fail loudly instead.
    if len(turns) % 2 != 0:
        raise ValueError(f"session {si}: transcript has {len(turns)} turns; must be even "
                         "(alternating user/assistant)")
    for i in range(0, len(turns), 2):
        if turns[i]["role"] != "user" or turns[i + 1]["role"] != "assistant":
            raise ValueError(
                f"session {si} turn {i}: transcript must alternate user, assistant")
    return turns


def load_scenario(path: str | Path) -> Scenario:
    data = yaml.safe_load(Path(path).read_text()) or {}
    if not data.get("id"):
        raise ValueError("scenario missing required field: id")
    if not data.get("probes"):
        raise ValueError("scenario missing required field: probes")
    sessions = []
    for si, s in enumerate(data.get("sessions", [])):
        gap = float(s.get("gap_days", 0.0))
        if gap < 0:
            raise ValueError("gap_days must be >= 0")
        has_intent, has_transcript = "intent" in s, "transcript" in s
        if has_intent == has_transcript:
            raise ValueError(
                f"session {si}: needs exactly one of 'intent' (generated) or "
                f"'transcript' (frozen); got {'both' if has_intent else 'neither'}")
        if has_transcript:
            turns = _parse_transcript(s["transcript"], si)
            sessions.append(Session(turns=len(turns) // 2, gap_days=gap, transcript=turns))
        else:
            sessions.append(Session(intent=s["intent"], turns=int(s.get("turns", 3)),
                                    gap_days=gap))
    if sessions and any(x.frozen for x in sessions) and not all(x.frozen for x in sessions):
        raise ValueError(
            "scenario mixes frozen and generated sessions; a partially-frozen run is "
            "neither reproducible nor realistic, so it is rejected rather than silently "
            "producing a number nobody can interpret")
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
    expect = dict(data.get("expect") or {})
    aliases = {str(k): [str(x) for x in (v or [])]
               for k, v in (data.get("aliases") or {}).items()}
    # Bridge: `expect.concepts[].aliases` is the single source of truth for a
    # frozen benchmark, but `recall_probes` and `lifecycle` read the flat
    # `scenario.aliases` map via alias_forms(). Project one onto the other so both
    # styles work and there is still only one place to edit. A top-level `aliases:`
    # entry wins on conflict — it's the more specific override.
    for c in expect.get("concepts") or []:
        label = str(c.get("label", "")).strip()
        if label and label not in aliases:
            aliases[label] = [str(x) for x in (c.get("aliases") or [])]
    return Scenario(id=data["id"], persona=data.get("persona", ""),
                    hidden_state=data.get("hidden_state", {}),
                    sessions=sessions, probes=probes, checks=checks, aliases=aliases,
                    expect=expect)
