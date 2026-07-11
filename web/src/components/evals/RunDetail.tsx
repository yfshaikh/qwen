import { useEffect, useState } from 'react'
import * as api from '../../api'
import type { EvalCheckResult, EvalRun, EvalSnapshot } from '../../types'
import { GraphScrubber } from './GraphScrubber'
import { LifecycleTimeline } from './LifecycleTimeline'

// Number of consolidation sessions in a finished run, derived from the inlined
// transcript (each turn carries its session index).
function sessionCount(run: EvalRun): number {
  const t = run.transcript ?? []
  if (t.length === 0) return 0
  return Math.max(...t.map((x) => x.session)) + 1
}

function CheckCard({ check }: { check: EvalCheckResult }) {
  return (
    <div className="rounded border border-zinc-200 p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm font-medium text-zinc-800">{check.name}</span>
        <span
          className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${
            check.passed ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
          }`}
        >
          {check.passed ? 'pass' : 'fail'}
        </span>
      </div>
      {Object.keys(check.metrics ?? {}).length > 0 && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs sm:grid-cols-3">
          {Object.entries(check.metrics).map(([k, v]) => (
            <div key={k} className="flex justify-between gap-2">
              <dt className="truncate font-mono text-zinc-500">{k}</dt>
              <dd className="font-mono text-zinc-700">{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {(check.details ?? []).length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-zinc-500">
          {check.details.map((d, i) => (
            <li key={i}>{d}</li>
          ))}
        </ul>
      )}
      {check.error && <p className="mt-2 text-xs text-red-600">{check.error}</p>}
    </div>
  )
}

function Transcript({ run }: { run: EvalRun }) {
  const turns = run.transcript ?? []
  if (turns.length === 0) return null
  const sessions = sessionCount(run)
  return (
    <div className="space-y-4">
      {Array.from({ length: sessions }, (_, si) => (
        <div key={si} className="space-y-2">
          <div className="text-[11px] uppercase tracking-wider text-zinc-400">session {si}</div>
          {turns
            .filter((t) => t.session === si)
            .map((t, i) => (
              <div key={i} className={`flex ${t.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[80%] whitespace-pre-wrap rounded px-3 py-2 text-xs ${
                    t.role === 'user' ? 'bg-indigo-50 text-zinc-800' : 'bg-zinc-100 text-zinc-700'
                  }`}
                >
                  {t.content}
                </div>
              </div>
            ))}
        </div>
      ))}
    </div>
  )
}

export function RunDetail({ run: runProp, onClose }: { run: EvalRun; onClose: () => void }) {
  const dir = runProp.dir ?? runProp.run_id
  const [run, setRun] = useState<EvalRun>(runProp)
  const [events, setEvents] = useState<string[]>([])
  const [sseError, setSseError] = useState<string | null>(null)
  const [snapshots, setSnapshots] = useState<EvalSnapshot[]>([])

  // Keep in sync when the parent's 3s poll hands down a fresher row.
  useEffect(() => {
    setRun(runProp)
  }, [runProp])

  // Live runs: stream the event log; refetch (for transcript + final checks)
  // and close the stream on the terminal status event. Close on unmount too.
  useEffect(() => {
    if (run.status !== 'running') return
    const es = new EventSource(`/eval/runs/${encodeURIComponent(dir)}/events`)
    es.onmessage = (ev) => {
      setEvents((prev) => [...prev, ev.data])
      let msg: { type?: string; status?: string }
      try {
        msg = JSON.parse(ev.data)
      } catch {
        return
      }
      if (msg.type === 'status' && msg.status !== 'running') {
        es.close()
        api.getEvalRun(dir).then(setRun).catch(() => {})
      }
    }
    es.onerror = () => {
      // Server restart / stream drop: close and surface one line, no retry loop.
      es.close()
      setSseError('Live event stream disconnected.')
    }
    return () => es.close()
  }, [dir, run.status])

  // Finished runs: fetch every session snapshot for the timeline. A 404 means an
  // older run without per-session snapshots — leave the list empty (sections hide).
  useEffect(() => {
    if (run.status === 'running') return
    const n = sessionCount(run)
    if (n === 0) return
    let cancelled = false
    Promise.all(Array.from({ length: n }, (_, i) => api.getEvalSnapshot(dir, i)))
      .then((snaps) => {
        if (!cancelled) setSnapshots(snaps)
      })
      .catch(() => {
        if (!cancelled) setSnapshots([])
      })
    return () => {
      cancelled = true
    }
    // NB: deliberately NOT depending on run.transcript — the parent's 3s poll
    // re-serializes run.json, producing a fresh array reference each tick with
    // identical content for a finished run; depending on it would re-fetch every
    // session snapshot every poll. dir + status changes cover all real cases.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dir, run.status])

  // An orphaned run (server restarted mid-run) still says status=running in
  // run.json but has no live task — don't open an SSE stream that never ends.
  const live = run.status === 'running' && run.alive !== false
  const isError = run.status === 'error'

  return (
    <div className="space-y-4 border-t border-zinc-200 bg-white px-4 py-4">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium text-zinc-800">{run.scenario_id}</span>
        <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs font-medium text-zinc-600">{run.status}</span>
        <span className="font-mono text-xs text-zinc-600">${(run.cost?.usd ?? 0).toFixed(4)}</span>
        {run.finished_at && run.started_at && (
          <span className="text-xs text-zinc-500">
            {Math.max(0, Math.round((Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000))}s
          </span>
        )}
        <button
          onClick={onClose}
          className="ml-auto rounded border border-zinc-200 px-2 py-0.5 text-xs text-zinc-600 hover:bg-zinc-50"
        >
          Close
        </button>
      </div>

      {/* Per-role cost table */}
      {run.cost?.by_role && Object.keys(run.cost.by_role).length > 0 && (
        <table className="text-xs">
          <thead className="text-zinc-400">
            <tr>
              <th className="px-2 py-0.5 text-left font-medium">role</th>
              <th className="px-2 py-0.5 text-right font-medium">tokens in</th>
              <th className="px-2 py-0.5 text-right font-medium">tokens out</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(run.cost.by_role).map(([role, t]) => (
              <tr key={role}>
                <td className="px-2 py-0.5 font-mono text-zinc-600">{role}</td>
                <td className="px-2 py-0.5 text-right font-mono text-zinc-700">{t.tokens_in}</td>
                <td className="px-2 py-0.5 text-right font-mono text-zinc-700">{t.tokens_out}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {sseError && <div className="rounded bg-amber-50 px-3 py-2 text-xs text-amber-700">{sseError}</div>}

      {/* Error-status runs: show the error prominently, no checks section. */}
      {isError ? (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {run.error ?? 'Run failed.'}
        </div>
      ) : (
        <>
          {run.error && (
            <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              {run.error}
            </div>
          )}
          {(run.checks ?? []).length > 0 && (
            <div className="space-y-2">
              {run.checks.map((c) => (
                <CheckCard key={c.name} check={c} />
              ))}
            </div>
          )}
        </>
      )}

      {/* Live: SSE event log strip. Finished: timeline + scrubber + transcript. */}
      {live ? (
        <div className="max-h-48 overflow-y-auto rounded border border-zinc-200 bg-zinc-50 p-2 font-mono text-[11px] text-zinc-600">
          {events.length === 0 ? (
            <span className="text-zinc-400">Waiting for events…</span>
          ) : (
            events.map((e, i) => <div key={i}>{e}</div>)
          )}
        </div>
      ) : (
        <>
          {snapshots.length > 0 && (
            <section className="space-y-1">
              <h3 className="text-xs font-medium uppercase tracking-wider text-zinc-400">Lifecycle</h3>
              <LifecycleTimeline snapshots={snapshots} />
            </section>
          )}
          {sessionCount(run) > 0 && (
            <section className="space-y-1">
              <h3 className="text-xs font-medium uppercase tracking-wider text-zinc-400">Graph</h3>
              <GraphScrubber dir={dir} sessions={sessionCount(run)} />
            </section>
          )}
          {(run.transcript ?? []).length > 0 && (
            <section className="space-y-2">
              <h3 className="text-xs font-medium uppercase tracking-wider text-zinc-400">Transcript</h3>
              <Transcript run={run} />
            </section>
          )}
        </>
      )}
    </div>
  )
}
