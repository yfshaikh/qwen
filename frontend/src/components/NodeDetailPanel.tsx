import { useEffect, useState } from "react";
import type { AuditEntry, Evidence, GraphNode } from "../types";
import { getEvidence } from "../api";
import { fmtDate, masteryColor, pct } from "../format";

interface Props {
  node: GraphNode;
  auditEntries: AuditEntry[];
  onClose: () => void;
  onError: (message: string) => void;
}

function Bar({ label, value, color }: { label: string; value: number | null; color?: string }) {
  const width = value == null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="bar-row">
      <span className="bar-label">{label}</span>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${width}%`, background: color ?? "#3b82f6" }} />
      </div>
      <span className="bar-value">{pct(value)}</span>
    </div>
  );
}

/** Audit entries that mention this node id in their refs, newest-first. */
function relevantAudit(
  entries: AuditEntry[],
  nodeId: string,
): { audit: AuditEntry[]; filtered: boolean } {
  const mentions = entries.filter((e) => {
    try {
      return (
        JSON.stringify(e.input_refs ?? {}).includes(nodeId) ||
        JSON.stringify(e.output_refs ?? {}).includes(nodeId)
      );
    } catch {
      return false;
    }
  });
  if (mentions.length > 0) return { audit: mentions.slice(0, 8), filtered: true };
  return { audit: entries.slice(0, 8), filtered: false };
}

export default function NodeDetailPanel({ node, auditEntries, onClose, onError }: Props) {
  const [evidence, setEvidence] = useState<Evidence[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setEvidence(null);
    getEvidence(node.id)
      .then((res) => {
        if (!cancelled) setEvidence(res.evidence);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setEvidence([]);
          onError(err.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [node.id, onError]);

  const { audit, filtered: auditIsFiltered } = relevantAudit(auditEntries, node.id);

  return (
    <aside className="detail-panel">
      <div className="detail-header">
        <div>
          <span className={`badge badge-${node.type}`}>{node.type}</span>
          <h2>{node.label}</h2>
        </div>
        <button className="icon-btn" onClick={onClose} title="Close">
          ×
        </button>
      </div>

      {node.summary && <p className="detail-summary">{node.summary}</p>}

      <section>
        <Bar label="mastery" value={node.mastery} color={masteryColor(node.mastery)} />
        <Bar label="confidence" value={node.confidence} />
        <Bar label="salience" value={node.salience} color="#8b5cf6" />
        <div className="detail-meta">
          <span>
            evidence: <strong>{node.evidence_count ?? 0}</strong>
          </span>
          <span>
            last seen: <strong>{fmtDate(node.last_seen_at)}</strong>
          </span>
          {node.forgotten_at && (
            <span className="forgotten-tag">forgotten at {fmtDate(node.forgotten_at)}</span>
          )}
        </div>
      </section>

      <section>
        <h3>Evidence</h3>
        {evidence === null && <p className="muted">Loading evidence…</p>}
        {evidence !== null && evidence.length === 0 && <p className="muted">No evidence yet.</p>}
        <ul className="evidence-list">
          {(evidence ?? []).map((ev) => (
            <li key={ev.id}>
              <div className="evidence-head">
                <span className="kind-chip">{ev.kind}</span>
                <span className="muted small">
                  importance {ev.importance == null ? "—" : ev.importance.toFixed(2)} ·{" "}
                  {fmtDate(ev.created_at)}
                </span>
              </div>
              {ev.content && <div className="evidence-content">{ev.content}</div>}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3>
          Provenance{" "}
          <span className="muted small">{auditIsFiltered ? "(mentions this node)" : "(recent)"}</span>
        </h3>
        {audit.length === 0 && <p className="muted">No audit entries yet.</p>}
        <ul className="audit-list">
          {audit.map((entry, i) => (
            <li key={`${entry.ts ?? ""}-${i}`}>
              <div className="audit-head">
                <span className="kind-chip op-chip">{entry.op}</span>
                <span className="muted small">{fmtDate(entry.ts)}</span>
              </div>
              {entry.rationale && <div className="audit-rationale">{entry.rationale}</div>}
            </li>
          ))}
        </ul>
      </section>
    </aside>
  );
}
