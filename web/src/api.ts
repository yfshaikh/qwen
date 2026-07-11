import type {
  AuditRow,
  ChatMessage,
  ConsolidateReport,
  EvalRun,
  EvalScenario,
  EvalSnapshot,
  GraphResponse,
  VoiceSession,
  VoiceTurn,
} from './types'

export async function getGraph(learnerId: string, focus?: string): Promise<GraphResponse> {
  const q = new URLSearchParams({ learner_id: learnerId })
  if (focus) q.set('focus', focus)
  const r = await fetch(`/graph?${q}`)
  if (!r.ok) throw new Error(`/graph ${r.status}`)
  return r.json()
}

export async function consolidate(learnerId: string): Promise<ConsolidateReport> {
  const r = await fetch('/consolidate', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ learner_id: learnerId }),
  })
  if (!r.ok) throw new Error(`/consolidate ${r.status}`)
  return r.json()
}

export async function getAudit(learnerId: string): Promise<AuditRow[]> {
  const r = await fetch(`/audit?learner_id=${encodeURIComponent(learnerId)}`)
  if (!r.ok) throw new Error(`/audit ${r.status}`)
  return (await r.json()).rows
}

export async function getHistory(learnerId: string, limit = 200): Promise<ChatMessage[]> {
  const q = new URLSearchParams({ learner_id: learnerId, limit: String(limit) })
  const r = await fetch(`/history?${q}`)
  if (!r.ok) throw new Error(`/history ${r.status}`)
  return (await r.json()).messages
}

export async function getSessions(learnerId: string): Promise<VoiceSession[]> {
  const r = await fetch(`/sessions?learner_id=${encodeURIComponent(learnerId)}`)
  if (!r.ok) throw new Error(`/sessions ${r.status}`)
  return (await r.json()).sessions
}

export async function getSessionTurns(sessionId: string): Promise<VoiceTurn[]> {
  const r = await fetch(`/sessions/${sessionId}/turns`)
  if (!r.ok) throw new Error(`/sessions/${sessionId}/turns ${r.status}`)
  return (await r.json()).turns
}

export async function getMemoryStatus(learnerId: string): Promise<boolean> {
  const r = await fetch(`/memory/status?learner_id=${encodeURIComponent(learnerId)}`)
  if (!r.ok) return false
  return (await r.json()).consolidating
}

export async function health(): Promise<boolean> {
  try {
    const r = await fetch('/health')
    return r.ok && (await r.json()).db === true
  } catch {
    return false
  }
}

export async function getEvalScenarios(): Promise<EvalScenario[]> {
  const r = await fetch('/eval/scenarios')
  if (!r.ok) throw new Error(`eval scenarios ${r.status}`)
  return (await r.json()).scenarios
}
export async function getEvalRuns(): Promise<EvalRun[]> {
  const r = await fetch('/eval/runs')
  if (!r.ok) throw new Error(`eval runs ${r.status}`)
  return (await r.json()).runs
}
export async function getEvalRun(dir: string): Promise<EvalRun> {
  const r = await fetch(`/eval/runs/${encodeURIComponent(dir)}`)
  if (!r.ok) throw new Error(`eval run ${r.status}`)
  return r.json()
}
export async function launchEvalRun(scenarioId: string, budgetUsd?: number): Promise<{ run_id: string; dir: string }> {
  const body: Record<string, unknown> = { scenario_id: scenarioId }
  if (budgetUsd !== undefined) body.budget_usd = budgetUsd
  const r = await fetch('/eval/runs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`eval launch ${r.status}`)
  return r.json()
}
export async function cancelEvalRun(dir: string): Promise<boolean> {
  const r = await fetch(`/eval/runs/${encodeURIComponent(dir)}/cancel`, { method: 'POST' })
  if (!r.ok) return false
  return (await r.json()).cancelled
}
export async function getEvalSnapshot(dir: string, n: number): Promise<EvalSnapshot> {
  const r = await fetch(`/eval/runs/${encodeURIComponent(dir)}/snapshots/${n}`)
  if (!r.ok) throw new Error(`eval snapshot ${r.status}`)
  return r.json()
}
