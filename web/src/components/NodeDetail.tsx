import type { GraphNode } from '../types'

const TYPE_CHIP: Record<string, string> = {
  concept: 'bg-indigo-50 text-indigo-700',
  preference: 'bg-emerald-50 text-emerald-700',
  goal: 'bg-amber-50 text-amber-700',
}

function fmt(v: number | null): string {
  return v == null ? '—' : v.toFixed(2)
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-100 bg-zinc-50 px-2 py-1.5 text-center">
      <div className="text-sm font-semibold tabular-nums text-zinc-800">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-zinc-400">{label}</div>
    </div>
  )
}

export function NodeDetail({ node, onClose }: { node: GraphNode | null; onClose: () => void }) {
  if (!node) return null
  const chip = TYPE_CHIP[node.type] ?? 'bg-zinc-100 text-zinc-600'
  return (
    <aside className="absolute bottom-4 right-4 top-4 z-10 flex w-80 flex-col rounded-2xl border border-zinc-200 bg-white/95 shadow-xl backdrop-blur">
      <div className="flex items-start justify-between gap-3 border-b border-zinc-100 p-4">
        <div>
          <h3 className="text-base font-semibold text-zinc-900">{node.label}</h3>
          <span className={`mt-1 inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ${chip}`}>
            {node.type}
          </span>
        </div>
        <button
          onClick={onClose}
          aria-label="close"
          className="rounded-md p-1 text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-600"
        >
          ✕
        </button>
      </div>
      <div className="scroll-thin flex-1 overflow-auto p-4">
        {node.summary && <p className="mb-4 text-sm leading-relaxed text-zinc-600">{node.summary}</p>}
        <div className="mb-5 grid grid-cols-3 gap-2">
          <Metric label="mastery" value={fmt(node.mastery)} />
          <Metric label="confidence" value={fmt(node.confidence)} />
          <Metric label="salience" value={fmt(node.salience)} />
        </div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">Evidence</h4>
        {node.evidence.length === 0 ? (
          <p className="text-sm text-zinc-400">none yet</p>
        ) : (
          <ul className="space-y-1.5">
            {node.evidence.map((e, i) => (
              <li key={i} className="rounded-lg bg-zinc-50 px-2.5 py-1.5 text-sm">
                <span className="font-medium text-zinc-700">{e.kind}</span>
                {e.content ? <span className="text-zinc-500">: {e.content}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  )
}
