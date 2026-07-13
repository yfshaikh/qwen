"""The Memory Keeper — plan, then commit.

consolidate() acquires a per-learner advisory lock, reads pending events + live
nodes, builds a ConsolidationPlan via a pure pipeline (extract → link/merge →
resolve → decay → prune → snapshot), and applies it in one atomic transaction.
New nodes carry temp ids remapped at commit. The planner never writes to the DB.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from engram.core.consolidation import (
    AuditEntry,
    ConsolidationPlan,
    ConsolidationReport,
    MasteryPoint,
)
from engram.core.edges import edge_rank
from engram.core.extraction import (
    EXTRACTION_SCHEMA,
    Extraction,
    ExtractionError,
    build_extraction_messages,
    filter_provenance,
    parse_extraction,
)
from engram.core.mastery import decay_salience, ewma, observation_for, update_confidence
from engram.core.ports import EmbedderPort, LLMPort, StoragePort
from engram.core.models import Edge, EdgeType, Evidence, EvidenceKind, Message, Node, NodeType
from engram.core.recall import cosine_similarity
from engram.core.text import canonical_label, normalize_label, token_jaccard

_JACCARD_MERGE = 0.8  # ponytail: fixed; promote to KeeperParams if a sweep ever tunes it


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class KeeperParams:
    tau_high: float = 0.86
    tau_low: float = 0.72
    ewma_alpha: float = 0.3
    salience_bump: float = 0.3
    prune_floor: float = 0.05
    decay: float = 0.98


@dataclass
class _Work:
    node: Node
    touched: bool = False


class Keeper:
    def __init__(self, storage: StoragePort, llm: LLMPort, embedder: EmbedderPort,
                 params: KeeperParams, clock=None) -> None:
        self.storage = storage
        self.llm = llm
        self.embedder = embedder
        self.p = params
        self.clock = clock or _utcnow

    async def consolidate(self, learner_id: str) -> ConsolidationReport:
        async with self.storage.consolidation_lock(learner_id) as acquired:
            if not acquired:
                return ConsolidationReport(learner_id=learner_id, skipped=True)
            events = await self.storage.get_pending_events(learner_id)
            if not events:
                return ConsolidationReport(learner_id=learner_id, processed_events=0)
            try:
                plan = await self._plan(learner_id, events)
            except ExtractionError as exc:
                await self.storage.apply_consolidation(
                    ConsolidationPlan(
                        learner_id=learner_id,
                        audit=[AuditEntry(op="extract_failed", rationale=str(exc))],
                    )
                )
                return ConsolidationReport(
                    learner_id=learner_id, errors=[f"extract_failed: {exc}"]
                )
            await self.storage.apply_consolidation(plan)
            return self._report(plan)

    # --- planning (pure: no DB writes) ----------------------------------

    async def _plan(self, learner_id: str, events) -> ConsolidationPlan:
        extraction = await self._extract(events)
        extraction, dropped = filter_provenance(extraction, events)
        live = await self.storage.get_live_nodes(learner_id)
        now = self.clock()

        plan = ConsolidationPlan(
            learner_id=learner_id, processed_event_ids=[e.id for e in events]
        )
        for label in dropped:
            plan.audit.append(AuditEntry(
                op="link", rationale=f"dropped {label!r}: tutor-only provenance"))
        work: dict[str, _Work] = {n.id: _Work(node=n) for n in live if n.id}

        cand_vecs = (
            await self.embedder.embed([c.embed_text() for c in extraction.nodes])
            if extraction.nodes
            else []
        )
        label_to_id: dict[str, str] = {}
        new_counter = 0

        for cand, vec in zip(extraction.nodes, cand_vecs):
            target_id = await self._resolve(cand, vec, work, plan)
            if target_id is None:  # create new
                target_id = f"tmp-{new_counter}"
                new_counter += 1
                node = Node(
                    id=target_id,
                    learner_id=learner_id,
                    type=NodeType(cand.type),
                    label=cand.label,
                    summary=cand.summary,
                    mastery=None,
                    confidence=0.3,
                    salience=1.0,
                    importance=cand.importance,
                    embedding=list(vec),
                    last_seen_at=now,
                )
                work[target_id] = _Work(node=node)
                plan.new_nodes.append(node)
                plan.audit.append(AuditEntry(op="link", rationale=f"new node {cand.label}"))
            label_to_id[cand.label] = target_id
            self._apply_evidence(cand, target_id, work, plan)
            work[target_id].touched = True

        real_ids = [nid for nid in work if not nid.startswith("tmp-")]
        existing_edges = await self.storage.get_edges(learner_id, real_ids) if real_ids else []
        # Working copies — never mutate storage-owned Edge objects in place.
        by_pair: dict[frozenset, Edge] = {}
        for e in existing_edges:
            by_pair.setdefault(frozenset((e.source_id, e.target_id)), replace(e))
        pending_updates: dict[str, Edge] = {}
        bumped: set[str] = set()
        proposed: dict[frozenset, Edge] = {}
        for rel in extraction.relations:
            s = label_to_id.get(rel.source_label)
            t = label_to_id.get(rel.target_label)
            if not s or not t or s == t:
                continue
            new_type = EdgeType(rel.type)
            key = frozenset((s, t))
            ex = by_pair.get(key)
            if ex is not None:  # edge already in the graph (either direction)
                changed = False
                if ex.type == new_type:
                    if ex.weight < 1.0 and ex.id not in bumped:
                        ex.weight = min(1.0, ex.weight + 0.1)
                        bumped.add(ex.id or "")
                        changed = True
                elif edge_rank(new_type) > edge_rank(ex.type):
                    plan.audit.append(AuditEntry(
                        op="link",
                        rationale=f"upgraded {ex.type.value}->{new_type.value} "
                                  f"{rel.source_label}->{rel.target_label}"))
                    ex.type = new_type
                    ex.source_id, ex.target_id = s, t  # adopt proposal direction
                    changed = True
                # weaker or equal-rank different type: keep what we have
                if changed and ex.id:
                    pending_updates[ex.id] = ex
                continue
            dup = proposed.get(key)
            if dup is not None:  # proposed twice in this batch
                if edge_rank(new_type) > edge_rank(dup.type):
                    dup.type = new_type
                    dup.source_id, dup.target_id = s, t
                continue
            edge = Edge(learner_id=learner_id, source_id=s, target_id=t, type=new_type)
            proposed[key] = edge
            plan.new_edges.append(edge)
        plan.edge_updates.extend(pending_updates.values())

        self._decay_and_snapshot(work, now, plan)
        plan.audit.append(
            AuditEntry(op="consolidate", rationale=f"{len(extraction.nodes)} candidates")
        )
        return plan

    async def _extract(self, events) -> Extraction:
        msgs = build_extraction_messages(events)
        try:
            out = await self.llm.complete("extractor", msgs, schema=EXTRACTION_SCHEMA)
            return parse_extraction(out.text or "")
        except ExtractionError:
            repair = msgs + [
                Message(role="user", content="Return ONLY valid JSON matching the schema.")
            ]
            out = await self.llm.complete("extractor", repair, schema=EXTRACTION_SCHEMA)
            return parse_extraction(out.text or "")  # may raise -> consolidate aborts

    async def _resolve(self, cand, vec, work, plan) -> str | None:
        """Return an existing node id to attach to, or None to create new.

        Merge when normalized labels are equal or token-Jaccard >= 0.8 (lexical —
        applies to same-batch tmp nodes too), else cosine >= tau_high, else send
        the tau_low..tau_high band to the reflector. Never merges across
        NodeType (goal ≠ concept). (#6)
        """
        cand_type = NodeType(cand.type)
        cand_norm = normalize_label(cand.label)
        if cand_norm:
            for nid, w in work.items():
                if w.node.type != cand_type:
                    continue
                if cand_norm == normalize_label(w.node.label) or \
                        token_jaccard(cand.label, w.node.label) >= _JACCARD_MERGE:
                    plan.audit.append(AuditEntry(
                        op="merge",
                        rationale=f"merged {cand.label!r} into {w.node.label!r} (label match)"))
                    self._adopt_label(w, cand)
                    return nid
        best_id, best_sim = None, -1.0
        for nid, w in work.items():
            if nid.startswith("tmp-") or not w.node.embedding:
                continue
            if w.node.type != cand_type:
                continue
            sim = cosine_similarity(vec, w.node.embedding)
            if sim > best_sim:
                best_sim, best_id = sim, nid
        if best_id is not None and best_sim >= self.p.tau_high:
            self._adopt_label(work[best_id], cand)
            return best_id
        if best_id is not None and best_sim > self.p.tau_low:
            if await self._reflector_confirm(cand, work[best_id].node):
                plan.audit.append(AuditEntry(op="merge", rationale=f"merged {cand.label}"))
                self._adopt_label(work[best_id], cand)
                return best_id
        return None

    @staticmethod
    def _adopt_label(w, cand) -> None:
        """On merge, keep the more canonical of the two surface labels so display
        names stay stable and full (abbreviations lose to their expansion). The
        node is already marked touched by the caller, so a real node's new label
        persists via node_updates; a tmp node's via its new_nodes INSERT."""
        w.node.label = canonical_label(w.node.label, cand.label)

    async def _reflector_confirm(self, cand, node) -> bool:
        try:
            msgs = [
                Message(role="system", content="Answer only 'yes' or 'no'."),
                Message(
                    role="user",
                    content=(
                        "Are these the same learning concept?\n"
                        f"A: {cand.label} — {cand.summary}\n"
                        f"B: {node.label} — {node.summary}"
                    ),
                ),
            ]
            out = await self.llm.complete("reflector", msgs)
            return (out.text or "").strip().lower().startswith("y")
        except Exception:
            return False  # degrade: not-same -> create new

    def _apply_evidence(self, cand, target_id, work, plan) -> None:
        node = work[target_id].node
        for ev in cand.evidence:
            plan.new_evidence.append(
                Evidence(
                    node_id=target_id,
                    kind=EvidenceKind(ev.kind),
                    content=ev.content,
                    importance=ev.importance,
                )
            )
            if ev.importance is not None:
                node.importance = ewma(node.importance, ev.importance, self.p.ewma_alpha)
            obs = observation_for(ev.kind, ev.correct, ev.mastery)
            if obs is None:
                continue
            new_conf, conflicted = update_confidence(node.confidence, node.mastery, obs)
            node.mastery = ewma(node.mastery, obs, self.p.ewma_alpha)
            node.confidence = new_conf
            if conflicted:
                plan.audit.append(
                    AuditEntry(
                        op="resolve_contradiction",
                        rationale=f"{cand.label}: obs {obs} vs prior mastery",
                    )
                )

    def _decay_and_snapshot(self, work, now, plan) -> None:
        for nid, w in work.items():
            node = w.node
            if w.touched:
                node.salience = min(1.0, (node.salience or 0.0) + self.p.salience_bump)
                node.last_seen_at = now
                plan.mastery_history.append(
                    MasteryPoint(node_id=nid, mastery=node.mastery, confidence=node.confidence)
                )
            else:
                last = node.last_seen_at or now
                days = max(0.0, (now - last).total_seconds() / 86400)
                node.salience = decay_salience(node.salience, days, self.p.decay)
                if (node.salience or 0.0) < self.p.prune_floor:
                    node.forgotten_at = now
            if not nid.startswith("tmp-"):  # new nodes already carried in new_nodes
                plan.node_updates.append(node)

    def _report(self, plan) -> ConsolidationReport:
        return ConsolidationReport(
            learner_id=plan.learner_id,
            processed_events=len(plan.processed_event_ids),
            nodes_created=len(plan.new_nodes),
            nodes_updated=len(plan.node_updates),
            edges_created=len(plan.new_edges),
            merged=sum(1 for a in plan.audit if a.op == "merge"),
            forgotten=sum(1 for n in plan.node_updates if n.forgotten_at is not None),
        )

    async def repair_merges(self, learner_id: str) -> dict:
        """Retroactive dedup sweep over the live graph (#6 layer 3). Applies the
        same combined merge score as _resolve; keeps the older node id; merged
        fields: mastery from the higher-confidence node, max confidence/salience/
        importance. Re-reads after each merge — graphs are small.
        # ponytail: O(n^2) pair scan per pass; vector-search top-k if graphs grow.
        """
        async with self.storage.consolidation_lock(learner_id) as acquired:
            if not acquired:
                return {"merged": 0, "pairs": [], "skipped": True}
            pairs: list[str] = []
            rejected: set[frozenset[str]] = set()  # reflector-no pairs, persist across passes
            while True:
                live = await self.storage.get_live_nodes(learner_id)
                found = await self._find_dup_pair(live, rejected)
                if found is None:
                    break
                keep, drop = found
                hi = keep if (keep.confidence or 0.0) >= (drop.confidence or 0.0) else drop
                await self.storage.merge_nodes(
                    learner_id, keep.id, drop.id,
                    label=canonical_label(keep.label, drop.label),
                    mastery=hi.mastery,
                    confidence=max(keep.confidence or 0.0, drop.confidence or 0.0),
                    salience=max(keep.salience or 0.0, drop.salience or 0.0),
                    importance=(max(keep.importance or 0.0, drop.importance or 0.0)
                                if keep.importance is not None or drop.importance is not None
                                else None),
                    rationale=f"repair: merged {drop.label!r} into {keep.label!r}",
                )
                pairs.append(f"{drop.label!r} -> {keep.label!r}")
            return {"merged": len(pairs), "pairs": pairs, "skipped": False}

    async def _find_dup_pair(self, live, rejected: set[frozenset[str]]) -> tuple | None:
        """First (keep, drop) duplicate pair by the combined score, or None."""
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                if a.type != b.type:
                    continue
                pair_key = frozenset((a.id, b.id))
                if pair_key in rejected:
                    continue
                lexical = (normalize_label(a.label)
                           and normalize_label(a.label) == normalize_label(b.label)) \
                    or token_jaccard(a.label, b.label) >= _JACCARD_MERGE
                cos = (cosine_similarity(a.embedding, b.embedding)
                       if a.embedding and b.embedding else 0.0)
                same = lexical or cos >= self.p.tau_high
                if not same and self.p.tau_low < cos < self.p.tau_high:
                    same = await self._reflector_confirm(a, b)
                    if not same:
                        rejected.add(pair_key)
                if same:
                    keep, drop = (a, b) if a.created_at <= b.created_at else (b, a)
                    return keep, drop
        return None
