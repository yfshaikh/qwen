import { useState } from 'react'
import type { PendingTurn } from '../chat'

export function ChatPanel({
  turns,
  pending,
  onSend,
  onConsolidate,
  busy,
}: {
  turns: PendingTurn[]
  pending: PendingTurn | null
  onSend: (text: string) => void
  onConsolidate: () => void
  busy: boolean
}) {
  const [text, setText] = useState('')
  const all = pending ? [...turns, pending] : turns
  return (
    <div className="chat">
      <div className="messages">
        {all.map((t, i) => (
          <div key={i} className={`turn ${t.role}`}>
            {t.role === 'assistant' && t.recalled !== undefined && (
              <div className="annot recalled">🧠 recalled: {t.recalled || '(none yet)'}</div>
            )}
            <div className="bubble">{t.content}</div>
            {t.error && <div className="annot error">⚠️ {t.error}</div>}
            {t.saved && t.saved.length > 0 && (
              <div className="annot saved">💾 saved: {t.saved.map((e) => e.type).join(', ')}</div>
            )}
          </div>
        ))}
      </div>
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault()
          const v = text.trim()
          if (v && !busy) {
            onSend(v)
            setText('')
          }
        }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask the tutor…"
          disabled={busy}
        />
        <button type="submit" disabled={busy || !text.trim()}>
          Send
        </button>
        <button type="button" onClick={onConsolidate} disabled={busy}>
          Consolidate
        </button>
      </form>
    </div>
  )
}
