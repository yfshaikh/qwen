import { useState } from 'react'
import type { EvalScenario } from '../../types'

export function LaunchPanel({
  scenarios,
  disabled,
  onLaunch,
}: {
  scenarios: EvalScenario[]
  disabled: boolean
  onLaunch: (scenarioId: string, budgetUsd?: number) => Promise<void>
}) {
  const [scenarioId, setScenarioId] = useState(scenarios[0]?.id ?? '')
  const [budget, setBudget] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [launching, setLaunching] = useState(false)

  const effectiveId = scenarioId || scenarios[0]?.id || ''

  async function launch() {
    if (!effectiveId) return
    setError(null)
    setLaunching(true)
    try {
      const budgetUsd = budget.trim() === '' ? undefined : Number(budget)
      await onLaunch(effectiveId, budgetUsd)
    } catch (e) {
      // Surface the server's 409 (a run is already alive) or any launch failure.
      setError(String(e instanceof Error ? e.message : e))
    }
    setLaunching(false)
  }

  return (
    <div className="flex flex-wrap items-end gap-3 border-b border-zinc-200 bg-white px-4 py-3">
      <label className="flex flex-col gap-1 text-xs text-zinc-500">
        Scenario
        <select
          value={effectiveId}
          onChange={(e) => setScenarioId(e.target.value)}
          disabled={disabled || scenarios.length === 0}
          className="rounded-lg border border-zinc-200 px-2 py-1 text-sm text-zinc-700 disabled:opacity-40"
        >
          {scenarios.map((s) => (
            <option key={s.id} value={s.id}>
              {s.id}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-zinc-500">
        Budget (USD)
        <input
          type="number"
          step="0.01"
          min="0"
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
          placeholder="optional"
          disabled={disabled}
          className="w-28 rounded-lg border border-zinc-200 px-2 py-1 text-sm text-zinc-700 disabled:opacity-40"
        />
      </label>
      <button
        onClick={launch}
        disabled={disabled || launching || !effectiveId}
        className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:opacity-40"
      >
        {launching ? 'Launching…' : 'Launch'}
      </button>
      {error && <span className="text-xs text-red-600">{error}</span>}
    </div>
  )
}
