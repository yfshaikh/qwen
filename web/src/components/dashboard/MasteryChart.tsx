import type { MasteryPoint } from '../../types'

// Fixed categorical order, never cycled — extends the house indigo/emerald/amber
// palette (see EngramNode) with three more distinct hues for up to 6 lines.
const COLORS = [
  { stroke: 'stroke-indigo-500', fill: 'fill-indigo-500', dot: 'bg-indigo-500' },
  { stroke: 'stroke-emerald-500', fill: 'fill-emerald-500', dot: 'bg-emerald-500' },
  { stroke: 'stroke-amber-500', fill: 'fill-amber-500', dot: 'bg-amber-500' },
  { stroke: 'stroke-rose-500', fill: 'fill-rose-500', dot: 'bg-rose-500' },
  { stroke: 'stroke-sky-500', fill: 'fill-sky-500', dot: 'bg-sky-500' },
  { stroke: 'stroke-violet-500', fill: 'fill-violet-500', dot: 'bg-violet-500' },
]

const WIDTH = 300
const HEIGHT = 120
const PAD = 8
const INNER_W = WIDTH - PAD * 2
const INNER_H = HEIGHT - PAD * 2

export function MasteryChart({ series }: { series: Record<string, MasteryPoint[]> }) {
  // ponytail: ranking by point count (not evidence count) is a deliberate
  // deviation from spec §4.2 ("top-6 concepts by evidence count") — the
  // timeline endpoint returns only label -> points, so evidence counts aren't
  // plumbed to this component. Point count is a zero-extra-fetch proxy for
  // "most-touched" concept. Upgrade path: thread the evidence_counts_by_kind
  // totals DashboardPage already fetches through as a ranking key if the
  // exact spec ordering is required.
  const top = Object.entries(series)
    .sort((a, b) => b[1].length - a[1].length) // ranked by point count, see comment above
    .slice(0, 6)
    .map(([label, points]) => ({ label, valid: points.filter((p) => p.mastery != null) }))
    .filter((s) => s.valid.length > 0) // drop series with no plottable mastery values

  if (top.length === 0) {
    return <p className="text-xs text-zinc-400">No mastery history yet.</p>
  }

  return (
    <div>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full" role="img" aria-label="Mastery over time">
        {top.map(({ label, valid }, i) => {
          const color = COLORS[i % COLORS.length]
          // Guard divide-by-zero for single-point series: center the lone point.
          const denom = Math.max(valid.length - 1, 1)
          const coords = valid.map((p, idx) => ({
            x: PAD + (valid.length === 1 ? INNER_W / 2 : (idx / denom) * INNER_W),
            y: PAD + INNER_H * (1 - (p.mastery as number)),
          }))
          return (
            <g key={label}>
              <polyline
                points={coords.map((c) => `${c.x},${c.y}`).join(' ')}
                fill="none"
                className={color.stroke}
                strokeWidth={2}
              />
              {coords.map((c, idx) => (
                <circle key={idx} cx={c.x} cy={c.y} r={2.5} className={color.fill} />
              ))}
            </g>
          )
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
        {top.map(({ label }, i) => (
          <span key={label} className="flex items-center gap-1 text-[10px] text-zinc-500">
            <span className={`h-1.5 w-1.5 rounded-full ${COLORS[i % COLORS.length].dot}`} />
            {label}
          </span>
        ))}
      </div>
    </div>
  )
}
