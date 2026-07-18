import ReactFlow, {
  Background,
  BackgroundVariant,
  Handle,
  Position,
  type Edge,
  type Node,
  type NodeProps,
} from 'reactflow'
import 'reactflow/dist/style.css'

interface StageData {
  icon: string
  title: string
  subtitle: string
  accent: string
  badge?: string
  handles: { type: 'source' | 'target'; position: Position; id: string }[]
}

function StageNode({ data }: NodeProps<StageData>) {
  return (
    <div className="w-48 rounded-xl border border-zinc-200 bg-white px-3 py-2.5 shadow-sm">
      {data.handles.map((h) => (
        <Handle
          key={h.type + h.id}
          type={h.type}
          position={h.position}
          id={h.id}
          className="!h-1.5 !w-1.5 !border-0 !bg-zinc-300"
        />
      ))}
      <div className="flex items-center gap-2">
        <span className={`grid h-6 w-6 place-items-center rounded-md text-sm text-white ${data.accent}`}>
          {data.icon}
        </span>
        <span className="text-sm font-semibold text-zinc-800">{data.title}</span>
        {data.badge && (
          <span className="ml-auto rounded bg-amber-50 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-700">
            {data.badge}
          </span>
        )}
      </div>
      <p className="mt-1.5 text-[11px] leading-snug text-zinc-500">{data.subtitle}</p>
    </div>
  )
}

const nodeTypes = { stage: StageNode }

const mk = (id: string, x: number, y: number, data: StageData): Node => ({
  id,
  type: 'stage',
  position: { x, y },
  data,
  draggable: false,
})

const NODES: Node[] = [
  mk('chat', 0, 30, {
    icon: '💬',
    title: 'You chat',
    subtitle: 'The tutor recalls memory and replies — the graph does not change yet.',
    accent: 'bg-indigo-500',
    handles: [
      { type: 'source', position: Position.Right, id: 'out' },
      { type: 'target', position: Position.Bottom, id: 'in' },
    ],
  }),
  mk('events', 320, 30, {
    icon: '📥',
    title: 'Raw events',
    subtitle: 'Each turn is logged to a pending queue. Cheap — no LLM on the hot path.',
    accent: 'bg-zinc-400',
    handles: [
      { type: 'target', position: Position.Left, id: 'in' },
      { type: 'source', position: Position.Right, id: 'out' },
    ],
  }),
  mk('keeper', 640, 30, {
    icon: '⚙️',
    title: 'Keeper',
    subtitle: 'Distills pending events into the graph: extract → link → merge → score.',
    accent: 'bg-amber-500',
    badge: 'offline',
    handles: [
      { type: 'target', position: Position.Left, id: 'in' },
      { type: 'source', position: Position.Bottom, id: 'out' },
    ],
  }),
  mk('graph', 640, 250, {
    icon: '🕸️',
    title: 'Knowledge graph',
    subtitle: 'Concepts, links, and mastery — the single source of truth.',
    accent: 'bg-emerald-500',
    handles: [
      { type: 'target', position: Position.Top, id: 'in' },
      { type: 'source', position: Position.Left, id: 'out' },
    ],
  }),
  mk('recall', 320, 250, {
    icon: '🧠',
    title: 'Recall',
    subtitle: 'A fast, token-budgeted read feeds memory into the next reply.',
    accent: 'bg-indigo-500',
    handles: [
      { type: 'target', position: Position.Right, id: 'in' },
      { type: 'source', position: Position.Left, id: 'out' },
    ],
  }),
]

const edge = (id: string, source: string, target: string, label: string): Edge => ({
  id,
  source,
  target,
  label,
  sourceHandle: 'out',
  targetHandle: 'in',
  type: 'smoothstep',
  animated: true,
  style: { stroke: '#cbd0d8', strokeWidth: 1.5 },
  labelStyle: { fill: '#71717a', fontSize: 11 },
  labelBgStyle: { fill: '#ffffff' },
  labelBgPadding: [4, 2] as [number, number],
})

const EDGES: Edge[] = [
  edge('e1', 'chat', 'events', 'append'),
  edge('e2', 'events', 'keeper', 'drain pending'),
  edge('e3', 'keeper', 'graph', 'extract · link · merge'),
  edge('e4', 'graph', 'recall', 'read subgraph'),
  edge('e5', 'recall', 'chat', 'memory → prompt'),
]

const STEPS = [
  {
    icon: '💬',
    title: 'Chatting is cheap',
    body: 'Every turn recalls memory and replies, then logs raw events to a queue. No heavy model work on the hot path.',
  },
  {
    icon: '⚙️',
    title: 'Memory forms offline',
    body: 'Hitting Consolidate runs the Keeper — it distills those events into concepts, links, and mastery. The expensive reasoning, amortized.',
  },
  {
    icon: '🧠',
    title: 'The graph is the memory',
    body: 'Recall reads a small, relevant slice of the graph into each reply, so the tutor remembers what you know.',
  },
]

export function Explainer({ onEnter }: { onEnter: () => void }) {
  return (
    <div className="h-screen overflow-auto bg-zinc-50">
      <header className="flex items-center gap-2 border-b border-zinc-200 bg-white px-4 py-2.5">
        <span className="grid h-6 w-6 place-items-center rounded-md bg-indigo-600 text-xs font-bold text-white">
          E
        </span>
        <span className="text-sm font-semibold text-zinc-900">Engram</span>
      </header>

      <main className="mx-auto w-full max-w-5xl px-6 py-12">
        <h1 className="text-2xl font-bold tracking-tight text-zinc-900">How Engram works</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-zinc-500">
          Engram is an app-agnostic memory core. It turns a stream of learning events into a living
          knowledge graph — <span className="font-medium text-zinc-700">built offline, read fast</span>.
          Two agents share one graph: a cheap live turn, and an expensive offline Keeper.
        </p>

        <div className="mt-8 h-[340px] overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-sm">
          <ReactFlow
            nodes={NODES}
            edges={EDGES}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.18 }}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            panOnDrag={false}
            zoomOnScroll={false}
            zoomOnPinch={false}
            zoomOnDoubleClick={false}
            preventScrolling={false}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#eef0f2" />
          </ReactFlow>
        </div>
        <p className="mt-3 text-center text-xs text-zinc-400">
          The graph changes <span className="font-medium text-zinc-500">only</span> during Consolidate
          (the offline Keeper). Chatting just logs raw events.
        </p>

        <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-3">
          {STEPS.map((s) => (
            <div key={s.title} className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm">
              <div className="text-xl">{s.icon}</div>
              <h3 className="mt-2 text-sm font-semibold text-zinc-800">{s.title}</h3>
              <p className="mt-1 text-xs leading-relaxed text-zinc-500">{s.body}</p>
            </div>
          ))}
        </div>

        <div className="mt-10 flex justify-center">
          <button
            onClick={onEnter}
            className="rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700"
          >
            Enter the console →
          </button>
        </div>
      </main>
    </div>
  )
}
