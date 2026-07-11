import { useEffect, useState } from 'react'
import { Explainer } from './components/Explainer'
import { GraphView } from './components/GraphView'
import { KeeperTrace } from './components/KeeperTrace'
import { NodeDetail } from './components/NodeDetail'
import { SessionSidebar } from './components/SessionSidebar'
import { VoiceMicPill } from './components/VoiceMicPill'
import { VoiceTranscriptPanel } from './components/VoiceTranscriptPanel'
import { EvalsPage } from './components/evals/EvalsPage'
import { useVoiceTutor } from './voice/useVoiceTutor'
import * as api from './api'
import type { AuditRow, ConsolidateReport, EvalScenario, GraphNode, GraphResponse } from './types'
import { buildSessionExport, downloadJson } from './exportSession'

function newLearner(): string {
  return 'demo-' + crypto.randomUUID().slice(0, 8)
}

export default function App() {
  const [view, setView] = useState<'explainer' | 'console' | 'evals'>('explainer')
  const [evalScenarios, setEvalScenarios] = useState<EvalScenario[] | null>(null)
  const [learner, setLearner] = useState(() => localStorage.getItem('engram.learner') || newLearner())
  const [graph, setGraph] = useState<GraphResponse>({ nodes: [], edges: [] })
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [report, setReport] = useState<ConsolidateReport | null>(null)
  const [audit, setAudit] = useState<AuditRow[]>([])
  const [flash, setFlash] = useState<Set<string>>(new Set())
  const [consolidating, setConsolidating] = useState(false)
  const [banner, setBanner] = useState<string | null>(null)
  const [traceErr, setTraceErr] = useState<string | undefined>(undefined)
  const [refreshKey, setRefreshKey] = useState(0)

  const voice = useVoiceTutor(learner)

  // Persist the learner id so a reload resumes the same session.
  useEffect(() => {
    localStorage.setItem('engram.learner', learner)
  }, [learner])

  useEffect(() => {
    api.health().then((ok) => setBanner(ok ? null : 'API unreachable — is the service running?'))
    loadInto(learner) // restore the persisted session's graph + audit trail
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Probe the eval endpoints once on mount; only expose the Evals view if the
  // feature is present (404/error → feature off, swallow the error).
  useEffect(() => {
    api
      .getEvalScenarios()
      .then((s) => setEvalScenarios(s))
      .catch(() => setEvalScenarios(null))
  }, [])

  const evalsAvailable = evalScenarios !== null

  async function doConsolidate() {
    setConsolidating(true)
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
      setRefreshKey((k) => k + 1)
    } catch (e) {
      setTraceErr(String(e))
    }
    setConsolidating(false)
  }

  // Poll Keeper consolidation status; on true→false transition, refresh graph + audit.
  useEffect(() => {
    let prev = false
    const id = setInterval(async () => {
      const now = await api.getMemoryStatus(learner)
      setConsolidating(now)
      if (prev && !now) {            // finished → refresh graph + sessions
        const before = new Set(graph.nodes.map((n) => n.id))
        const g = await api.getGraph(learner)
        setGraph(g)
        setAudit(await api.getAudit(learner))
        setFlash(new Set(g.nodes.filter((n) => !before.has(n.id)).map((n) => n.id)))
        setTimeout(() => setFlash(new Set()), 1600)
        setRefreshKey((k) => k + 1)  // Task 9 sidebar refresh
      }
      prev = now
    }, 3000)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [learner, graph.nodes])

  function reset() {
    setLearner(newLearner())
    setGraph({ nodes: [], edges: [] })
    setSelected(null)
    setReport(null)
    setAudit([])
    setFlash(new Set())
    setTraceErr(undefined)
  }

  async function loadInto(id: string, switchView = false) {
    if (switchView) setView('console')
    try {
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
    setSelected(null)
    setReport(null)
    setFlash(new Set())
    setTraceErr(undefined)
    loadInto(trimmed, true)
  }
  function exportSession() {
    const data = buildSessionExport({
      learner,
      turns: voice.messages.map((m) => ({ role: m.role, content: m.text })),
      report,
      audit,
      graph,
    })
    downloadJson(`engram-${learner}.json`, data)
  }

  if (view === 'explainer') {
    return <Explainer onEnter={() => setView('console')} />
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
        {consolidating && (
          <span className="ml-auto rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs font-medium text-amber-800">
            Updating memory…
          </span>
        )}
        <span className={`${consolidating ? '' : 'ml-auto '}rounded-md bg-zinc-100 px-2 py-1 text-xs text-zinc-500`}>
          learner <span className="font-mono text-zinc-700">{learner}</span>
        </span>
        <button
          onClick={doConsolidate}
          disabled={consolidating}
          className="rounded-lg border border-zinc-200 px-2.5 py-1 text-xs font-medium text-zinc-600 transition hover:bg-zinc-50 disabled:opacity-40"
        >
          {consolidating ? 'Consolidating…' : 'Consolidate'}
        </button>
        <button
          onClick={exportSession}
          disabled={voice.messages.length === 0 && !report}
          className="rounded-lg border border-zinc-200 px-2.5 py-1 text-xs font-medium text-zinc-600 transition hover:bg-zinc-50 disabled:opacity-40"
        >
          Export
        </button>
        {evalsAvailable && (
          <button
            onClick={() => setView(view === 'evals' ? 'console' : 'evals')}
            className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition ${
              view === 'evals'
                ? 'border-indigo-200 bg-indigo-50 text-indigo-700'
                : 'border-zinc-200 text-zinc-600 hover:bg-zinc-50'
            }`}
          >
            Evals
          </button>
        )}
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

      {view === 'evals' ? (
        <EvalsPage scenarios={evalScenarios ?? []} />
      ) : (
        <>
      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[380px] shrink-0 flex-col border-r border-zinc-200 bg-white">
          <VoiceTranscriptPanel
            phase={voice.phase}
            connected={voice.connected}
            messages={voice.messages}
            errorMsg={voice.errorMsg}
            speed={voice.speed}
            onChangeSpeed={voice.setSpeed}
            onDismissError={voice.clearError}
          />
        </aside>
        <main className="relative min-w-0 flex-1 bg-zinc-50">
          <GraphView graph={graph} flashIds={flash} onSelect={setSelected} />
          <NodeDetail node={selected} onClose={() => setSelected(null)} />
          <VoiceMicPill
            phase={voice.phase}
            connected={voice.connected}
            isHolding={voice.isHolding}
            onHoldStart={voice.startHold}
            onHoldEnd={voice.endHold}
          />
        </main>
        <SessionSidebar learner={learner} refreshKey={refreshKey} />
      </div>

      <footer className="border-t border-zinc-200 bg-white">
        <KeeperTrace report={report} rows={audit} error={traceErr} />
      </footer>
        </>
      )}
    </div>
  )
}
