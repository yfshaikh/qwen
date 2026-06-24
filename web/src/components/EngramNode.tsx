import { Handle, Position, type NodeProps } from 'reactflow'

const TYPE_STYLE: Record<string, { dot: string; chip: string }> = {
  concept: { dot: 'bg-indigo-500', chip: 'bg-indigo-50 text-indigo-700' },
  preference: { dot: 'bg-emerald-500', chip: 'bg-emerald-50 text-emerald-700' },
  goal: { dot: 'bg-amber-500', chip: 'bg-amber-50 text-amber-700' },
}

export interface EngramNodeData {
  label: string
  type: string
  mastery: number | null
}

export function EngramNode({ data, selected }: NodeProps<EngramNodeData>) {
  const style = TYPE_STYLE[data.type] ?? { dot: 'bg-zinc-400', chip: 'bg-zinc-100 text-zinc-600' }
  const pct = Math.round((data.mastery ?? 0) * 100)
  return (
    <div
      className={`w-44 rounded-xl border bg-white px-3 py-2.5 shadow-sm transition-shadow hover:shadow-md ${
        selected ? 'border-indigo-400 ring-2 ring-indigo-100' : 'border-zinc-200'
      }`}
    >
      <Handle type="target" position={Position.Top} className="!h-1.5 !w-1.5 !border-0 !bg-zinc-300" />
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 shrink-0 rounded-full ${style.dot}`} />
        <span className="truncate text-sm font-medium text-zinc-800">{data.label}</span>
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${style.chip}`}>{data.type}</span>
        {data.mastery != null && <span className="text-[10px] tabular-nums text-zinc-400">{pct}%</span>}
      </div>
      <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-zinc-100">
        <div className={`h-full rounded-full ${style.dot}`} style={{ width: `${pct}%` }} />
      </div>
      <Handle type="source" position={Position.Bottom} className="!h-1.5 !w-1.5 !border-0 !bg-zinc-300" />
    </div>
  )
}
