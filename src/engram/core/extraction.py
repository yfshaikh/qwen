"""Extraction — turn pending events into typed candidate nodes + relations.

The extractor LLM returns JSON; parse_extraction validates it into typed
candidates, dropping items with out-of-enum kinds/types but raising on
structurally broken JSON. Evidence may carry optional correct/mastery copied from
event signals (signal-greedy) — the planner prefers those over the kind table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from engram.core.models import EdgeType, EvidenceKind, Message, NodeType
from engram.core.text import normalize_label

# Passed to LLMPort.complete as `schema` to trigger json_object mode; the prompt
# describes the shape for the model.
EXTRACTION_SCHEMA: dict = {"type": "object"}

_VALID_NODE_TYPES = {t.value for t in NodeType}
_VALID_KINDS = {k.value for k in EvidenceKind}
_VALID_REL_TYPES = {t.value for t in EdgeType}


class ExtractionError(Exception):
    """Raised when the extractor output is not usable JSON of the right shape."""


@dataclass(slots=True)
class ExtractedEvidence:
    kind: str
    content: str | None = None
    importance: float | None = None
    correct: bool | None = None
    mastery: float | None = None


@dataclass(slots=True)
class ExtractedNode:
    type: str
    label: str
    summary: str | None
    importance: float | None = None
    evidence: list[ExtractedEvidence] = field(default_factory=list)
    external_id: str | None = None

    def embed_text(self) -> str:
        return self.label + (f" {self.summary}" if self.summary else "")


@dataclass(slots=True)
class ExtractedRelation:
    source_label: str
    target_label: str
    type: str


@dataclass(slots=True)
class Extraction:
    nodes: list[ExtractedNode] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


# Evidence kinds are the ONLY thing that moves the learner model: the Keeper maps
# kind -> mastery observation via core/mastery.py KIND_OBSERVATION, and four of the
# seven kinds carry a signal while three are inert.
#
# This guide exists because an earlier prompt passed `sorted(_VALID_KINDS)` as a
# bare alphabetical enum with no definitions. Measured on eval run a2b4c404 (frozen
# transcript, 3 sessions containing an explicit wrong answer that the tutor
# explicitly corrected): the extractor emitted ZERO quiz_wrong, reached for the
# three inert kinds throughout, and every mastery on the graph's misconception
# concept stayed None. Contradiction detection is built and correct — it had simply
# never been fed. Never reduce this back to a bare enum.
_KIND_GUIDE = (
    "EVIDENCE KIND — this is the most important field you emit. It is the only "
    "thing that updates what the learner knows. Pick the most specific one:\n"
    "  quiz_wrong   = the learner answered incorrectly, OR stated a belief the "
    "tutor corrected. USE THIS FOR MISCONCEPTIONS — a wrong belief the learner "
    "holds is the single most valuable thing to record.\n"
    "  quiz_correct = the learner answered a question correctly.\n"
    "  demonstrated = the learner correctly explained or applied the concept "
    "without being asked.\n"
    "  struggle     = the learner expressed confusion, uncertainty, or difficulty.\n"
    "  asked_about  = the learner asked about it. Carries NO mastery signal.\n"
    "  explained    = the tutor explained it. Carries NO mastery signal.\n"
    "  note         = anything else. Carries NO mastery signal.\n"
    "The first four move mastery; the last three are inert. If the learner was "
    "assessed and you choose an inert kind, that assessment is silently lost.\n"
)

# The attribution rule. Same run: the learner correctly explained a concept while
# naming two others in the sentence, and the extractor credited the two named
# concepts (mastery 0.9 each) while the concept actually being assessed got a bare
# `explained` and stayed at mastery=None. The concepts were right; the evidence
# landed on the wrong ones.
_ATTRIBUTION = (
    "ATTRIBUTION: attach assessment evidence (quiz_wrong, quiz_correct, "
    "demonstrated, struggle) to the concept BEING ASSESSED — not to every concept "
    "the sentence happens to mention. If a learner is asked about concept X and "
    "answers using the words Y and Z, the evidence belongs on X. Y and Z get "
    "`note` or nothing.\n"
)

# NOTE: relations are deliberately NOT requested here. One call was doing five
# jobs (concepts, summaries, importance, evidence, relations) and did the last
# badly — roadmap §3.1 fix #2 / Graphiti's split pipeline. Edge inference is a
# separate pass (_EDGE_SYSTEM below) that runs AFTER entities are resolved.
_SYSTEM = (
    "You extract a learner's knowledge graph from learning events. "
    "Return ONLY JSON with keys: concepts, preferences, goals (each a list of "
    '{label, summary, importance, evidence:[{kind, content, importance, correct?, mastery?}]}). '
    "importance is 0-1: 1.0 = central to the learner's goal or repeatedly discussed, "
    "0.7 = actively being studied, 0.4 = supporting detail, 0.1 = passing mention. "
    + _KIND_GUIDE
    + _ATTRIBUTION
    + f"Evidence kind must be one of {sorted(_VALID_KINDS)}. "
    "If an event's signals contain correct/mastery, copy them onto the evidence. "
    "Extract preferences and goals ONLY from the learner's own words; never "
    "from tutor_explanation text. A preference must be DURABLE — something the "
    "learner states as a standing preference, not a one-off request in the moment. "
    "Do not invent node types beyond concept/preference/goal. "
    "A concept is a topic the learner is learning. Do not emit a concept for an "
    "incidental noun or phrase that merely appeared in the conversation."
)

# Closed-vocabulary mode: used only when a learner has ontology-backed concepts
# (host-supplied-ontology design, spec 2026-07-15 §6.5). NEVER edit _SYSTEM above
# to add this behavior — it is the ontology=None path and is calibrated against
# live runs. This is a SEPARATE prompt, reusing _KIND_GUIDE and _ATTRIBUTION
# verbatim exactly as _SYSTEM does.
_SYSTEM_CLOSED = (
    "You extract a learner's knowledge graph from learning events. "
    "The concepts are FIXED — a curriculum defines them and you may not add to "
    "them. Your job on concepts is to decide which of the listed concepts each "
    "event is evidence about, and what kind of evidence it is.\n"
    "Return ONLY JSON with keys: concepts, preferences, goals.\n"
    "  concepts: a list of {concept_id, importance, evidence:[{kind, content, "
    "importance, correct?, mastery?}]}. concept_id MUST be copied exactly from "
    "the CONCEPTS list below. If an event is not about any listed concept, omit "
    "it — do NOT invent a concept, do NOT pick the closest one.\n"
    "  preferences, goals: a list of {label, summary, importance, evidence:[...]}"
    " — these are NOT in the curriculum, so write them yourself as before.\n"
    "Do NOT output a 'relations' key. The curriculum already defines how "
    "concepts relate; any relation you emit is ignored.\n"
    "importance is 0-1: 1.0 = central to the learner's goal or repeatedly "
    "discussed, 0.7 = actively being studied, 0.4 = supporting detail, 0.1 = "
    "passing mention. "
    + _KIND_GUIDE
    + _ATTRIBUTION
    + f"Evidence kind must be one of {sorted(_VALID_KINDS)}. "
    "If an event's signals contain correct/mastery, copy them onto the evidence. "
    "Extract preferences and goals ONLY from the learner's own words; never from "
    "tutor_explanation text. A preference must be DURABLE — something the learner "
    "states as a standing preference, not a one-off request in the moment."
)


# Open-mode anchor (roadmap §3.1 fix #1). Before this, the extractor NEVER saw
# the graph it was building: session 1 minted 'EM induction' next to session 0's
# 'electromagnetic induction' because nothing told it the label existed, and the
# dedup ladder measurably cannot catch that (jaccard 0.33 vs the 0.8 bar). This
# is mem0's retrieve-then-decide done at extraction time: reuse the exact label
# when it's the same concept, so duplicates die at the source instead of in
# _resolve. Unlike closed mode this stays OPEN — new nodes are still allowed.
_KNOWN_GUIDE = (
    "KNOWN NODES — this learner's graph already contains these (type: label):\n"
    "{catalog}\n"
    "If an event is about one of these, reuse the EXACT label shown — never a "
    "variant, abbreviation, or expansion of it ('EM induction' and "
    "'electromagnetic induction' must be ONE node). Do not mint a narrower "
    "sub-concept of a known concept for a detail discussed in passing; attach "
    "the evidence to the known concept instead. Create a new node only for "
    "material no known node covers.\n\n"
)


def build_extraction_messages(
    events,
    vocabulary: list[tuple[str, str]] | None = None,
    known: list[tuple[str, str]] | None = None,
) -> list[Message]:
    """`vocabulary` is [(external_id, label)] — a learner's ontology-backed
    concepts; when present, extraction is CLOSED and `known` is ignored (the
    catalog already is the concept list). `known` is [(type, label)] — the
    learner's existing live nodes, used to anchor OPEN extraction so labels are
    reused instead of re-invented. Both falsy = the original open extraction,
    byte-identical prompt (a learner's first consolidation is unchanged).

    # ponytail: the vocabulary is dumped in full every consolidation. Marfini's
    # ~40 concepts is ~350 tokens/call; a 500-concept course would be ~4k. If
    # that ever bites, send only vector-nearest-k to the batch — but measure
    # first, and note that a partial list can make a correct concept unpickable.
    """
    lines = []
    for e in events:
        lines.append(
            json.dumps({"type": e.type, "text": e.text, "signals": e.signals})
        )
    if not vocabulary:
        prefix = ""
        if known:
            catalog = "\n".join(f"  {t}: {label}" for t, label in sorted(known))
            prefix = _KNOWN_GUIDE.format(catalog=catalog)
        user = (prefix + "Events:\n" + "\n".join(lines)
                + "\n\nReturn the JSON described above.")
        return [Message(role="system", content=_SYSTEM), Message(role="user", content=user)]

    catalog = "\n".join(f"  {ext_id}\t{label}" for ext_id, label in vocabulary)
    user = (
        "CONCEPTS (concept_id, then label — pick concept_id ONLY from this list):\n"
        + catalog
        + "\n\nEvents:\n" + "\n".join(lines)
        + "\n\nReturn the JSON described above."
    )
    return [Message(role="system", content=_SYSTEM_CLOSED), Message(role="user", content=user)]


# The edge pass (roadmap §3.1 fix #2). Asked ONE clear question, with the
# entities already resolved — Graphiti's split pipeline, minus the cost of a
# call per edge. Dynamic mode only: an ontology's edges are authoritative and
# closed mode never infers relations at all.
_EDGE_SYSTEM = (
    "You infer directed relations between concepts in a learner's knowledge "
    "graph. You are given the concept list, the relations already recorded, "
    "and the learning events just discussed.\n"
    'Return ONLY JSON: {"relations": [{"source_label": "...", '
    '"target_label": "...", "type": "..."}]}.\n'
    "Types:\n"
    "  prerequisite = the source concept must be understood BEFORE the target "
    "can be learned. Direction matters — check it twice: 'A prerequisite B' "
    "means A is learned first and B builds on it.\n"
    "  part_of     = the source is a component or special case of the target.\n"
    "  relates_to  = a meaningful association that is neither of the above. "
    "Use sparingly; it is the weakest signal.\n"
    "Rules: use labels EXACTLY as listed — never invent a concept. Do not "
    "repeat a relation already recorded; if a recorded relation has the wrong "
    "type or direction, you may propose the corrected one. Prefer relations "
    "involving the concepts discussed in the events. Only emit relations you "
    "are confident of; an empty list is a good answer."
)


def build_edge_messages(
    concept_labels: list[str],
    known_edges: list[tuple[str, str, str]],
    events,
) -> list[Message]:
    """`known_edges` is [(source_label, type, target_label)] already in the
    graph — shown so settled pairs are not re-litigated every consolidation
    (re-litigation is what let directions churn)."""
    lines = [json.dumps({"type": e.type, "text": e.text, "signals": e.signals})
             for e in events]
    known = ("\n".join(f"  {s} --{t}--> {d}" for s, t, d in known_edges)
             or "  (none yet)")
    user = (
        "CONCEPTS:\n" + "\n".join(f"  {label}" for label in sorted(concept_labels))
        + "\n\nRELATIONS ALREADY RECORDED:\n" + known
        + "\n\nEvents:\n" + "\n".join(lines)
        + "\n\nReturn the JSON described above."
    )
    return [Message(role="system", content=_EDGE_SYSTEM), Message(role="user", content=user)]


def parse_edge_extraction(text: str, concept_labels: set[str]) -> list[ExtractedRelation]:
    """Validate the edge pass's output. Labels must resolve to a listed concept
    (exact, else normalized) — an edge can never mint a node. Returns relations
    carrying the GRAPH's labels so the keeper's label->id lookup always hits."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ExtractionError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ExtractionError("top-level JSON is not an object")
    rels = data.get("relations", [])
    if not isinstance(rels, list):
        raise ExtractionError("'relations' is not a list")

    by_norm = {normalize_label(label): label for label in concept_labels}

    def canon(raw) -> str | None:
        if not isinstance(raw, str):
            return None
        if raw in concept_labels:
            return raw
        return by_norm.get(normalize_label(raw))

    out: list[ExtractedRelation] = []
    for r in rels:
        if not isinstance(r, dict) or r.get("type") not in _VALID_REL_TYPES:
            continue
        s, t = canon(r.get("source_label")), canon(r.get("target_label"))
        if s is None or t is None or s == t:
            continue
        out.append(ExtractedRelation(s, t, r["type"]))
    return out


def _as_float(v) -> float | None:
    """Coerce an LLM-supplied numeric field to float, or None.

    The model sometimes returns qualitative words ("high"/"low") or numeric
    strings for importance/mastery; these must never reach the float4 columns as
    raw strings. Numbers and numeric strings pass through; anything else (a word,
    a bool, a dict) becomes None.
    """
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _evidence(raw: dict) -> ExtractedEvidence | None:
    kind = raw.get("kind")
    if kind not in _VALID_KINDS:
        return None
    return ExtractedEvidence(
        kind=kind,
        content=raw.get("content"),
        importance=_as_float(raw.get("importance")),
        correct=raw.get("correct"),
        mastery=_as_float(raw.get("mastery")),
    )


def _pref_goal_nodes(data: dict) -> list[ExtractedNode]:
    """Parse the 'preferences'/'goals' keys. Shared by open and closed mode —
    preferences/goals are never in the curriculum, so both modes author them the
    same label-based way."""
    nodes: list[ExtractedNode] = []
    for key, node_type in (("preferences", "preference"), ("goals", "goal")):
        items = data.get(key, [])
        if not isinstance(items, list):
            raise ExtractionError(f"{key!r} is not a list")
        for it in items:
            if not isinstance(it, dict) or "label" not in it:
                continue
            if node_type not in _VALID_NODE_TYPES:
                continue
            evs = [_evidence(r) for r in it.get("evidence", []) if isinstance(r, dict)]
            nodes.append(
                ExtractedNode(
                    type=node_type,
                    label=str(it["label"]),
                    summary=it.get("summary"),
                    importance=_as_float(it.get("importance")),
                    evidence=[e for e in evs if e is not None],
                )
            )
    return nodes


def parse_extraction(
    text: str, vocabulary: list[tuple[str, str]] | None = None
) -> Extraction:
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ExtractionError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ExtractionError("top-level JSON is not an object")

    if not vocabulary:
        nodes: list[ExtractedNode] = []
        for key, node_type in (
            ("concepts", "concept"),
            ("preferences", "preference"),
            ("goals", "goal"),
        ):
            items = data.get(key, [])
            if not isinstance(items, list):
                raise ExtractionError(f"{key!r} is not a list")
            for it in items:
                if not isinstance(it, dict) or "label" not in it:
                    continue
                if node_type not in _VALID_NODE_TYPES:
                    continue
                evs = [_evidence(r) for r in it.get("evidence", []) if isinstance(r, dict)]
                nodes.append(
                    ExtractedNode(
                        type=node_type,
                        label=str(it["label"]),
                        summary=it.get("summary"),
                        importance=_as_float(it.get("importance")),
                        evidence=[e for e in evs if e is not None],
                    )
                )

        relations: list[ExtractedRelation] = []
        rels = data.get("relations", [])
        if not isinstance(rels, list):
            raise ExtractionError("'relations' is not a list")
        for r in rels:
            if not isinstance(r, dict):
                continue
            if r.get("type") not in _VALID_REL_TYPES:
                continue
            if not r.get("source_label") or not r.get("target_label"):
                continue
            relations.append(
                ExtractedRelation(r["source_label"], r["target_label"], r["type"])
            )

        return Extraction(nodes=nodes, relations=relations)

    # Closed mode: classify into a fixed vocabulary, never invent, never infer
    # relations. Matching is exact concept_id, else normalized-label equality —
    # no cosine, no threshold, no fuzzy matching beyond that.
    by_id = dict(vocabulary)
    by_label = {normalize_label(label): ext_id for ext_id, label in vocabulary}

    concepts = data.get("concepts", [])
    if not isinstance(concepts, list):
        raise ExtractionError("'concepts' is not a list")

    closed_nodes: list[ExtractedNode] = []
    dropped: list[str] = []
    for it in concepts:
        if not isinstance(it, dict):
            continue
        ext = it.get("concept_id")
        if ext not in by_id:
            ext = by_label.get(normalize_label(str(it.get("label", ""))))
        if ext is None or ext not in by_id:
            dropped.append(str(it.get("label") or it))
            continue
        evs = [_evidence(r) for r in it.get("evidence", []) if isinstance(r, dict)]
        closed_nodes.append(
            ExtractedNode(
                type="concept",
                label=by_id[ext],  # ontology's label, never the model's echo
                summary=None,
                importance=_as_float(it.get("importance")),
                evidence=[e for e in evs if e is not None],
                external_id=ext,
            )
        )

    closed_nodes.extend(_pref_goal_nodes(data))

    # Relations are ignored entirely in closed mode; the curriculum already
    # defines how concepts relate.
    return Extraction(nodes=closed_nodes, relations=[], dropped=dropped)


_TUTOR_EVENT_TYPES = {"tutor_explanation"}


def filter_provenance(extraction: Extraction, events) -> tuple[Extraction, list[str]]:
    """Drop preference/goal candidates whose support traces only to tutor speech (#4).

    Concepts pass untouched. A pref/goal candidate is kept when any evidence
    content substring-matches a learner-authored event; dropped when it matches
    only tutor events, or when nothing matches and the batch has no learner
    events at all. Untraceable evidence in a batch that does contain learner
    events gets the benefit of the doubt (extractors paraphrase).
    """
    learner_texts = [(e.text or "").casefold() for e in events
                     if e.type not in _TUTOR_EVENT_TYPES]
    tutor_texts = [(e.text or "").casefold() for e in events
                   if e.type in _TUTOR_EVENT_TYPES]
    kept: list[ExtractedNode] = []
    dropped: list[str] = []
    for n in extraction.nodes:
        if n.type not in ("preference", "goal"):
            kept.append(n)
            continue
        contents = [c for c in ((ev.content or "").casefold() for ev in n.evidence) if c]
        in_learner = any(any(c in lt for lt in learner_texts) for c in contents)
        in_tutor = any(any(c in tt for tt in tutor_texts) for c in contents)
        if in_learner or (not in_tutor and learner_texts):
            kept.append(n)
        else:
            dropped.append(n.label)
    return Extraction(nodes=kept, relations=extraction.relations, dropped=extraction.dropped), dropped
