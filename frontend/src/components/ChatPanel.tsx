import { useEffect, useRef, useState } from "react";
import { postTutorTurn } from "../api";

interface ChatMessage {
  role: "learner" | "tutor";
  text: string;
  /** recall.text_block — "what the tutor remembered" for this turn. */
  remembered?: string;
  eventsEmitted?: number;
}

interface Props {
  learnerId: string;
  /** Called after a successful turn so the app can refresh graph + audit. */
  onAfterTurn: () => void;
  onError: (message: string) => void;
}

export default function ChatPanel({ learnerId, onAfterTurn, onError }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const sessionIdRef = useRef(`web-${Date.now().toString(36)}`);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Reset the conversation when switching learners.
  useEffect(() => {
    setMessages([]);
    sessionIdRef.current = `web-${Date.now().toString(36)}`;
  }, [learnerId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, sending]);

  async function send() {
    const message = input.trim();
    if (!message || sending) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "learner", text: message }]);
    setSending(true);
    try {
      const res = await postTutorTurn(learnerId, message, sessionIdRef.current);
      setMessages((prev) => [
        ...prev,
        {
          role: "tutor",
          text: res.reply,
          remembered: res.recall?.text_block ?? "",
          eventsEmitted: res.events_emitted,
        },
      ]);
      onAfterTurn();
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="chat-panel">
      <h3 className="panel-title">Tutor chat</h3>
      <div className="chat-messages" ref={scrollRef}>
        {messages.length === 0 && (
          <p className="muted chat-hint">
            Talk to the tutor as <strong>{learnerId}</strong>. Each turn shows what the tutor
            remembered, and emits new learning events. (Tutor replies need an LLM key on the
            backend.)
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-msg chat-${m.role}`}>
            {m.role === "tutor" && m.remembered && (
              <details className="remembered">
                <summary>What the tutor remembered</summary>
                <pre>{m.remembered}</pre>
              </details>
            )}
            <div className="chat-bubble">{m.text}</div>
            {m.role === "tutor" && m.eventsEmitted != null && (
              <div className="muted small">{m.eventsEmitted} event(s) emitted</div>
            )}
          </div>
        ))}
        {sending && <div className="muted small">Tutor is thinking…</div>}
      </div>
      <form
        className="chat-input-row"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask the tutor…"
          disabled={sending}
        />
        <button type="submit" disabled={sending || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
