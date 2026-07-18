import type { EvalRun } from '../../types'

// Effective status: a 'running' row whose process is no longer alive means the
// server restarted mid-run — surface it as 'orphaned' rather than a live run.
function effectiveStatus(run: EvalRun): string {
  if (run.status === 'running' && !run.alive) return 'orphaned'
  return run.status
}

const CHIP: Record<string, string> = {
  passed: 'bg-emerald-100 text-emerald-700',
  failed: 'bg-red-100 text-red-700',
  running: 'bg-indigo-100 text-indigo-700 animate-pulse',
  over_budget: 'bg-amber-100 text-amber-700',
  orphaned: 'bg-amber-100 text-amber-700',
  cancelled: 'bg-zinc-100 text-zinc-500',
  error: 'bg-zinc-100 text-zinc-500',
}

function StatusChip({ status }: { status: string }) {
  const cls = CHIP[status] ?? 'bg-zinc-100 text-zinc-500'
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  )
}

export function RunsTable({
  runs,
  selectedDir,
  onSelect,
  onCancel,
}: {
  runs: EvalRun[]
  selectedDir: string | null
  onSelect: (dir: string) => void
  onCancel: (dir: string) => void
}) {
  if (runs.length === 0) {
    return <div className="px-3 py-6 text-center text-xs text-zinc-400">No eval runs yet.</div>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead className="text-zinc-400">
          <tr className="border-b border-zinc-200">
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 font-medium">Scenario</th>
            <th className="px-3 py-2 font-medium">Started</th>
            <th className="px-3 py-2 font-medium">Cost</th>
            <th className="px-3 py-2 font-medium">Checks</th>
            <th className="px-3 py-2 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const dir = run.dir ?? run.run_id
            const passed = run.checks?.filter((c) => c.passed).length ?? 0
            const total = run.checks?.length ?? 0
            return (
              <tr
                key={dir}
                onClick={() => onSelect(dir)}
                data-testid="run-row"
                className={`cursor-pointer border-b border-zinc-100 hover:bg-zinc-50 ${
                  selectedDir === dir ? 'bg-indigo-50' : ''
                }`}
              >
                <td className="px-3 py-2">
                  <StatusChip status={effectiveStatus(run)} />
                </td>
                <td className="px-3 py-2 text-zinc-700">{run.scenario_id}</td>
                <td className="px-3 py-2 text-zinc-500">
                  {run.started_at ? new Date(run.started_at).toLocaleString() : '—'}
                </td>
                <td className="px-3 py-2 font-mono text-zinc-600">${(run.cost?.usd ?? 0).toFixed(4)}</td>
                <td className="px-3 py-2 text-zinc-600">
                  {passed}/{total}
                </td>
                <td className="px-3 py-2 text-right">
                  {run.alive && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        onCancel(dir)
                      }}
                      className="rounded border border-zinc-200 px-2 py-0.5 text-xs font-medium text-zinc-600 transition hover:bg-red-50 hover:text-red-600"
                    >
                      Cancel
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
