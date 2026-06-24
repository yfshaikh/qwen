import { parseSSE, type SSEFrame } from './sse'
import type { AuditRow, ChatMessage, ConsolidateReport, GraphResponse } from './types'

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

export async function health(): Promise<boolean> {
  try {
    const r = await fetch('/health')
    return r.ok && (await r.json()).db === true
  } catch {
    return false
  }
}

export async function* streamChat(
  learnerId: string,
  messages: ChatMessage[],
  budget?: number,
): AsyncGenerator<SSEFrame> {
  const r = await fetch('/chat', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ learner_id: learnerId, messages, budget }),
  })
  if (!r.ok || !r.body) throw new Error(`/chat ${r.status}`)
  yield* parseSSE(r)
}
