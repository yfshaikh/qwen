import { masteryColor, typeMeta } from "../lib/visual";
import type { NodeType } from "../lib/types";

// Compact legend explaining the visual encoding.
export default function Legend() {
  const types: NodeType[] = ["concept", "preference", "goal"];
  return (
    <div
      style={{
        position: "absolute",
        right: 10,
        bottom: 10,
        background: "rgba(255,255,255,0.95)",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: 10,
        fontSize: 11,
        boxShadow: "0 1px 6px rgba(0,0,0,0.12)",
        zIndex: 5,
        maxWidth: 230,
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: 4 }}>Legend</div>

      <div style={{ marginBottom: 4 }}>
        mastery (size + color):
        <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 2 }}>
          {[0, 0.25, 0.5, 0.75, 1].map((m) => (
            <span
              key={m}
              style={{
                width: 14,
                height: 14,
                borderRadius: "50%",
                background: masteryColor(m),
                display: "inline-block",
              }}
            />
          ))}
          <span style={{ color: "#6b7280" }}>low → high</span>
        </div>
      </div>

      <div style={{ marginBottom: 4 }}>
        salience = opacity (faded = forgotten)
      </div>

      <div style={{ marginBottom: 4 }}>
        type:
        {types.map((t) => {
          const m = typeMeta(t);
          return (
            <span key={t} style={{ marginLeft: 6 }}>
              <span
                style={{
                  background: m.accent,
                  color: "#fff",
                  borderRadius: "50%",
                  padding: "0 4px",
                  fontSize: 9,
                }}
              >
                {m.badge}
              </span>{" "}
              {m.label}
            </span>
          );
        })}
      </div>

      <div>
        edges:
        <div style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 2 }}>
          <span>
            <svg width="34" height="8">
              <line x1="0" y1="4" x2="34" y2="4" stroke="#475569" strokeWidth="2.5" />
            </svg>{" "}
            prerequisite →
          </span>
          <span>
            <svg width="34" height="8">
              <line
                x1="0"
                y1="4"
                x2="34"
                y2="4"
                stroke="#475569"
                strokeWidth="2"
                strokeDasharray="6 4"
              />
            </svg>{" "}
            relates_to
          </span>
          <span>
            <svg width="34" height="8">
              <line x1="0" y1="4" x2="34" y2="4" stroke="#475569" strokeWidth="1" />
            </svg>{" "}
            part_of
          </span>
        </div>
      </div>
    </div>
  );
}
