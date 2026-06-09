import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AuditEntry, ConsolidateStats, GraphResponse } from "./types";
import { getAudit, getGraph, postConsolidate } from "./api";
import GraphView from "./components/GraphView";
import NodeDetailPanel from "./components/NodeDetailPanel";
import ChatPanel from "./components/ChatPanel";
import IngestForm from "./components/IngestForm";

const EMPTY_GRAPH: GraphResponse = { nodes: [], edges: [] };

interface AppError {
  id: number;
  message: string;
}

export default function App() {
  // Learner selection: the input is editable; `learnerId` is what's loaded.
  const [learnerInput, setLearnerInput] = useState("alice");
  const [learnerId, setLearnerId] = useState("alice");

  const [graph, setGraph] = useState<GraphResponse>(EMPTY_GRAPH);
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [consolidating, setConsolidating] = useState(false);
  const [consolidateStats, setConsolidateStats] = useState<ConsolidateStats | null>(null);
  const [errors, setErrors] = useState<AppError[]>([]);
  const errorSeq = useRef(0);
  const statsTimer = useRef<number | undefined>(undefined);

  const pushError = useCallback((message: string) => {
    errorSeq.current += 1;
    const id = errorSeq.current;
    setErrors((prev) => [...prev.slice(-4), { id, message }]);
  }, []);

  const dismissError = (id: number) => setErrors((prev) => prev.filter((e) => e.id !== id));

  const refresh = useCallback(
    async (id: string) => {
      setLoading(true);
      const [graphRes, auditRes] = await Promise.allSettled([getGraph(id), getAudit(id)]);
      if (graphRes.status === "fulfilled") {
        setGraph(graphRes.value);
      } else {
        pushError((graphRes.reason as Error).message);
      }
      if (auditRes.status === "fulfilled") {
        setAuditEntries(auditRes.value.entries);
      } else {
        pushError((auditRes.reason as Error).message);
      }
      setLoading(false);
    },
    [pushError],
  );

  // Load on mount and whenever the active learner changes.
  useEffect(() => {
    setSelectedNodeId(null);
    setGraph(EMPTY_GRAPH);
    setAuditEntries([]);
    void refresh(learnerId);
  }, [learnerId, refresh]);

  function loadLearner() {
    const id = learnerInput.trim();
    if (!id) return;
    if (id === learnerId) {
      void refresh(id); // same learner -> just reload
    } else {
      setLearnerId(id);
    }
  }

  async function consolidateNow() {
    if (consolidating) return;
    setConsolidating(true);
    try {
      const res = await postConsolidate(learnerId);
      setConsolidateStats(res.stats);
      window.clearTimeout(statsTimer.current);
      statsTimer.current = window.setTimeout(() => setConsolidateStats(null), 8000);
      await refresh(learnerId);
    } catch (err) {
      pushError((err as Error).message);
    } finally {
      setConsolidating(false);
    }
  }

  const afterTurn = useCallback(() => {
    void refresh(learnerId);
  }, [refresh, learnerId]);

  const selectedNode = useMemo(
    () => graph.nodes.find((n) => n.id === selectedNodeId) ?? null,
    [graph, selectedNodeId],
  );

  return (
    <div className="app">
      <header className="topbar">
        <h1 className="brand">
          Engram <span className="muted">memory graph</span>
        </h1>
        <form
          className="learner-form"
          onSubmit={(e) => {
            e.preventDefault();
            loadLearner();
          }}
        >
          <label htmlFor="learner-input">learner</label>
          <input
            id="learner-input"
            value={learnerInput}
            onChange={(e) => setLearnerInput(e.target.value)}
            placeholder="learner_id"
          />
          <button type="submit" disabled={!learnerInput.trim()}>
            {loading ? "Loading…" : "Load"}
          </button>
        </form>
        <div className="topbar-right">
          <IngestForm learnerId={learnerId} onIngested={() => void refresh(learnerId)} onError={pushError} />
          <button className="consolidate-btn" onClick={() => void consolidateNow()} disabled={consolidating}>
            {consolidating ? "Consolidating…" : "Consolidate now"}
          </button>
        </div>
      </header>

      <main className={`main${selectedNode ? " with-detail" : ""}`}>
        {selectedNode && (
          <NodeDetailPanel
            node={selectedNode}
            auditEntries={auditEntries}
            onClose={() => setSelectedNodeId(null)}
            onError={pushError}
          />
        )}
        <section className="graph-area">
          <GraphView
            graph={graph}
            fitKey={learnerId}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
          />
          <div className="graph-stats muted small">
            {graph.nodes.length} nodes · {graph.edges.length} edges · learner {learnerId}
          </div>
        </section>
        <ChatPanel learnerId={learnerId} onAfterTurn={afterTurn} onError={pushError} />
      </main>

      {consolidateStats && (
        <div className="toast stats-toast" onClick={() => setConsolidateStats(null)}>
          <strong>Consolidated.</strong>{" "}
          {consolidateStats.events_processed} events → {consolidateStats.nodes_created} nodes created,{" "}
          {consolidateStats.nodes_updated} updated, {consolidateStats.edges_created} edges,{" "}
          {consolidateStats.merged} merged, {consolidateStats.pruned} pruned
        </div>
      )}

      <div className="error-stack">
        {errors.map((e) => (
          <div key={e.id} className="toast error-toast">
            <span>{e.message}</span>
            <button className="icon-btn" onClick={() => dismissError(e.id)} title="Dismiss">
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
