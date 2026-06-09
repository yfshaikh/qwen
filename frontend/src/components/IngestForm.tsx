import { useState } from "react";
import { api, ApiError } from "../lib/api";

interface Props {
  learnerId: string;
  onError: (msg: string) => void;
  onInfo: (msg: string) => void;
}

// Small helper to POST a single raw event to /ingest, so a demo can seed events
// without curl. Consolidate afterwards to fold it into the graph.
export default function IngestForm({ learnerId, onError, onInfo }: Props) {
  const [type, setType] = useState("note");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true);
    try {
      const res = await api.ingest(learnerId, [{ type, text: t }]);
      onInfo(`Ingested ${res.ids.length} event(s). Run "Consolidate now" to fold into the graph.`);
      setText("");
    } catch (err) {
      onError(`Ingest failed: ${err instanceof ApiError ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <details style={{ borderTop: "1px solid #e5e7eb", padding: "8px 12px" }}>
      <summary style={{ cursor: "pointer", fontSize: 12, fontWeight: 600, color: "#475569" }}>
        Ingest event (seed a demo)
      </summary>
      <div style={{ display: "flex", gap: 6, marginTop: 8, alignItems: "center" }}>
        <input
          value={type}
          onChange={(e) => setType(e.target.value)}
          placeholder="type"
          title="event type, e.g. note, asked_about, quiz_correct"
          style={{ width: 110, padding: "5px 7px", border: "1px solid #cbd5e1", borderRadius: 6 }}
        />
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          placeholder="event text..."
          style={{ flex: 1, padding: "5px 7px", border: "1px solid #cbd5e1", borderRadius: 6 }}
        />
        <button onClick={submit} disabled={busy} className="btn">
          {busy ? "..." : "Ingest"}
        </button>
      </div>
    </details>
  );
}
