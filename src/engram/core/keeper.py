"""The Memory Keeper — plan, then commit.

consolidate() acquires a per-learner advisory lock, reads pending events + live
nodes, builds a ConsolidationPlan via a pure pipeline (extract → link/merge →
resolve → decay → prune → snapshot), and applies it in one atomic transaction.
New nodes carry temp ids remapped at commit. The planner never writes to the DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from engram.core.consolidation import (
    AuditEntry,
    ConsolidationPlan,
    ConsolidationReport,
    MasteryPoint,
)
from engram.core.extraction import (
    EXTRACTION_SCHEMA,
    Extraction,
    ExtractionError,
    build_extraction_messages,
    parse_extraction,
)
from engram.core.mastery import decay_salience, ewma, observation_for, update_confidence
from engram.core.models import Edge, EdgeType, Evidence, EvidenceKind, Message, Node, NodeType
from engram.core.recall import cosine_similarity


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
    def __init__(self, storage, llm, embedder, params: KeeperParams, clock=None) -> None:
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
        live = await self.storage.get_live_nodes(learner_id)
        now = self.clock()

        plan = ConsolidationPlan(
            learner_id=learner_id, processed_event_ids=[e.id for e in events]
        )
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
                    embedding=list(vec),
                    last_seen_at=now,
                )
                work[target_id] = _Work(node=node)
                plan.new_nodes.append(node)
                plan.audit.append(AuditEntry(op="link", rationale=f"new node {cand.label}"))
            label_to_id[cand.label] = target_id
            self._apply_evidence(cand, target_id, work, plan)
            work[target_id].touched = True

        for rel in extraction.relations:
            s = label_to_id.get(rel.source_label)
            t = label_to_id.get(rel.target_label)
            if s and t:
                plan.new_edges.append(
                    Edge(learner_id=learner_id, source_id=s, target_id=t, type=EdgeType(rel.type))
                )

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
        """Return an existing node id to attach to, or None to create new."""
        best_id, best_sim = None, -1.0
        for nid, w in work.items():
            if nid.startswith("tmp-") or not w.node.embedding:
                continue
            sim = cosine_similarity(vec, w.node.embedding)
            if sim > best_sim:
                best_sim, best_id = sim, nid
        if best_id is not None and best_sim >= self.p.tau_high:
            return best_id
        if best_id is not None and best_sim > self.p.tau_low:
            if await self._reflector_confirm(cand, work[best_id].node):
                plan.audit.append(AuditEntry(op="merge", rationale=f"merged {cand.label}"))
                return best_id
        return None

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
