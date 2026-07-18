import { useEffect, useState } from 'react'
import * as api from '../api'
import type { VoiceSession, VoiceTurn } from '../types'

export function SessionSidebar({ learner, refreshKey }: { learner: string; refreshKey: number }) {
  const [sessions, setSessions] = useState<VoiceSession[]>([])
  const [openId, setOpenId] = useState<string | null>(null)
  const [turns, setTurns] = useState<VoiceTurn[]>([])

  useEffect(() => {
    api.getSessions(learner).then(setSessions).catch(() => setSessions([]))
  }, [learner, refreshKey])

  async function toggle(id: string) {
    if (openId === id) { setOpenId(null); return }
    setOpenId(id)
    try { setTurns(await api.getSessionTurns(id)) } catch { setTurns([]) }
  }

  return (
    <aside className="flex w-72 shrink-0 flex-col overflow-y-auto border-l border-zinc-200 bg-white">
      <div className="border-b border-zinc-200 px-3 py-2 text-xs font-semibold text-zinc-500">
        Sessions
      </div>
      {sessions.length === 0 && (
        <div className="px-3 py-4 text-xs text-zinc-400">No voice sessions yet.</div>
      )}
      {sessions.map((s) => (
        <div key={s.id} className="border-b border-zinc-100">
          <button
            onClick={() => toggle(s.id)}
            className="flex w-full items-center justify-between px-3 py-2 text-left text-xs hover:bg-zinc-50"
          >
            <span className="text-zinc-700">
              {s.started_at ? new Date(s.started_at).toLocaleString() : s.id.slice(0, 8)}
            </span>
            <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-zinc-500">{s.turns}</span>
          </button>
          {openId === s.id && (
            <div className="space-y-1 px-3 pb-2">
              {turns.map((t) => (
                <div key={t.id} className="text-xs">
                  <span className={t.role === 'user' ? 'font-medium text-indigo-600' : 'text-zinc-500'}>
                    {t.role}:
                  </span>{' '}
                  <span className="text-zinc-700">{t.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </aside>
  )
}
