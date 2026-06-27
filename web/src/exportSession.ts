import type { PendingTurn } from './chat'
import type { AuditRow, ConsolidateReport, GraphResponse } from './types'

export interface SessionExport {
  learner: string
  exportedAt: string
  messages: {
    role: string
    content: string
    recalled?: string
    saved?: { type: string; text: string | null }[]
  }[]
  keeper: { report: ConsolidateReport | null; audit: AuditRow[] }
  graph: GraphResponse
}

export function buildSessionExport(args: {
  learner: string
  turns: PendingTurn[]
  report: ConsolidateReport | null
  audit: AuditRow[]
  graph: GraphResponse
  now?: string
}): SessionExport {
  return {
    learner: args.learner,
    exportedAt: args.now ?? new Date().toISOString(),
    messages: args.turns.map((t) => ({
      role: t.role,
      content: t.content,
      recalled: t.recalled,
      saved: t.saved,
    })),
    keeper: { report: args.report, audit: args.audit },
    graph: args.graph,
  }
}

export function downloadJson(filename: string, obj: unknown): void {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
