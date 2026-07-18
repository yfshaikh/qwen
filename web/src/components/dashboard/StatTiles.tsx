import type { InsightsSummary } from '../../types'

function pct(v: number | null): string {
  return v == null ? '—' : `${Math.round(v * 100)}%`
}

export function StatTiles({ summary }: { summary: InsightsSummary }) {
  const tiles = [
    { label: 'Concepts', value: String(summary.concepts) },
    { label: 'Avg mastery', value: pct(summary.avg_mastery) },
    { label: 'Evidence', value: String(summary.evidence) },
    { label: 'Sessions', value: String(summary.sessions) },
    { label: 'Fading', value: String(summary.fading) },
    { label: 'Open misconceptions', value: String(summary.open_misconceptions) },
  ]

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-lg border border-zinc-200 bg-white px-3 py-2">
          <p className="text-lg font-semibold tabular-nums text-zinc-900">{t.value}</p>
          <p className="text-[11px] text-zinc-500">{t.label}</p>
        </div>
      ))}
    </div>
  )
}
