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
      setTimeout(() => setFlash(new Set()), 1500)
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
    <div className="app">
      {banner && <div className="banner">{banner}</div>}
      <header className="topbar">
        <strong>Engram Console</strong>
        <span>
          learner: <code>{learner}</code>
        </span>
        <button onClick={reset}>New session</button>
      </header>
      <main className="panes">
        <section className="left">
          <ChatPanel turns={turns} pending={pending} onSend={send} onConsolidate={doConsolidate} busy={busy} />
        </section>
        <section className="right">
          <GraphView graph={graph} flashIds={flash} onSelect={setSelected} />
          <NodeDetail node={selected} onClose={() => setSelected(null)} />
        </section>
      </main>
      <footer className="drawer">
        <KeeperTrace report={report} rows={audit} error={traceErr} />
      </footer>
    </div>
  )
}
