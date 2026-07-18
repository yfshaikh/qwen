import type { ActivityDay } from '../../types'

const WIDTH = 300
const HEIGHT = 40
const GAP = 1

export function ActivityStrip({ days }: { days: ActivityDay[] }) {
  if (days.length === 0) {
    return <p className="text-xs text-zinc-400">No activity.</p>
  }

  const maxCount = Math.max(0, ...days.map((d) => d.count)) // guard: all-zero days
  const colW = WIDTH / days.length

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full" role="img" aria-label="Daily activity, last 30 days">
      {days.map((d, i) => {
        // Floor of 2px keeps every column hoverable (title tooltip) even at count 0.
        const h = Math.max(maxCount > 0 ? (d.count / maxCount) * HEIGHT : 0, 2)
        const x = i * colW
        return (
          <rect
            key={d.day}
            x={x + GAP / 2}
            y={HEIGHT - h}
            width={Math.max(colW - GAP, 1)}
            height={h}
            rx={1}
            className={d.count > 0 ? 'fill-indigo-400' : 'fill-zinc-100'}
          >
            <title>{`${d.day}: ${d.count}`}</title>
          </rect>
        )
      })}
    </svg>
  )
}
