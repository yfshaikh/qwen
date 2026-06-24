import type { ReactNode } from 'react'
import type { AuditRow, ConsolidateReport } from '../types'

function Bar({ tone, children }: { tone: 'muted' | 'error'; children: ReactNode }) {
  return (
    <div className={`px-4 py-3 text-sm ${tone === 'error' ? 'text-red-600' : 'text-zinc-400'}`}>
      {children}
    </div>
  )
}

export function KeeperTrace({
  report,
  rows,
  error,
}: {
  report: ConsolidateReport | null
  rows: AuditRow[]
  error?: string
}) {
  if (error) return <Bar tone="error">⚠️ {error}</Bar>
  if (!report)
    return (
      <Bar tone="muted">
        Run <span className="font-medium text-zinc-600">Consolidate</span> to watch the Keeper turn
        events into graph memory.
      </Bar>
    )
  if (report.skipped) return <Bar tone="muted">Nothing to consolidate — no pending events.</Bar>

  const stats: [string, string | number][] = [
    ['nodes', `+${report.nodes_created}`],
    ['edges', `+${report.edges_created}`],
    ['updated', report.nodes_updated],
    ['merged', report.merged],
    ['forgotten', report.forgotten],
    ['processed', report.processed_events],
  ]
  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5 px-4 pt-3">
        <span className="mr-1 text-xs font-semibold uppercase tracking-wide text-zinc-400">
          Keeper
        </span>
        {stats.map(([k, v]) => (
          <span
            key={k}
            className="inline-flex items-center gap-1 rounded-md bg-zinc-100 px-2 py-0.5 text-xs"
          >
            <span className="text-zinc-400">{k}</span>
            <span className="font-semibold tabular-nums text-zinc-700">{v}</span>
          </span>
        ))}
      </div>
      <ul className="scroll-thin max-h-36 space-y-1 overflow-auto px-4 py-2.5">
        {rows.map((r) => (
          <li key={r.id} className="flex items-start gap-2 text-xs">
            <span className="shrink-0 rounded bg-indigo-50 px-1.5 py-0.5 font-medium text-indigo-700">
              {r.op}
            </span>
            {r.rationale && <span className="text-zinc-500">{r.rationale}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}
