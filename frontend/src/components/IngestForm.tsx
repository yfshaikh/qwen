import { useState } from "react";
import { postIngest } from "../api";

const COMMON_TYPES = [
  "explained",
  "asked_about",
  "quiz_correct",
  "quiz_wrong",
  "note",
  "struggle",
  "demonstrated",
];

interface Props {
  learnerId: string;
  onIngested: (ids: string[]) => void;
  onError: (message: string) => void;
}

/** Collapsible helper to POST a single raw event to /ingest for demo seeding. */
export default function IngestForm({ learnerId, onIngested, onError }: Props) {
  const [type, setType] = useState("note");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);

  async function submit() {
    if (!type.trim() || busy) return;
    setBusy(true);
    setLastResult(null);
    try {
      const event: { type: string; text?: string } = { type: type.trim() };
      if (text.trim()) event.text = text.trim();
      const res = await postIngest(learnerId, [event]);
      setLastResult(`Ingested ${res.ids.length} event(s).`);
      setText("");
      onIngested(res.ids);
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="ingest-form">
      <summary>Ingest event</summary>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label>
          type
          <input
            list="event-types"
            value={type}
            onChange={(e) => setType(e.target.value)}
            placeholder="e.g. quiz_wrong"
            required
          />
          <datalist id="event-types">
            {COMMON_TYPES.map((t) => (
              <option key={t} value={t} />
            ))}
          </datalist>
        </label>
        <label>
          text
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            placeholder="Raw event text, e.g. 'Struggled with chain rule on quiz 3'"
          />
        </label>
        <div className="ingest-actions">
          <button type="submit" disabled={busy || !type.trim()}>
            {busy ? "Ingesting…" : `Ingest for ${learnerId}`}
          </button>
          {lastResult && <span className="muted small">{lastResult}</span>}
        </div>
      </form>
    </details>
  );
}
