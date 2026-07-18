import { useEffect, useState } from 'react'
import * as api from '../../api'
import type { EvalRun, EvalScenario } from '../../types'
import { CompareView } from './CompareView'
import { LaunchPanel } from './LaunchPanel'
import { RunDetail } from './RunDetail'
import { RunsTable } from './RunsTable'

export function EvalsPage({ scenarios }: { scenarios: EvalScenario[] }) {
  const [runs, setRuns] = useState<EvalRun[]>([])
  const [selectedDir, setSelectedDir] = useState<string | null>(null)
  const [comparing, setComparing] = useState(false)

  // Any alive run means the server rejects a new launch with 409 — mirror that
  // single-flight rule in the UI by disabling the launch controls.
  const anyAlive = runs.some((r) => r.alive)

  // Poll the runs list every 3s while mounted; clean the interval up on unmount.
  useEffect(() => {
    let cancelled = false
    async function tick() {
      try {
        const next = await api.getEvalRuns()
        if (!cancelled) setRuns(next)
      } catch {
        // transient error — keep the last good list
      }
    }
    tick()
    const id = setInterval(tick, 3000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  async function refresh() {
    try {
      setRuns(await api.getEvalRuns())
    } catch {
      /* keep last good list */
    }
  }

  async function onLaunch(scenarioId: string, budgetUsd?: number) {
    const { dir } = await api.launchEvalRun(scenarioId, budgetUsd)
    setSelectedDir(dir)
    await refresh()
  }

  async function onCancel(dir: string) {
    await api.cancelEvalRun(dir)
    await refresh()
  }

  const selectedRun = selectedDir
    ? runs.find((r) => (r.dir ?? r.run_id) === selectedDir) ?? null
    : null

  return (
    <main className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-zinc-50">
      <LaunchPanel scenarios={scenarios} disabled={anyAlive} onLaunch={onLaunch} />
      <div className="flex items-center justify-end px-4 py-2">
        <button
          onClick={() => setComparing((v) => !v)}
          className={`rounded border px-2 py-0.5 text-xs font-medium ${
            comparing
              ? 'border-indigo-200 bg-indigo-50 text-indigo-700'
              : 'border-zinc-200 text-zinc-600 hover:bg-zinc-50'
          }`}
        >
          Compare
        </button>
      </div>
      {comparing ? (
        <div className="border-t border-zinc-200 bg-white px-4 py-4">
          <CompareView runs={runs} />
        </div>
      ) : (
        <>
          <RunsTable
            runs={runs}
            selectedDir={selectedDir}
            onSelect={setSelectedDir}
            onCancel={onCancel}
          />
          {selectedRun && <RunDetail run={selectedRun} onClose={() => setSelectedDir(null)} />}
        </>
      )}
    </main>
  )
}
