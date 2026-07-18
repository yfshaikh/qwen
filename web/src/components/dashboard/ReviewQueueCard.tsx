import type { ReviewItem } from '../../types'

// ponytail: onAsk wiring into the transcript panel (suggested opening line) is
// out of scope for this task — callers may pass a no-op/console.log stub.
export function ReviewQueueCard({
  items,
  onAsk,
}: {
  items: ReviewItem[]
  onAsk: (item: ReviewItem) => void
}) {
  if (items.length === 0) {
    return <p className="text-xs text-zinc-400">Nothing due for review.</p>
  }

  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li
          key={item.node_id}
          className="flex items-center justify-between gap-3 rounded-lg border border-zinc-100 px-3 py-2"
        >
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-zinc-700">{item.label}</p>
            <p className="truncate text-[11px] text-zinc-400">{item.reason}</p>
          </div>
          <button
            onClick={() => onAsk(item)}
            className="shrink-0 rounded-md border border-zinc-200 px-2 py-1 text-[11px] font-medium text-zinc-600 transition hover:bg-zinc-50"
          >
            Ask the tutor about this
          </button>
        </li>
      ))}
    </ul>
  )
}
