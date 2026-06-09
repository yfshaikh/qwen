import { useCallback, useEffect, useMemo, useState } from "react";
import { api, API_BASE, ApiError } from "./lib/api";
import type { AuditEntryItem, ConsolidateStats, GraphView } from "./lib/types";
import MemoryGraph from "./components/MemoryGraph";
import DetailPanel from "./components/DetailPanel";
import ChatPanel from "./components/ChatPanel";
import IngestForm from "./components/IngestForm";
import Legend from "./components/Legend";

const EMPTY_GRAPH: GraphView = { nodes: [], edges: [] };

type Tab = "detail" | "chat";

interface Toast {
  kind: "error" | "info";
  text: string;
}

export default function App() {
  const [learnerInput, setLearnerInput] = useState("alice");
  const [learnerId, setLearnerId] = useState<string | null>(null);
  const [graph, setGraph] = useState<GraphView>(EMPTY_GRAPH);
  const [audit, setAudit] = useState<AuditEntryItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("detail");
  const [loading, setLoading] = useState(false);
  const [consolidating, setConsolidating] = useState(false);
  const [stats, setStats] = useState<ConsolidateStats | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);

  const showError = useCallback((text: string) => setToast({ kind: "error", text }), []);
  const showInfo = useCallback((text: string) => setToast({ kind: "info", text }), []);

  // Auto-dismiss toasts.
  useEffect(() => {
    if (!toast) return;
    const ms = toast.kind === "error" ? 7000 : 4000;
    const id = setTimeout(() => setToast(null), ms);
    return () => clearTimeout(id);
  }, [toast]);

  const refresh = useCallback(
    async (id: string) => {
      // Graph and audit are independent; load both, but don't let an audit
      // failure hide the graph (and vice versa).
      const [g, a] = await Promise.allSettled([api.getGraph(id), api.getAudit(id)]);
      if (g.status === "fulfilled") {
        setGraph(g.value);
      } else {
        const e = g.reason;
        showError(`Load graph failed: ${e instanceof ApiError ? e.message : String(e)}`);
      }
      if (a.status === "fulfilled") setAudit(a.value.entries);
      else setAudit([]);
    },
    [showError],
  );

  async function loadLearner() {
    const id = learnerInput.trim();
    if (!id) return;
    setLearnerId(id);
    setSelectedId(null);
    setStats(null);
    setLoading(true);
    await refresh(id);
    setLoading(false);
  }

  async function consolidate() {
    if (!learnerId || consolidating) return;
    setConsolidating(true);
    try {
      const res = await api.consolidate(learnerId);
      setStats(res.stats);
      showInfo(
        `Consolidated: +${res.stats.nodes_created} nodes, ${res.stats.nodes_updated} updated, ` +
          `${res.stats.merged} merged, ${res.stats.pruned} pruned.`,
      );
      await refresh(learnerId);
    } catch (err) {
      showError(`Consolidate failed: ${err instanceof ApiError ? err.message : String(err)}`);
    } finally {
      setConsolidating(false);
    }
  }

  const selectedNode = useMemo(
    () => graph.nodes.find((n) => n.id === selectedId) ?? null,
    [graph.nodes, selectedId],
  );

  // Clicking a node jumps to the detail tab.
  const onSelect = useCallback((id: string | null) => {
    setSelectedId(id);
    if (id) setTab("detail");
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          Engram <span className="sub">memory graph</span>
        </div>
        <div className="learner">
          <input
            value={learnerInput}
            onChange={(e) => setLearnerInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") loadLearner();
            }}
            placeholder="learner_id"
            aria-label="learner_id"
          />
          <button className="btn primary" onClick={loadLearner} disabled={loading}>
            {loading ? "Loading..." : "Load"}
          </button>
          <button
            className="btn"
            onClick={consolidate}
            disabled={!learnerId || consolidating}
            title="Run the Memory Keeper for this learner, then refresh"
          >
            {consolidating ? "Consolidating..." : "Consolidate now"}
          </button>
          {stats && (
            <span className="stats" title="last consolidate stats">
              proc {stats.events_processed} · +{stats.nodes_created}n · ~{stats.nodes_updated}n ·{" "}
              {stats.edges_created}e · merged {stats.merged} · pruned {stats.pruned}
            </span>
          )}
        </div>
        <div className="api-base" title="API base URL">
          API: {API_BASE || "(dev proxy → :8000)"}
        </div>
      </header>

      <main className="layout">
        <section className="canvas">
          {!learnerId ? (
            <div className="placeholder">
              Enter a <code>learner_id</code> and click <strong>Load</strong> to render the
              memory graph.
            </div>
          ) : graph.nodes.length === 0 ? (
            <div className="placeholder">
              No memory nodes for <code>{learnerId}</code> yet. Ingest some events and click{" "}
              <strong>Consolidate now</strong> to build the graph.
            </div>
          ) : (
            <>
              <MemoryGraph graph={graph} selectedId={selectedId} onSelect={onSelect} />
              <Legend />
            </>
          )}
        </section>

        <aside className="side">
          <div className="tabs">
            <button
              className={tab === "detail" ? "tab active" : "tab"}
              onClick={() => setTab("detail")}
            >
              Detail
            </button>
            <button
              className={tab === "chat" ? "tab active" : "tab"}
              onClick={() => setTab("chat")}
            >
              Chat
            </button>
          </div>
          <div className="side-body">
            {tab === "detail" ? (
              <DetailPanel node={selectedNode} audit={audit} />
            ) : learnerId ? (
              <ChatPanel
                learnerId={learnerId}
                onError={showError}
                onTurnComplete={() => refresh(learnerId)}
              />
            ) : (
              <div style={{ padding: 16, color: "#6b7280", fontSize: 13 }}>
                Load a learner to chat with the tutor.
              </div>
            )}
          </div>
          {learnerId && (
            <IngestForm learnerId={learnerId} onError={showError} onInfo={showInfo} />
          )}
        </aside>
      </main>

      {toast && (
        <div className={`toast ${toast.kind}`} onClick={() => setToast(null)}>
          {toast.text}
        </div>
      )}
    </div>
  );
}
