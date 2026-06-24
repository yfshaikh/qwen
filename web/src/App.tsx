import { useEffect, useState } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { GraphView } from './components/GraphView'
import { KeeperTrace } from './components/KeeperTrace'
import { NodeDetail } from './components/NodeDetail'
import { applyFrame, assistantTurn, userTurn, type PendingTurn } from './chat'
import * as api from './api'
import type { AuditRow, ChatMessage, ConsolidateReport, GraphNode, GraphResponse } from './types'

function newLearner(): string {
  return 'demo-' + crypto.randomUUID().slice(0, 8)
}

export default function App() {
  const [learner, setLearner] = useState(newLearner)
  const [turns, setTurns] = useState<PendingTurn[]>([])
  const [pending, setPending] = useState<PendingTurn | null>(null)
  const [graph, setGraph] = useState<GraphResponse>({ nodes: [], edges: [] })
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [report, setReport] = useState<ConsolidateReport | null>(null)
  const [audit, setAudit] = useState<AuditRow[]>([])
  const [flash, setFlash] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [banner, setBanner] = useState<string | null>(null)
  const [traceErr, setTraceErr] = useState<string | undefined>(undefined)

  useEffect(() => {
    api.health().then((ok) => setBanner(ok ? null : 'API unreachable — is the service running?'))
  }, [])

  async function send(text: string) {
    setBusy(true)
    const history: ChatMessage[] = [...turns, userTurn(text)].map((t) => ({ role: t.role, content: t.content }))
    setTurns((ts) => [...ts, userTurn(text)])
    let cur = assistantTurn()
    setPending(cur)
    try {
      for await (const frame of api.streamChat(learner, history)) {
        cur = applyFrame(cur, frame)
        setPending({ ...cur })
      }
    } catch (e) {
      cur = { ...cur, error: String(e), done: true }
    }
    setTurns((ts) => [...ts, cur])
    setPending(null)
    setBusy(false)
  }

  async function doConsolidate() {
    setBusy(true)
    setTraceErr(undefined)
    try {
      const before = new Set(graph.nodes.map((n) => n.id))
      const rep = await api.consolidate(learner)
      setReport(rep)
      const g = await api.getGraph(learner)
      setGraph(g)
      setAudit(await api.getAudit(learner))
      const fresh = new Set(g.nodes.filter((n) => !before.has(n.id)).map((n) => n.id))
      setFlash(fresh)
      setTimeout(() => setFlash(new Set()), 1600)
    } catch (e) {
      setTraceErr(String(e))
    }
    setBusy(false)
  }

  function reset() {
    setLearner(newLearner())
    setTurns([])
    setPending(null)
    setGraph({ nodes: [], edges: [] })
    setSelected(null)
    setReport(null)
    setAudit([])
    setFlash(new Set())
    setTraceErr(undefined)
  }

  return (
    <div className="flex h-screen flex-col bg-zinc-50 text-zinc-900">
      {banner && (
        <div className="border-b border-amber-100 bg-amber-50 px-4 py-2 text-center text-sm text-amber-800">
          {banner}
        </div>
      )}
      <header className="flex items-center gap-3 border-b border-zinc-200 bg-white px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="grid h-6 w-6 place-items-center rounded-md bg-indigo-600 text-xs font-bold text-white">
            E
          </span>
          <span className="text-sm font-semibold text-zinc-900">Engram Console</span>
        </div>
        <span className="ml-auto rounded-md bg-zinc-100 px-2 py-1 text-xs text-zinc-500">
          learner <span className="font-mono text-zinc-700">{learner}</span>
        </span>
        <button
          onClick={reset}
          className="rounded-lg border border-zinc-200 px-2.5 py-1 text-xs font-medium text-zinc-600 transition hover:bg-zinc-50"
        >
          New session
        </button>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[380px] shrink-0 flex-col border-r border-zinc-200 bg-white">
          <ChatPanel
            turns={turns}
            pending={pending}
            onSend={send}
            onConsolidate={doConsolidate}
            busy={busy}
          />
        </aside>
        <main className="relative min-w-0 flex-1 bg-zinc-50">
          <GraphView graph={graph} flashIds={flash} onSelect={setSelected} />
          <NodeDetail node={selected} onClose={() => setSelected(null)} />
        </main>
      </div>

      <footer className="border-t border-zinc-200 bg-white">
        <KeeperTrace report={report} rows={audit} error={traceErr} />
      </footer>
    </div>
  )
}
