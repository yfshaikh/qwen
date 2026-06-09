"""Memory Keeper — the slow, offline consolidation agent (DESIGN §4.3, §4.5).

All of Engram's expensive reasoning lives here, amortized over a whole sitting.
The Keeper drains a learner's un-consolidated events and runs the pipeline:

    extract → link → merge → resolve → decay → prune → snapshot

One batched structured-output LLM call does the extraction (step 2); everything
else is vector ops + arithmetic + bookkeeping, with no LLM on the common path
(DESIGN §6). Every step writes an ``engram_audit`` row for observability and
provenance (DESIGN §4.2), and consolidation is idempotent: only events with
``consolidated_at IS NULL`` are processed, so racing/repeat triggers are safe
(DESIGN §4.3 "Idempotency & scope").

The single entry point is :meth:`Keeper.consolidate`, which returns a small stats
dict the host can log or surface in the "consolidate now" demo button.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import numpy as np

from engram.core.models import (
    AuditEntry,
    Edge,
    EdgeType,
    Evidence,
    EvidenceKind,
    ExtractedEvidence,
    ExtractedItem,
    LearningEvent,
    Message,
    Node,
    NodeType,
)
from engram.core.ports import LLMPort, StoragePort

# Valid enum value sets — the extractor is *not* allowed to invent types
# (DESIGN §4.1: fixed, small type sets keep cost down + the viz legible).
_NODE_TYPES: frozenset[str] = frozenset(t.value for t in NodeType)
_EVIDENCE_KINDS: frozenset[str] = frozenset(k.value for k in EvidenceKind)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _coerce_float(value: Any) -> float | None:
    """Best-effort float, or ``None`` for missing/garbage values."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# The exact JSON contract we ask the extractor to emit (DESIGN §4.3 step 1).
# Sent as ``schema`` so a capable model emits a json_object; the prompt also
# spells it out for models that only honour the text description.
EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": sorted(_NODE_TYPES)},
                    "label": {"type": "string"},
                    "summary": {"type": "string"},
                    "observation": {"type": ["number", "null"]},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "enum": sorted(_EVIDENCE_KINDS)},
                                "content": {"type": "string"},
                                "importance": {"type": "number"},
                            },
                            "required": ["kind", "content"],
                        },
                    },
                },
                "required": ["type", "label"],
            },
        }
    },
    "required": ["items"],
}

_EXTRACTOR_SYSTEM = (
    "You are Engram's Memory Keeper extractor. From a batch of a learner's "
    "learning events, distill the durable knowledge: concepts they touched, "
    "preferences for how they like to learn, and goals they are working toward. "
    "Attach scored evidence to each. You MUST NOT invent new types.\n"
    f"node type ∈ {sorted(_NODE_TYPES)}; evidence kind ∈ {sorted(_EVIDENCE_KINDS)}.\n"
    "`observation` is a mastery estimate in [0,1] when inferable from the events "
    "(e.g. a correct quiz → high, a struggle → low), else null. `importance` is "
    "in [0,1]. Return ONLY JSON of this exact shape:\n"
    '{"items":[{"type":"concept|preference|goal","label":"...","summary":"...",'
    '"observation":0.0,"evidence":[{"kind":"explained|asked_about|quiz_correct|'
    'quiz_wrong|note|struggle|demonstrated","content":"...","importance":0.5}]}]}'
)


class Keeper:
    """The Memory Keeper consolidation agent (DESIGN §4.3).

    Holds tuning knobs (EWMA ``alpha``, ``decay`` factor, similarity thresholds,
    forgetting floor) and the storage + LLM ports. Stateless across calls beyond
    its configuration; one instance is shared by :class:`EngramService`.
    """

    def __init__(
        self,
        storage: StoragePort,
        llm: LLMPort,
        *,
        alpha: float = 0.3,
        decay: float = 0.98,
        merge_threshold: float = 0.92,
        link_threshold: float = 0.6,
        prune_floor: float = 0.05,
        embed_dim: int = 1024,
    ) -> None:
        self.storage = storage
        self.llm = llm
        self.alpha = alpha
        self.decay = decay
        self.merge_threshold = merge_threshold
        self.link_threshold = link_threshold
        self.prune_floor = prune_floor
        self.embed_dim = embed_dim

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #
    async def consolidate(self, learner_id: str) -> dict[str, Any]:
        """Run extract→link→merge→resolve→decay→prune→snapshot for one learner.

        Idempotent: drains only ``consolidated_at IS NULL`` events, so a second
        call with no new events is a no-op (returns zero stats). Consolidates
        *per-learner* (not per-session) so cross-document ``relates_to`` edges
        form across the learner's whole pending backlog (DESIGN §4.3).
        """
        stats = {
            "events_processed": 0,
            "nodes_created": 0,
            "nodes_updated": 0,
            "edges_created": 0,
            "merged": 0,
            "pruned": 0,
        }

        # 1. Drain the queue. No events → nothing to do (the idempotency case).
        events = await self.storage.fetch_unconsolidated_events(learner_id)
        if not events:
            return stats
        stats["events_processed"] = len(events)
        event_ids = [e.id for e in events if e.id]

        # 2. EXTRACT — one batched structured-output call over the whole sitting.
        items = await self._extract(learner_id, events)

        # 3+4+5. LINK / MERGE / RESOLVE — fold each item into the graph, applying
        #         evidence, EWMA mastery, confidence + contradiction handling.
        touched: set[str] = set()
        for item in items:
            await self._link_and_resolve(learner_id, item, touched, stats)

        # 4 (light merge pass over concept nodes that ended up near-duplicate).
        merged = await self._merge_duplicates(learner_id, touched, stats)
        stats["merged"] = merged

        # 6. DECAY + PRUNE untouched nodes; soft-delete those below the floor.
        await self._decay_and_prune(learner_id, touched, stats)

        # 7. SNAPSHOT mastery trajectories for touched nodes, watermark events.
        await self._snapshot(touched)
        await self.storage.mark_events_consolidated(event_ids)

        await self._audit(
            learner_id,
            "consolidate",
            output_refs={
                k: stats[k]
                for k in ("nodes_created", "nodes_updated", "edges_created", "merged", "pruned")
            },
            rationale=(
                f"consolidated {stats['events_processed']} events → "
                f"{stats['nodes_created']} new / {stats['nodes_updated']} updated nodes"
            ),
        )
        return stats

    # ------------------------------------------------------------------ #
    # Step 2 — EXTRACT
    # ------------------------------------------------------------------ #
    async def _extract(
        self, learner_id: str, events: list[LearningEvent]
    ) -> list[ExtractedItem]:
        """One batched LLM call → normalized ``list[ExtractedItem]`` (DESIGN §4.3).

        Defensive throughout: tolerates ``None`` json, missing fields, and bad
        enum values (clamp/skip) so a flaky extractor never crashes consolidation.
        """
        messages = self._build_extract_messages(events)
        completion = await self.llm.complete(
            role="extractor", messages=messages, schema=EXTRACTION_SCHEMA
        )

        payload = completion.json
        if payload is None and completion.text:
            try:
                payload = json.loads(completion.text)
            except (ValueError, TypeError):
                payload = None

        items = self._parse_items(payload)
        await self._audit(
            learner_id,
            "extract",
            input_refs={"event_count": len(events)},
            output_refs={"item_count": len(items)},
            rationale=f"extracted {len(items)} item(s) from {len(events)} event(s)",
            model=completion.model,
            tokens=completion.usage.get("total_tokens") if completion.usage else None,
        )
        return items

    def _build_extract_messages(self, events: list[LearningEvent]) -> list[Message]:
        """Render the task + the batch of events for the extractor."""
        lines: list[str] = [
            "Consolidate these learning events into items. Events (most recent last):",
            "",
        ]
        for i, e in enumerate(events, 1):
            parts = [f"[{i}] type={e.type}"]
            if e.text:
                parts.append(f"text={e.text!r}")
            if e.refs:
                parts.append(f"refs={json.dumps(e.refs, default=str)}")
            if e.signals:
                parts.append(f"signals={json.dumps(e.signals, default=str)}")
            lines.append(" ".join(parts))
        return [
            Message(role="system", content=_EXTRACTOR_SYSTEM),
            Message(role="user", content="\n".join(lines)),
        ]

    @staticmethod
    def _parse_items(payload: dict[str, Any] | None) -> list[ExtractedItem]:
        """Map a (possibly malformed) extractor payload to ``ExtractedItem``s."""
        if not isinstance(payload, dict):
            return []
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            return []

        items: list[ExtractedItem] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            type_ = str(raw.get("type", "")).strip().lower()
            label = raw.get("label")
            if type_ not in _NODE_TYPES or not isinstance(label, str) or not label.strip():
                continue  # skip items with an invented type or no label

            obs = _coerce_float(raw.get("observation"))
            if obs is not None:
                obs = _clamp(obs)

            evidence = Keeper._parse_evidence(raw.get("evidence"))
            summary = raw.get("summary")
            items.append(
                ExtractedItem(
                    type=type_,
                    label=label.strip(),
                    summary=summary.strip() if isinstance(summary, str) else None,
                    observation=obs,
                    evidence=evidence,
                    source_refs=raw.get("source_refs") or [],
                )
            )
        return items

    @staticmethod
    def _parse_evidence(raw_evidence: Any) -> list[ExtractedEvidence]:
        out: list[ExtractedEvidence] = []
        if not isinstance(raw_evidence, list):
            return out
        for raw in raw_evidence:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind", "")).strip().lower()
            content = raw.get("content")
            if kind not in _EVIDENCE_KINDS or not isinstance(content, str) or not content.strip():
                continue
            imp = _coerce_float(raw.get("importance"))
            out.append(
                ExtractedEvidence(
                    kind=kind,
                    content=content.strip(),
                    importance=_clamp(imp) if imp is not None else None,
                )
            )
        return out

    # ------------------------------------------------------------------ #
    # Steps 3 + 5 — LINK + RESOLVE (per item)
    # ------------------------------------------------------------------ #
    async def _link_and_resolve(
        self,
        learner_id: str,
        item: ExtractedItem,
        touched: set[str],
        stats: dict[str, Any],
    ) -> None:
        """Vector-match an item to existing nodes, then update or create it.

        - top similarity ≥ ``merge_threshold`` → SAME node: update in place.
        - otherwise create a new node (with embedding + initial salience 1.0).
        - any *other* match with similarity ≥ ``link_threshold`` → a
          ``relates_to`` edge (the cross-document link, DESIGN §4.3 step 2).
        Then apply the item's evidence + state updates (step 5).
        """
        embedding = (await self.llm.embed([self._item_text(item)]))[0]
        matches = await self.storage.vector_search(
            learner_id, embedding, k=5, types=[item.type]
        )

        node_id: str
        created = False
        if matches and matches[0][1] >= self.merge_threshold:
            # Same concept under (possibly) a different surface form → update it.
            node_id = matches[0][0].id  # type: ignore[assignment]
            existing = matches[0][0]
            await self.storage.update_node_state(
                node_id,
                summary=item.summary or existing.summary,
                embedding=embedding,
            )
            stats["nodes_updated"] += 1
        else:
            node_id = await self.storage.upsert_node(
                Node(
                    learner_id=learner_id,
                    type=NodeType(item.type),
                    label=item.label,
                    summary=item.summary,
                    salience=1.0,
                    embedding=embedding,
                    source_refs=list(item.source_refs),
                )
            )
            created = True
            stats["nodes_created"] += 1

        # relates_to edges to the *other* near matches above the link floor.
        linked: list[str] = []
        for matched, sim in matches:
            if matched.id is None or matched.id == node_id:
                continue
            if sim >= self.link_threshold:
                await self.storage.upsert_edge(
                    Edge(
                        learner_id=learner_id,
                        source_id=node_id,
                        target_id=matched.id,
                        type=EdgeType.RELATES_TO,
                        weight=round(float(sim), 4),
                    )
                )
                stats["edges_created"] += 1
                linked.append(matched.id)

        await self._audit(
            learner_id,
            "link",
            input_refs={"label": item.label, "type": item.type},
            output_refs={"node_id": node_id, "created": created, "linked_to": linked},
            rationale=(
                f"{'created' if created else 'updated'} '{item.label}'"
                + (f"; linked to {len(linked)} node(s)" if linked else "")
            ),
        )

        # Step 5 — apply evidence + EWMA mastery + confidence/contradiction.
        await self._resolve(learner_id, node_id, item, created)
        touched.add(node_id)

    async def _resolve(
        self,
        learner_id: str,
        node_id: str,
        item: ExtractedItem,
        created: bool,
    ) -> None:
        """Apply evidence, update mastery (EWMA) + confidence, bump salience.

        EWMA (DESIGN §4.1): ``mastery = α·observation + (1−α)·(old or observation)``
        when ``observation`` is not None. Confidence nudges up on corroborating
        evidence and down on a contradiction (e.g. a learner *demonstrates*
        mastery on a node we thought was low) — which also writes a
        ``resolve_contradiction`` audit row (DESIGN §4.3 step 4, §4.5).
        """
        node = await self.storage.get_node(node_id)
        if node is None:  # pragma: no cover — just-written; defensive only
            return

        old_mastery = node.mastery
        old_confidence = node.confidence if node.confidence is not None else 0.5

        # Insert evidence rows (each ExtractedEvidence → one Evidence).
        for ev in item.evidence:
            await self.storage.insert_evidence(
                Evidence(
                    node_id=node_id,
                    kind=EvidenceKind(ev.kind),
                    content=ev.content,
                    importance=ev.importance,
                )
            )

        # EWMA mastery update.
        new_mastery = old_mastery
        if item.observation is not None:
            base = old_mastery if old_mastery is not None else item.observation
            new_mastery = _clamp(self.alpha * item.observation + (1.0 - self.alpha) * base)

        # Confidence: corroboration nudges up; a contradiction nudges down.
        contradiction = self._is_contradiction(old_mastery, item)
        if contradiction:
            new_confidence = _clamp(old_confidence - 0.2)
            await self._audit(
                learner_id,
                "resolve_contradiction",
                input_refs={"node_id": node_id, "observation": item.observation},
                output_refs={"old_mastery": old_mastery, "new_mastery": new_mastery},
                rationale=(
                    f"new evidence contradicts state for '{item.label}' "
                    f"(was mastery={_fmt(old_mastery)}, observed={_fmt(item.observation)})"
                ),
            )
        elif item.evidence:
            new_confidence = _clamp(old_confidence + 0.05 * len(item.evidence))
        else:
            new_confidence = old_confidence

        # Salience bump + last_seen on every touched node (DESIGN §4.5).
        base_salience = node.salience if node.salience is not None else (1.0 if created else 0.0)
        new_salience = _clamp(base_salience + 0.2)

        await self.storage.update_node_state(
            node_id,
            mastery=new_mastery,
            confidence=new_confidence,
            salience=new_salience,
            last_seen_at=_now(),
        )

    @staticmethod
    def _is_contradiction(old_mastery: float | None, item: ExtractedItem) -> bool:
        """A demonstrated/correct observation that conflicts with a low prior."""
        if old_mastery is None or item.observation is None:
            return False
        # Demonstrated mastery on a node we thought the learner had not mastered.
        strong_kinds = {EvidenceKind.DEMONSTRATED.value, EvidenceKind.QUIZ_CORRECT.value}
        demonstrated = any(ev.kind in strong_kinds for ev in item.evidence)
        return demonstrated and item.observation - old_mastery >= 0.3

    # ------------------------------------------------------------------ #
    # Step 4 — MERGE (light pass; same-node is already handled in LINK)
    # ------------------------------------------------------------------ #
    async def _merge_duplicates(
        self,
        learner_id: str,
        touched: set[str],
        stats: dict[str, Any],
    ) -> int:
        """Fold remaining near-duplicate concept nodes into one.

        LINK already collapses same-node updates, so this is a minimal safety
        pass over concept nodes touched this round: if two concepts exceed
        ``merge_threshold``, move the loser's evidence onto the keeper and
        soft-delete the loser (DESIGN §4.3 step 3). Conservative — only merges
        within the freshly-touched set to avoid disturbing the wider graph.
        """
        concepts = [
            n
            for n in await self.storage.get_nodes(learner_id, types=["concept"])
            if n.id in touched and n.embedding is not None
        ]
        merged = 0
        dead: set[str] = set()
        for i, keeper in enumerate(concepts):
            if keeper.id in dead:
                continue
            for other in concepts[i + 1 :]:
                if other.id in dead or other.embedding is None:
                    continue
                sim = _cosine(keeper.embedding, other.embedding)
                if sim < self.merge_threshold:
                    continue
                # Move evidence from the loser onto the keeper, then forget it.
                for ev in await self.storage.get_evidence(other.id):  # type: ignore[arg-type]
                    await self.storage.insert_evidence(
                        Evidence(
                            node_id=keeper.id,  # type: ignore[arg-type]
                            kind=ev.kind,
                            content=ev.content,
                            source_ref=ev.source_ref,
                            importance=ev.importance,
                        )
                    )
                await self.storage.update_node_state(other.id, forgotten_at=_now())  # type: ignore[arg-type]
                dead.add(other.id)  # type: ignore[arg-type]
                touched.discard(other.id)  # type: ignore[arg-type]
                merged += 1
                await self._audit(
                    learner_id,
                    "merge",
                    input_refs={"kept": keeper.id, "merged": other.id, "similarity": round(sim, 4)},
                    rationale=f"merged duplicate '{other.label}' into '{keeper.label}'",
                )
        return merged

    # ------------------------------------------------------------------ #
    # Step 6 — DECAY + PRUNE
    # ------------------------------------------------------------------ #
    async def _decay_and_prune(
        self,
        learner_id: str,
        touched: set[str],
        stats: dict[str, Any],
    ) -> None:
        """Age untouched nodes' salience; soft-delete those below the floor.

        Timely forgetting (DESIGN §4.5): nodes NOT touched this round have
        ``salience *= decay``; any node then under ``prune_floor`` is
        soft-deleted via ``forgotten_at`` (never hard-deleted, so the viz can
        fade it out — DESIGN §9 decision 6).
        """
        decayed = 0
        pruned = 0
        for node in await self.storage.get_nodes(learner_id):
            if node.id in touched or node.id is None:
                continue
            old = node.salience if node.salience is not None else self.prune_floor
            new = old * self.decay
            await self.storage.update_node_state(node.id, salience=new)
            decayed += 1
            if new < self.prune_floor:
                await self.storage.update_node_state(node.id, forgotten_at=_now())
                pruned += 1
        stats["pruned"] = pruned

        if decayed:
            await self._audit(
                learner_id,
                "decay",
                output_refs={"decayed": decayed},
                rationale=f"decayed salience on {decayed} untouched node(s)",
            )
        if pruned:
            await self._audit(
                learner_id,
                "prune",
                output_refs={"pruned": pruned},
                rationale=f"soft-deleted {pruned} node(s) below salience floor",
            )

    # ------------------------------------------------------------------ #
    # Step 7 — SNAPSHOT
    # ------------------------------------------------------------------ #
    async def _snapshot(self, touched: set[str]) -> None:
        """Write a ``mastery_history`` point per touched node (DESIGN §4.2)."""
        for node_id in touched:
            node = await self.storage.get_node(node_id)
            if node is None:
                continue
            await self.storage.insert_mastery_snapshot(node_id, node.mastery, node.confidence)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _item_text(item: ExtractedItem) -> str:
        """The text embedded for linking: ``label + " " + summary``."""
        return f"{item.label} {item.summary or ''}".strip()

    async def _audit(
        self,
        learner_id: str,
        op: str,
        *,
        input_refs: dict[str, Any] | None = None,
        output_refs: dict[str, Any] | None = None,
        rationale: str | None = None,
        model: str | None = None,
        tokens: int | None = None,
    ) -> None:
        """Best-effort audit write; a failed audit must not break consolidation."""
        try:
            await self.storage.insert_audit(
                AuditEntry(
                    learner_id=learner_id,
                    op=op,
                    input_refs=input_refs,
                    output_refs=output_refs,
                    rationale=rationale,
                    model=model,
                    tokens=tokens,
                )
            )
        except Exception:  # noqa: BLE001 — audit is observability, not critical path.
            pass


def _cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _fmt(x: float | None, ndigits: int = 2) -> str:
    return "?" if x is None else f"{round(x, ndigits):g}"
