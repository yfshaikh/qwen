import { useEffect, useState } from 'react'
import { ChatPanel, type DemoBanner } from './components/ChatPanel'
import { Explainer } from './components/Explainer'
import { GraphView } from './components/GraphView'
import { KeeperTrace } from './components/KeeperTrace'
import { NodeDetail } from './components/NodeDetail'
import { applyFrame, assistantTurn, userTurn, type PendingTurn } from './chat'
import * as api from './api'
import type { AuditRow, ChatMessage, ConsolidateReport, GraphNode, GraphResponse } from './types'
import { DEMO_PATH } from './examples'
import { buildSessionExport, downloadJson } from './exportSession'

function newLearner(): string {
  return 'demo-' + crypto.randomUUID().slice(0, 8)
}

export default function App() {
  const [view, setView] = useState<'explainer' | 'console'>('explainer')
  const [learner, setLearner] = useState(() => localStorage.getItem('engram.learner') || newLearner())
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
  const [demo, setDemo] = useState<number | null>(null)
  const [prefill, setPrefill] = useState('')
  const [prefillKey, setPrefillKey] = useState(0)

  // Persist the learner id so a reload resumes the same session.
  useEffect(() => {
    localStorage.setItem('engram.learner', learner)
  }, [learner])

  useEffect(() => {
    api.health().then((ok) => setBanner(ok ? null : 'API unreachable — is the service running?'))
    loadInto(learner) // restore the persisted session's history + graph
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    if (demo !== null && DEMO_PATH[demo].kind === 'say') advanceDemo(demo)
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
    if (demo !== null && DEMO_PATH[demo].kind === 'consolidate') advanceDemo(demo)
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
    setDemo(null)
    pushPrefill('')
  }

  function pushPrefill(value: string) {
    setPrefill(value)
    setPrefillKey((k) => k + 1)
  }
  function startDemo() {
    setDemo(0)
    const s = DEMO_PATH[0]
    pushPrefill(s.kind === 'say' ? s.text : '')
  }
  function exitDemo() {
    setDemo(null)
    pushPrefill('')
  }
  function advanceDemo(from: number) {
    const next = from + 1
    if (next >= DEMO_PATH.length) {
      setDemo(null)
      return
    }
    setDemo(next)
    const s = DEMO_PATH[next]
    pushPrefill(s.kind === 'say' ? s.text : '')
  }

  async function loadInto(id: string, switchView = false) {
    if (switchView) setView('console')
    try {
      const msgs = await api.getHistory(id)
      setTurns(msgs.map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content })))
      setGraph(await api.getGraph(id))
      setAudit(await api.getAudit(id))
    } catch {
      // offline or empty session — leave current state as-is
    }
  }
  function resume(id: string) {
    const trimmed = id.trim()
    if (!trimmed) return
    setLearner(trimmed)
    setPending(null)
    setSelected(null)
    setReport(null)
    setFlash(new Set())
    setTraceErr(undefined)
    setDemo(null)
    pushPrefill('')
    loadInto(trimmed, true)
  }
  function exportSession() {
    const data = buildSessionExport({
      learner,
      turns: pending ? [...turns, pending] : turns,
      report,
      audit,
      graph,
    })
    downloadJson(`engram-${learner}.json`, data)
  }

  if (view === 'explainer') {
    return <Explainer onEnter={() => setView('console')} />
  }

  let demoProp: DemoBanner | null = null
  if (demo !== null) {
    const s = DEMO_PATH[demo]
    demoProp = {
      step: demo + 1,
      total: DEMO_PATH.length,
      kind: s.kind,
      note: s.kind === 'consolidate' ? s.note : undefined,
      onExit: exitDemo,
    }
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
          onClick={exportSession}
          disabled={turns.length === 0 && !report}
          className="rounded-lg border border-zinc-200 px-2.5 py-1 text-xs font-medium text-zinc-600 transition hover:bg-zinc-50 disabled:opacity-40"
        >
          Export
        </button>
        <button
          onClick={() => setView('explainer')}
          className="rounded-lg border border-zinc-200 px-2.5 py-1 text-xs font-medium text-zinc-600 transition hover:bg-zinc-50"
        >
          How it works
        </button>
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
            prefill={prefill}
            prefillKey={prefillKey}
            onStartDemo={startDemo}
            onResume={resume}
            demo={demoProp}
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
