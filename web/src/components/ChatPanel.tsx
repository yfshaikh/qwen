import { useEffect, useState } from 'react'
import type { PendingTurn } from '../chat'
import { EXAMPLE_FLOWS } from '../examples'

export interface DemoBanner {
  step: number
  total: number
  kind: 'say' | 'consolidate'
  note?: string
  onExit: () => void
}

function DemoHero({ onStart }: { onStart: () => void }) {
  return (
    <div className="rounded-xl border border-indigo-200 bg-indigo-50/60 p-4">
      <div className="flex items-start gap-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-indigo-600 text-sm text-white">
          ▶
        </span>
        <div>
          <h2 className="text-sm font-semibold text-zinc-800">Guided demo</h2>
          <p className="mt-0.5 text-xs leading-relaxed text-zinc-500">
            A full tutoring session in a handful of messages. We prefill each one — just hit{' '}
            <span className="font-medium text-zinc-600">Send</span>, and{' '}
            <span className="font-medium text-zinc-600">Consolidate</span> when prompted, to watch the
            graph form.
          </p>
        </div>
      </div>
      <button
        onClick={onStart}
        className="mt-3 w-full rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700"
      >
        Start guided demo
      </button>
    </div>
  )
}

function Examples({ onPick, busy }: { onPick: (p: string) => void; busy: boolean }) {
  return (
    <div>
      <div className="mb-3">
        <h2 className="text-sm font-semibold text-zinc-700">Or try a single prompt</h2>
        <p className="text-xs text-zinc-400">Click a prompt to send it, then Consolidate.</p>
      </div>
      <div className="space-y-3">
        {EXAMPLE_FLOWS.map((f) => (
          <div key={f.id} className="rounded-xl border border-zinc-200 bg-white p-3 shadow-sm">
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${f.accent}`} />
              <span className="text-sm font-medium text-zinc-800">{f.title}</span>
            </div>
            <p className="mt-0.5 text-xs text-zinc-400">{f.blurb}</p>
            <div className="mt-2 space-y-1.5">
              {f.prompts.map((p, i) => (
                <button
                  key={i}
                  disabled={busy}
                  onClick={() => onPick(p)}
                  className="block w-full rounded-lg bg-zinc-50 px-2.5 py-1.5 text-left text-xs text-zinc-600 transition hover:bg-indigo-50 hover:text-indigo-700 disabled:opacity-40"
                >
                  <span className="mr-1.5 text-zinc-300">{i + 1}</span>
                  {p}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function TurnView({ t }: { t: PendingTurn }) {
  if (t.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-indigo-600 px-3.5 py-2 text-sm text-white">
          {t.content}
        </div>
      </div>
    )
  }
  return (
    <div className="space-y-1.5">
      {t.recalled !== undefined && (
        <div className="text-[11px] text-zinc-400">🧠 recalled: {t.recalled || '(none yet)'}</div>
      )}
      <div className="max-w-[90%] whitespace-pre-wrap rounded-2xl rounded-bl-sm border border-zinc-200 bg-white px-3.5 py-2 text-sm leading-relaxed text-zinc-800 shadow-sm">
        {t.content || <span className="text-zinc-300">…</span>}
      </div>
      {t.error && <div className="text-xs text-red-600">⚠️ {t.error}</div>}
      {t.saved && t.saved.length > 0 && (
        <div className="text-[11px] text-zinc-400">💾 saved: {t.saved.map((e) => e.type).join(', ')}</div>
      )}
    </div>
  )
}

function ResumeRow({ onResume }: { onResume: (id: string) => void }) {
  const [id, setId] = useState('')
  return (
    <form
      className="rounded-xl border border-zinc-200 bg-white p-3 shadow-sm"
      onSubmit={(e) => {
        e.preventDefault()
        if (id.trim()) onResume(id.trim())
      }}
    >
      <h2 className="text-sm font-semibold text-zinc-700">Resume a session</h2>
      <p className="mb-2 text-xs text-zinc-400">Paste a learner id to reload its chat and graph.</p>
      <div className="flex gap-2">
        <input
          value={id}
          onChange={(e) => setId(e.target.value)}
          placeholder="demo-…"
          className="flex-1 rounded-lg border border-zinc-200 px-2.5 py-1.5 text-xs outline-none focus:border-indigo-300"
        />
        <button
          type="submit"
          disabled={!id.trim()}
          className="rounded-lg bg-zinc-800 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-zinc-900 disabled:opacity-40"
        >
          Resume
        </button>
      </div>
    </form>
  )
}

export function ChatPanel({
  turns,
  pending,
  onSend,
  onConsolidate,
  busy,
  prefill,
  prefillKey,
  onStartDemo,
  onResume,
  demo,
}: {
  turns: PendingTurn[]
  pending: PendingTurn | null
  onSend: (text: string) => void
  onConsolidate: () => void
  busy: boolean
  prefill?: string
  prefillKey?: number
  onStartDemo?: () => void
  onResume?: (id: string) => void
  demo?: DemoBanner | null
}) {
  const [text, setText] = useState('')

  // The guided demo prefills the composer by bumping prefillKey.
  useEffect(() => {
    if (prefillKey !== undefined) setText(prefill ?? '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillKey])

  const all = pending ? [...turns, pending] : turns
  const wantConsolidate = demo?.kind === 'consolidate'

  return (
    <div className="flex h-full flex-col">
      <div className="scroll-thin flex-1 overflow-auto px-4 py-4">
        {all.length === 0 ? (
          <div className="space-y-5">
            {onStartDemo && !demo && <DemoHero onStart={onStartDemo} />}
            {onResume && <ResumeRow onResume={onResume} />}
            <Examples onPick={(p) => !busy && onSend(p)} busy={busy} />
          </div>
        ) : (
          <div className="space-y-5">
            {all.map((t, i) => (
              <TurnView key={i} t={t} />
            ))}
          </div>
        )}
      </div>

      {demo && (
        <div className="flex items-center gap-2 border-t border-indigo-100 bg-indigo-50/70 px-3 py-2 text-xs">
          <span className="shrink-0 font-semibold text-indigo-700">Guided demo</span>
          <span className="shrink-0 text-zinc-400">
            step {demo.step}/{demo.total}
          </span>
          <span className="truncate text-zinc-500">
            {demo.kind === 'consolidate' ? demo.note : 'Prefilled — press Send to continue.'}
          </span>
          <button
            onClick={demo.onExit}
            className="ml-auto shrink-0 text-zinc-400 transition hover:text-zinc-600"
          >
            Exit
          </button>
        </div>
      )}

      <form
        className="border-t border-zinc-200 p-3"
        onSubmit={(e) => {
          e.preventDefault()
          const v = text.trim()
          if (v && !busy) {
            onSend(v)
            setText('')
          }
        }}
      >
        <div className="flex items-center gap-2 rounded-xl border border-zinc-200 bg-white p-1.5 shadow-sm focus-within:border-indigo-300 focus-within:ring-2 focus-within:ring-indigo-100">
          <input
            className="flex-1 bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-zinc-400"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Ask the tutor…"
            disabled={busy}
          />
          <button
            type="submit"
            disabled={busy || !text.trim()}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm transition hover:bg-indigo-700 disabled:opacity-40"
          >
            Send
          </button>
        </div>
        <button
          type="button"
          onClick={onConsolidate}
          disabled={busy}
          className={`mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition disabled:opacity-40 ${
            wantConsolidate
              ? 'animate-pulse border-amber-300 bg-amber-50 text-amber-700'
              : 'border-zinc-200 bg-white text-zinc-700 hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700'
          }`}
        >
          ⚡ Consolidate memory
        </button>
      </form>
    </div>
  )
}
