import type { AuditRow, ChatMessage, ConsolidateReport, GraphResponse, VoiceSession, VoiceTurn } from './types'

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
