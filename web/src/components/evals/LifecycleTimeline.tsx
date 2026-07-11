import type { EvalSnapshot } from '../../types'

// Pure presentational: one row per consolidation snapshot, with the memory
// lifecycle counts (created / merged / forgotten / processed) as small chips.
// Green marks growth (created), amber marks loss (forgotten) — the two signals
// you scan a run's history for.
function Chip({ label, tone }: { label: string; tone: 'green' | 'amber' | 'zinc' }) {
  const cls =
    tone === 'green'
      ? 'bg-emerald-100 text-emerald-700'
      : tone === 'amber'
        ? 'bg-amber-100 text-amber-700'
        : 'bg-zinc-100 text-zinc-600'
  return <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>{label}</span>
}

export function LifecycleTimeline({ snapshots }: { snapshots: EvalSnapshot[] }) {
  if (snapshots.length === 0) return null
  return (
    <ol className="space-y-1">
      {snapshots.map((s) => {
        const r = s.report
        return (
          <li key={s.session} className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
            <span className="w-20 font-mono text-zinc-600">session {s.session}</span>
            <Chip label={`${r.nodes_created ?? 0} created`} tone="green" />
            <Chip label={`${r.merged ?? 0} merged`} tone="zinc" />
            <Chip label={`${r.forgotten ?? 0} forgotten`} tone="amber" />
            <Chip label={`${r.processed_events ?? 0} processed`} tone="zinc" />
          </li>
        )
      })}
    </ol>
  )
}
