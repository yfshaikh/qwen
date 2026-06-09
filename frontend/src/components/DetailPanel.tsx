import type { AuditEntryItem, GraphNode } from "../lib/types";
import { fmtNum, fmtTime, masteryColor, typeMeta } from "../lib/visual";

interface Props {
  node: GraphNode | null;
  audit: AuditEntryItem[];
}

function Stat({ label, value, bar }: { label: string; value: string; bar?: number | null }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
        <span style={{ color: "#6b7280" }}>{label}</span>
        <span style={{ fontWeight: 600, fontFamily: "monospace" }}>{value}</span>
      </div>
      {bar != null && (
        <div style={{ height: 5, background: "#e5e7eb", borderRadius: 3, marginTop: 3 }}>
          <div
            style={{
              width: `${Math.max(0, Math.min(1, bar)) * 100}%`,
              height: "100%",
              background: masteryColor(bar),
              borderRadius: 3,
            }}
          />
        </div>
      )}
    </div>
  );
}

export default function DetailPanel({ node, audit }: Props) {
  if (!node) {
    return (
      <div style={{ padding: 16, color: "#6b7280", fontSize: 13 }}>
        Click a node in the graph to inspect its mastery, salience, and provenance.
      </div>
    );
  }

  const meta = typeMeta(node.type);
  // Show audit entries that reference this node where possible, otherwise the
  // recent feed (the API does not expose per-node evidence directly).
  const refsNode = (e: AuditEntryItem): boolean => {
    const blob = JSON.stringify([e.input_refs, e.output_refs, e.rationale]);
    return blob.includes(node.id) || (e.rationale ?? "").includes(node.label);
  };
  const related = audit.filter(refsNode);
  const shown = related.length > 0 ? related : audit;

  return (
    <div style={{ padding: 16, overflowY: "auto", height: "100%", boxSizing: "border-box" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            background: meta.accent,
            color: "#fff",
            fontSize: 10,
            padding: "2px 6px",
            borderRadius: 4,
            textTransform: "uppercase",
            letterSpacing: 0.5,
          }}
        >
          {meta.label}
        </span>
        <h3 style={{ margin: 0, fontSize: 16 }}>{node.label}</h3>
      </div>

      {node.summary && (
        <p style={{ fontSize: 13, color: "#374151", marginTop: 8 }}>{node.summary}</p>
      )}

      <div style={{ marginTop: 12 }}>
        <Stat label="mastery" value={fmtNum(node.mastery)} bar={node.mastery} />
        <Stat label="confidence" value={fmtNum(node.confidence)} bar={node.confidence} />
        <Stat label="salience" value={fmtNum(node.salience)} bar={node.salience} />
        <Stat label="evidence_count" value={String(node.evidence_count)} />
        <Stat label="last_seen_at" value={fmtTime(node.last_seen_at)} />
        {node.forgotten_at && (
          <Stat label="forgotten_at" value={fmtTime(node.forgotten_at)} />
        )}
      </div>

      <h4 style={{ marginBottom: 6, marginTop: 18, fontSize: 13 }}>
        Provenance / audit{related.length > 0 ? " (related)" : " (recent)"}
      </h4>
      {shown.length === 0 ? (
        <div style={{ fontSize: 12, color: "#9ca3af" }}>No audit entries yet.</div>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {shown.slice(0, 12).map((e, i) => (
            <li
              key={i}
              style={{
                borderLeft: "3px solid #cbd5e1",
                paddingLeft: 8,
                marginBottom: 8,
                fontSize: 12,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 6 }}>
                <strong style={{ color: "#1f2937" }}>{e.op}</strong>
                <span style={{ color: "#9ca3af", whiteSpace: "nowrap" }}>{fmtTime(e.ts)}</span>
              </div>
              {e.rationale && (
                <div style={{ color: "#4b5563", marginTop: 2 }}>{e.rationale}</div>
              )}
              {(e.model || e.tokens != null) && (
                <div style={{ color: "#9ca3af", marginTop: 2 }}>
                  {e.model ?? "—"}
                  {e.tokens != null ? ` · ${e.tokens} tok` : ""}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
