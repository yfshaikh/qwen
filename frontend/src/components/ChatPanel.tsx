import { useState } from "react";
import { api, ApiError } from "../lib/api";
import type { TutorTurnResult } from "../lib/types";

interface Props {
  learnerId: string;
  onError: (msg: string) => void;
  onTurnComplete: () => void; // refresh graph + audit after a turn
}

interface ChatLine {
  role: "user" | "tutor";
  text: string;
  recall?: string;
}

export default function ChatPanel({ learnerId, onError, onTurnComplete }: Props) {
  const [message, setMessage] = useState("");
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [busy, setBusy] = useState(false);

  async function send() {
    const msg = message.trim();
    if (!msg || busy) return;
    setBusy(true);
    setLines((prev) => [...prev, { role: "user", text: msg }]);
    setMessage("");
    try {
      const res: TutorTurnResult = await api.tutorTurn(learnerId, msg);
      setLines((prev) => [
        ...prev,
        {
          role: "tutor",
          text: res.reply || "(empty reply — backend may be missing an OpenRouter key)",
          recall: res.recall?.text_block,
        },
      ]);
      onTurnComplete();
    } catch (err) {
      const m = err instanceof ApiError ? err.message : String(err);
      onError(`Tutor turn failed: ${m}`);
      setLines((prev) => [...prev, { role: "tutor", text: `[error] ${m}` }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>
        {lines.length === 0 && (
          <div style={{ color: "#9ca3af", fontSize: 13 }}>
            Ask the tutor something. Its reply and the memory it recalled appear here;
            the graph refreshes after each turn.
          </div>
        )}
        {lines.map((l, i) => (
          <div key={i} style={{ marginBottom: 10 }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: l.role === "user" ? "#2563eb" : "#0d9488",
                textTransform: "uppercase",
              }}
            >
              {l.role}
            </div>
            <div style={{ fontSize: 13, color: "#1f2937", whiteSpace: "pre-wrap" }}>{l.text}</div>
            {l.recall && (
              <div
                style={{
                  marginTop: 4,
                  fontSize: 11,
                  background: "#f1f5f9",
                  border: "1px solid #e2e8f0",
                  borderRadius: 6,
                  padding: "6px 8px",
                  color: "#475569",
                }}
              >
                <div style={{ fontWeight: 700, marginBottom: 2 }}>what the tutor remembered</div>
                <div style={{ whiteSpace: "pre-wrap" }}>{l.recall}</div>
              </div>
            )}
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 6, padding: 8, borderTop: "1px solid #e5e7eb" }}>
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") send();
          }}
          placeholder="Message the tutor..."
          disabled={busy}
          style={{ flex: 1, padding: "6px 8px", border: "1px solid #cbd5e1", borderRadius: 6 }}
        />
        <button onClick={send} disabled={busy} className="btn">
          {busy ? "..." : "Send"}
        </button>
      </div>
    </div>
  );
}
