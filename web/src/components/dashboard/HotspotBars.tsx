import type { Hotspot } from '../../types'

// Horizontal Tailwind-div bars, reusing the EngramNode percentage-width bar idiom.
export function HotspotBars({ hotspots }: { hotspots: Hotspot[] }) {
  if (hotspots.length === 0) {
    return <p className="text-xs text-zinc-400">No struggle hotspots.</p>
  }

  const maxStruggle = Math.max(0, ...hotspots.map((h) => h.struggle)) // guard: all-zero

  return (
    <ul className="space-y-2">
      {hotspots.map((h) => {
        const pct = maxStruggle > 0 ? Math.round((h.struggle / maxStruggle) * 100) : 0
        const masteryLabel = h.mastery != null ? `${Math.round(h.mastery * 100)}%` : '—'
        return (
          <li key={h.node_id} className="text-xs">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="truncate font-medium text-zinc-700">{h.label}</span>
              <span className="flex shrink-0 items-center gap-1.5 tabular-nums text-zinc-400">
                <span className={h.trend === 'improving' ? 'text-emerald-600' : 'text-zinc-400'}>
                  {h.trend === 'improving' ? '↑' : '→'}
                </span>
                {masteryLabel}
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-100">
              <div className="h-full rounded-full bg-rose-400" style={{ width: `${pct}%` }} />
            </div>
          </li>
        )
      })}
    </ul>
  )
}
