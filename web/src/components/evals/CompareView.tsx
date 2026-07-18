import { useState } from 'react'
import type { EvalRun } from '../../types'

// Duplicated from src/engram/eval/regression.py — that module is the source of
// truth. A shared list would require a Python→TS codegen step for 9 strings;
// accepted duplication. Keep in sync if the backend set changes.
const LOWER_BETTER = new Set([
  'mean_rank',
  'mastered_leak_rate',
  'duplicate_label_rate',
  'on_re_explanation_rate',
  'baseline_re_explanation_rate',
  'lifecycle_failures',
  'integrity_failures',
  'orphan_edges',
  'usd',
])

// Same flatten rule as regression.flatten_metrics: merge each check's metrics in
// order; on a duplicate key prefix with the check name; then append cost `usd`.
function flattenMetrics(run: EvalRun): Record<string, number> {
  const flat: Record<string, number> = {}
  for (const c of run.checks ?? []) {
    for (const [k, v] of Object.entries(c.metrics ?? {})) {
      flat[k in flat ? `${c.name}.${k}` : k] = v
    }
  }
  const usd = run.cost?.usd
  if (usd != null) flat.usd = usd
  return flat
}

function dirOf(run: EvalRun): string {
  return run.dir ?? run.run_id
}

function isFinished(run: EvalRun): boolean {
  return run.status !== 'running'
}

export function CompareView({ runs }: { runs: EvalRun[] }) {
  const finished = runs.filter(isFinished)
  const [aDir, setADir] = useState<string>(finished[0] ? dirOf(finished[0]) : '')
  const [bDir, setBDir] = useState<string>(finished[1] ? dirOf(finished[1]) : '')

  const a = finished.find((r) => dirOf(r) === aDir)
  const b = finished.find((r) => dirOf(r) === bDir)

  if (finished.length < 2) {
    return <div className="px-1 py-3 text-xs text-zinc-400">Need at least two finished runs to compare.</div>
  }

  const fa = a ? flattenMetrics(a) : {}
  const fb = b ? flattenMetrics(b) : {}
  const keys = Array.from(new Set([...Object.keys(fa), ...Object.keys(fb)])).sort()

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 text-xs">
        <label className="flex items-center gap-1.5 text-zinc-500">
          A
          <select
            value={aDir}
            onChange={(e) => setADir(e.target.value)}
            className="rounded border border-zinc-200 bg-zinc-50 px-1.5 py-0.5 font-mono text-zinc-700"
          >
            {finished.map((r) => (
              <option key={dirOf(r)} value={dirOf(r)}>
                {dirOf(r)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-zinc-500">
          B
          <select
            value={bDir}
            onChange={(e) => setBDir(e.target.value)}
            className="rounded border border-zinc-200 bg-zinc-50 px-1.5 py-0.5 font-mono text-zinc-700"
          >
            {finished.map((r) => (
              <option key={dirOf(r)} value={dirOf(r)}>
                {dirOf(r)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-zinc-400">
            <tr className="border-b border-zinc-200">
              <th className="px-3 py-2 font-medium">Metric</th>
              <th className="px-3 py-2 text-right font-medium">A</th>
              <th className="px-3 py-2 text-right font-medium">B</th>
              <th className="px-3 py-2 text-right font-medium">Δ</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => {
              const va = fa[k]
              const vb = fb[k]
              const both = va != null && vb != null
              const delta = both ? vb - va : null
              // Direction of "better": for LOWER_BETTER metrics a rise (B>A) is
              // worse (red); otherwise a rise is better (green). Zero = neutral.
              let tone = 'text-zinc-400'
              if (delta != null && delta !== 0) {
                const worse = LOWER_BETTER.has(k) ? delta > 0 : delta < 0
                tone = worse ? 'text-red-600' : 'text-emerald-600'
              }
              return (
                <tr key={k} className="border-b border-zinc-100">
                  <td className="px-3 py-1.5 font-mono text-zinc-600">{k}</td>
                  <td className="px-3 py-1.5 text-right font-mono text-zinc-700">
                    {va != null ? va.toFixed(4) : '—'}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-zinc-700">
                    {vb != null ? vb.toFixed(4) : '—'}
                  </td>
                  <td className={`px-3 py-1.5 text-right font-mono ${tone}`}>
                    {delta != null ? `${delta > 0 ? '+' : ''}${delta.toFixed(4)}` : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
