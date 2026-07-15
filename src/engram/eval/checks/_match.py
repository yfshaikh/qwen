"""Concept matching shared by the frozen-benchmark checks.

WHY THIS IS ITS OWN MODULE
Concept identity is the foundation of every ground-truth check: `edges`,
`abstention`, and `knowledge_update` all ask "which node IS this expected
concept?" before they can assert anything. If that lookup is wrong, they report
bugs that don't exist — and an agent iterating on fixes cannot tell a stale alias
from a real regression, "adjusts accordingly", and makes the code worse chasing a
ghost. One matcher, one semantic, one place to fix.

MATCHING SEMANTIC
Equality on the normalized label (casefold + collapsed whitespace), against the
concept's label and its authored aliases.

This diverges from arms.py's case-insensitive substring, which it previously
copied for consistency. Substring made every short alias a wildcard: `Transformer`
matched the distinct concept `Transformer turns ratio`, and 3 of the 5 runs in
variance-em-frozen-v1.md reported a duplicate that did not exist. The original
reasoned that ambiguity should be REPORTED rather than resolved because "a human
reading the failure can tell a real duplicate from an over-broad alias" — true,
but the harness's job is now to gate an agent's fix-loop with no human in it. A
diagnostic an LLM will act on cannot cost a human read to interpret.

The divergence from arms.py is deliberate: it scores authored goal text against a
free-text plan, where substring absorbs phrasing drift. Here we compare graph
labels to authored ground truth, and the drift IS the bug under test.

Equality also makes short aliases safe — under substring, `flux` had to be dropped
for matching `EMF from flux change`; as an exact form it matches only a node
labelled exactly "flux". Add aliases for the forms a correct extractor may emit;
calibrate them from a real run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engram.eval.scenario import alias_forms


def is_live(node: dict) -> bool:
    return not node.get("forgotten_at")


def live_nodes(nodes: list[dict], node_type: str | None = None) -> list[dict]:
    out = [n for n in nodes if is_live(n)]
    if node_type is not None:
        out = [n for n in out if n.get("type") == node_type]
    return out


def norm_label(s: str) -> str:
    """Casefold + collapse whitespace. The whole normalization, deliberately."""
    return " ".join(str(s).split()).casefold()


def mentions_topic(nodes: list[dict], topic: str) -> list[dict]:
    """Every node whose label CONTAINS `topic`. Containment, not identity.

    The opposite question from match_concept, and it wants the opposite semantic.
    `abstention` asks "did the extractor invent this topic at all?" — a fabricated
    'AC Circuits (RLC Impedance)' is the fabricated 'AC Circuits', and equality
    would wave it through on the parenthetical. Identity checks want exact;
    did-you-touch-this checks want loose. Don't unify them.
    """
    needle = norm_label(topic)
    return [n for n in nodes if needle and needle in norm_label(n.get("label", ""))]


def match_concept(nodes: list[dict], label: str,
                  aliases: dict[str, list[str]] | None = None) -> list[dict]:
    """Every node whose label EQUALS `label` or one of its aliases, normalized.

    Returns a LIST, not a single node, on purpose: >1 match is a genuine duplicate
    (what `concepts`/`no_duplicates` hunts). Collapsing to "the first match" would
    silently hide it.
    """
    needles = {norm_label(f) for f in alias_forms(label, aliases) if f.strip()}
    return [n for n in nodes if norm_label(n.get("label", "")) in needles]


@dataclass(slots=True)
class Resolution:
    """The full picture of expected-vs-actual concept identity for one graph."""

    # expected label -> live nodes matching it. Empty list = missing.
    by_label: dict[str, list[dict]] = field(default_factory=dict)
    # Live node labels that matched NO expected concept. Not a failure by itself —
    # a graph is allowed extra concepts — but it is the diagnostic that tells a
    # reader whether a "missing concept" is a real regression or a stale alias.
    unmatched: list[str] = field(default_factory=list)

    def one(self, label: str) -> dict | None:
        """The single node for `label`, or None if missing or ambiguous.
        Callers that care about the difference should read `by_label` directly."""
        got = self.by_label.get(label) or []
        return got[0] if len(got) == 1 else None

    def missing(self) -> list[str]:
        return [k for k, v in self.by_label.items() if not v]

    def duplicated(self) -> dict[str, list[str]]:
        return {k: [str(n.get("label")) for n in v]
                for k, v in self.by_label.items() if len(v) > 1}

    def unmatched_note(self) -> str:
        """The line that lets a human (or an iterating agent reading the failure
        text) tell an alias gap from a real regression. Every check that keys on
        concept identity must include this in its details — see roadmap §3.3."""
        return (f"unmatched labels in graph: {sorted(self.unmatched)}"
                if self.unmatched else "unmatched labels in graph: none")


def resolve(nodes: list[dict], expected: list[str],
            aliases: dict[str, list[str]] | None = None,
            node_type: str | None = None) -> Resolution:
    """Map expected concept labels onto the graph's LIVE nodes, both directions.

    Forgotten nodes are excluded: an expectation is about what the learner still
    holds, and a forgotten node is precisely the graph saying "not any more".
    """
    live = live_nodes(nodes, node_type)
    by_label = {label: match_concept(live, label, aliases) for label in expected}
    matched_ids = {id(n) for v in by_label.values() for n in v}
    unmatched = [str(n.get("label")) for n in live if id(n) not in matched_ids]
    return Resolution(by_label=by_label, unmatched=unmatched)


def node_id_set(nodes: list[dict]) -> set[str]:
    return {str(n["id"]) for n in nodes if n.get("id")}


def snapshot_nodes(ctx: Any, index: int = -1) -> list[dict]:
    """Nodes from a snapshot, or [] when the run produced none (a failed run must
    make checks fail loudly, not raise IndexError into the registry's catch-all)."""
    snaps = getattr(ctx, "snapshots", None) or []
    if not snaps:
        return []
    try:
        return list(snaps[index]["graph"]["nodes"])
    except (IndexError, KeyError, TypeError):
        return []
