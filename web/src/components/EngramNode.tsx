import { Handle, Position, type NodeProps } from 'reactflow'

// Type accent language mirrors the rest of the console: concept=indigo,
// preference=emerald, goal=amber. Each type carries a dot/tint/border/glow so
// the glass card can lift and glow in its own colour when selected.
const TYPE_COLOR: Record<
  string,
  { dot: string; tint: string; border: string; glow: string }
> = {
  concept: {
    dot: '#6366f1',
    tint: 'rgba(99,102,241,0.10)',
    border: 'rgba(99,102,241,0.45)',
    glow: 'rgba(99,102,241,0.30)',
  },
  preference: {
    dot: '#10b981',
    tint: 'rgba(16,185,129,0.10)',
    border: 'rgba(16,185,129,0.45)',
    glow: 'rgba(16,185,129,0.30)',
  },
  goal: {
    dot: '#f59e0b',
    tint: 'rgba(245,158,11,0.10)',
    border: 'rgba(245,158,11,0.45)',
    glow: 'rgba(245,158,11,0.30)',
  },
}
const FALLBACK_COLOR = {
  dot: '#a1a1aa',
  tint: 'rgba(161,161,170,0.10)',
  border: 'rgba(161,161,170,0.45)',
  glow: 'rgba(161,161,170,0.30)',
}
const colorOf = (type: string) => TYPE_COLOR[type] ?? FALLBACK_COLOR

export interface EngramNodeData {
  label: string
  type: string
  mastery: number | null
}

export function EngramNode({ data, selected }: NodeProps<EngramNodeData>) {
  const color = colorOf(data.type)
  const pct = data.mastery == null ? null : Math.round(data.mastery * 100)

  return (
    <div
      style={{
        width: 176,
        borderRadius: 14,
        padding: '10px 12px',
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
        background: selected ? color.tint : 'rgba(255,255,255,0.85)',
        border: `1px solid ${selected ? color.border : '#e4e4e7'}`,
        boxShadow: selected
          ? `0 0 0 2px ${color.glow}, 0 6px 20px ${color.glow}`
          : '0 1px 4px rgba(24,24,27,0.08)',
        transform: selected ? 'scale(1.05)' : 'scale(1)',
        transition: 'transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease, border-color 0.15s ease',
        cursor: 'pointer',
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!h-1.5 !w-1.5 !border-0"
        style={{ background: color.dot }}
      />

      <div className="flex items-center gap-2">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color.dot }} />
        <span className="truncate text-sm font-medium text-zinc-800">{data.label}</span>
      </div>

      <div className="mt-2 flex items-center justify-between">
        <span
          className="rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide"
          style={{ background: color.tint, color: color.dot }}
        >
          {data.type}
        </span>
        <span className="text-[10px] tabular-nums text-zinc-400">
          {pct == null ? 'not studied' : `${pct}%`}
        </span>
      </div>

      <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-zinc-100">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct ?? 0}%`, background: color.dot, transition: 'width 0.3s ease' }}
        />
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-1.5 !w-1.5 !border-0"
        style={{ background: color.dot }}
      />
    </div>
  )
}
