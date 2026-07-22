"""EngramHost — the resilient embedding runtime every host used to hand-roll.

Construction NEVER raises; `start()` is the only place init/connect failures
surface (logged once, latched). When disabled, `host.memory` is a DisabledEngram
null object: same verbs, typed empty returns, never raises — call sites need no
None-checks and no try/except.

Per-process state (task set, consolidating flags): multi-worker deployments
need a shared store for the status flag — same caveat as before, now in one place.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from engram.core.consolidation import ConsolidationReport
from engram.core.models import GraphView, LearningEvent, RecallResult

# Deliberately "engram.host", not this module's path (engram.runtime.host): the
# logger name is an operational contract that consumers' log filters key on, so it
# stays stable across internal moves. Don't "fix" it to match the module.
logger = logging.getLogger("engram.host")


class DisabledEngram:
    """Null-object Engram: every verb returns its typed empty result."""

    enabled = False
    # Present so attribute access on a disabled host degrades to None rather than
    # AttributeError (the real Engram exposes these). Callers should still gate on
    # host.enabled; these keep `getattr(host.memory, "storage", None)` honest.
    storage = None
    settings = None

    async def ingest(self, events: list[LearningEvent]) -> None:
        return None

    async def recall(self, learner_id: str, query: str, budget: int | None = None) -> RecallResult:
        return RecallResult(text_block="", subgraph={"nodes": [], "edges": []})

    async def consolidate(self, learner_id: str) -> ConsolidationReport:
        return ConsolidationReport(learner_id=learner_id, skipped=True)

    async def repair_merges(self, learner_id: str) -> dict:
        return {"merged": 0, "pairs": [], "skipped": True}

    async def seed_ontology(self, learner_id: str, ontology: Any) -> dict:
        return {"inserted": 0, "updated": 0, "edges": 0, "skipped": True}

    async def graph(self, learner_id: str, focus: str | None = None) -> GraphView:
        return GraphView(nodes=[], edges=[])

    async def audit(self, learner_id: str, since: Any = None, limit: int = 100) -> list:
        return []

    async def events(self, learner_id: str, limit: int = 200) -> list:
        return []

    async def health(self) -> bool:
        return False

    # voice-session passthroughs (facade parity — Marfini uses Supabase for
    # voice, but a disabled host must degrade every facade verb, not most)
    async def create_voice_session(self, learner_id: str) -> str:
        return ""

    async def end_voice_session(self, session_id: str) -> None:
        return None

    async def append_voice_turn(self, session_id, learner_id, role, text) -> str:
        return ""

    async def list_voice_sessions(self, learner_id: str, limit: int = 50) -> list:
        return []

    async def list_voice_turns(self, session_id: str) -> list:
        return []

    add = ingest
    search = recall


_DISABLED = DisabledEngram()


class EngramHost:
    def __init__(self, engram: Any = None, *, from_env_kwargs: dict | None = None) -> None:
        self._injected = engram      # an injected instance survives aclose/failure
        self._engram = engram        # (it is NEVER replaced by a from_env rebuild)
        self._kwargs = dict(from_env_kwargs or {})
        self._started = False
        self._failed = False
        self._tasks: set[asyncio.Task] = set()          # Task 4 fills these
        self._consolidating: dict[str, dict] = {}       # Task 4
        self._seeding: dict[str, asyncio.Task] = {}     # in-flight ontology seeds
        # learner_id -> most recent ConsolidationReport. consolidate_soon is
        # fire-and-forget, so without this the report is visible only in logs —
        # hosts that render a "keeper log" (Marfini's memory page) read it here.
        self._last_reports: dict[str, ConsolidationReport] = {}
        # test seam: swap the factory without touching Engram
        from engram.runtime.factory import from_env
        self._engram_factory = from_env

    @classmethod
    def from_env(cls, **kwargs: Any) -> "EngramHost":
        return cls(from_env_kwargs=kwargs)

    @property
    def enabled(self) -> bool:
        return self._started and not self._failed

    @property
    def memory(self) -> Any:
        return self._engram if self.enabled else _DISABLED

    async def start(self) -> bool:
        if self.enabled:
            return True
        if self._failed:
            return False  # latched; aclose() clears the latch
        try:
            if self._engram is None:
                self._engram = self._engram_factory(**self._kwargs)
            await self._engram.connect()
            self._started = True
            return True
        except Exception as exc:  # noqa: BLE001 — degradation is the contract
            logger.error("Engram start failed (memory disabled): %s", exc)
            # A factory-built instance may have opened a partial asyncpg pool
            # before connect() raised — close it (best-effort) so connections
            # don't leak. An injected instance is the caller's to manage.
            if self._engram is not None and self._engram is not self._injected:
                try:
                    await self._engram.aclose()
                except Exception:  # noqa: BLE001 — best-effort cleanup
                    pass
            self._engram = self._injected  # never discard an injected instance
            self._failed = True
            self._started = False
            return False

    async def aclose(self) -> None:
        # Disable FIRST: during the cancel/await window below other coroutines
        # run, and consolidate_soon must refuse new work while we drain.
        self._started = False
        self._failed = False  # E2: restart allowed after aclose
        for t in list(self._tasks):
            t.cancel()
        for t in list(self._tasks):
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()
        self._consolidating.clear()
        self._seeding.clear()
        if self._engram is not None:
            try:
                await self._engram.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Engram close failed: %s", exc)
        self._engram = self._injected  # factory-built hosts rebuild in start()

    async def __aenter__(self) -> "EngramHost":
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # --- ontology seeding (fire-and-forget, host-owned) ------------------

    def seed_soon(self, learner_id: str, ontology: Any) -> None:
        """Fire-and-forget curriculum seed, owned by the host (NOT the caller's
        request). Survives the originating request/websocket closing — the task
        lives on the process-wide host and runs to completion server-side.

        Idempotent and coalesced: if a seed for this learner is already in
        flight, this is a no-op (re-seeding produces the same graph; the next
        session picks up any curriculum edit anyway). Safe to call on every
        session start. A disabled host seeds nothing.

        Robust to interruption: seed_ontology's DB write is one transaction
        (atomic — no half-seeded graph) and idempotent (a crash self-heals on
        the next call), so there is no partial-state to clean up.
        """
        if not self.enabled:
            return
        existing = self._seeding.get(learner_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(self.memory.seed_ontology(learner_id, ontology),
                                   name=f"engram-seed:{learner_id}")
        self._seeding[learner_id] = task
        self._tasks.add(task)

        def _done(t: asyncio.Task) -> None:
            if self._seeding.get(learner_id) is t:
                self._seeding.pop(learner_id, None)
            self._reap(t)

        task.add_done_callback(_done)

    def is_seeding(self, learner_id: str) -> bool:
        t = self._seeding.get(learner_id)
        return t is not None and not t.done()

    async def _await_seed(self, learner_id: str) -> None:
        """Block until any in-flight seed for this learner completes. Called
        before consolidation so it never runs open-mode against a half-seeded
        graph (which would mint dynamic concepts duplicating the ontology's). A
        failed seed is swallowed — consolidation proceeds degraded and the seed
        retries next session."""
        t = self._seeding.get(learner_id)
        if t is not None and not t.done():
            try:
                await t
            except Exception:  # noqa: BLE001 — seed failure must not block consolidation
                pass

    # --- consolidation orchestration (E3) --------------------------------

    def consolidate_soon(self, learner_id: str) -> None:
        """Fire-and-forget consolidation with per-learner coalescing: while a
        run is in flight, further calls mark ONE rerun instead of stacking."""
        if not self.enabled:
            return
        state = self._consolidating.get(learner_id)
        if state is not None:
            state["rerun"] = True
            return
        self._consolidating[learner_id] = {"rerun": False}
        task = asyncio.create_task(self._consolidate_loop(learner_id),
                                   name=f"engram-consolidate:{learner_id}")
        self._tasks.add(task)
        task.add_done_callback(self._reap)

    async def _consolidate_loop(self, learner_id: str) -> None:
        try:
            # Never consolidate over a half-seeded graph — wait out any in-flight
            # ontology seed first, so closed-mode extraction has its vocabulary.
            await self._await_seed(learner_id)
            while True:
                try:
                    report = await self.memory.consolidate(learner_id)
                    self._last_reports[learner_id] = report
                    logger.info("consolidation for %s complete: %s", learner_id, report)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — never unobserved
                    logger.warning("consolidation failed for %s: %s", learner_id, exc)
                state = self._consolidating.get(learner_id)
                if not state or not state["rerun"]:
                    break
                state["rerun"] = False
        finally:
            self._consolidating.pop(learner_id, None)

    def is_consolidating(self, learner_id: str) -> bool:
        return learner_id in self._consolidating

    def last_report(self, learner_id: str) -> ConsolidationReport | None:
        """Most recent consolidation report for this learner, or None if this
        process hasn't consolidated it yet. Per-process, like the status flag."""
        return self._last_reports.get(learner_id)

    # --- turn logging (E4) ------------------------------------------------

    async def log_turn(self, learner_id: str, user_text: str | None = None,
                       tutor_reply: str | None = None, *,
                       refs: dict | None = None) -> bool:
        events = []
        if user_text and user_text.strip():
            events.append(LearningEvent(learner_id=learner_id, type="utterance",
                                        text=user_text, refs=dict(refs or {})))
        if tutor_reply and tutor_reply.strip():
            events.append(LearningEvent(learner_id=learner_id, type="tutor_explanation",
                                        text=tutor_reply, refs=dict(refs or {})))
        return await self._safe_ingest(events)

    async def log_quiz(self, learner_id: str, item: str, correct: bool, *,
                       mastery: float | None = None, refs: dict | None = None) -> bool:
        if not item or not item.strip():
            return False
        signals: dict = {"correct": correct}
        if mastery is not None:
            signals["mastery"] = mastery
        return await self._safe_ingest([LearningEvent(
            learner_id=learner_id, type="quiz_result", text=item,
            signals=signals, refs=dict(refs or {}))])

    async def log_note(self, learner_id: str, text: str, *,
                       refs: dict | None = None) -> bool:
        if not text or not text.strip():
            return False
        return await self._safe_ingest([LearningEvent(
            learner_id=learner_id, type="note", text=text, refs=dict(refs or {}))])

    def _reap(self, task: asyncio.Task) -> None:
        """Done-callback for owned background tasks: unregister AND retrieve the
        exception so a write that outlives a cancelled caller can never surface
        as an unretrieved-task warning with its failure silently lost."""
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            # Name the task kind: this one warning is the ONLY trace a
            # fire-and-forget failure leaves, and "ingest failed" sent a real
            # debugging session hunting the wrong subsystem when the dead task
            # was a seed (Marfini, 2026-07-18).
            logger.warning("background task %s failed: %s", task.get_name(), exc)

    async def _safe_ingest(self, events: list[LearningEvent]) -> bool:
        """Shielded, never-raise write. Events were built eagerly by the caller,
        so a cancellation of the surrounding turn cannot drop a half-built batch.
        Exceptions are logged by _reap (the single observer) whether the caller
        awaited to completion or was cancelled mid-write."""
        if not events or not self.enabled:
            return False
        # Own the shielded write: registered in _tasks so aclose() drains it and
        # _reap observes its exception even when the caller is cancelled.
        task = asyncio.ensure_future(self.memory.ingest(events))
        task.set_name(f"engram-ingest:{events[0].learner_id}")
        self._tasks.add(task)
        task.add_done_callback(self._reap)
        try:
            await asyncio.shield(task)
            return True
        except asyncio.CancelledError:
            raise  # cooperative: shield kept the write alive; propagate the cancel
        except Exception:  # noqa: BLE001 — logged by _reap; caller just gets False
            return False
