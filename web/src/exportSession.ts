import type { AuditRow, ConsolidateReport, GraphResponse } from './types'

/** Minimal shape shared by the voice transcript's messages — decoupled
 *  from `VoiceMessage` so this module doesn't need to import from
 *  `./voice/types` just to build an export blob. */
export interface ExportableTurn {
  role: string
  content: string
}

export interface SessionExport {
  learner: string
  exportedAt: string
  messages: {
    role: string
    content: string
  }[]
  keeper: { report: ConsolidateReport | null; audit: AuditRow[] }
  graph: GraphResponse
}

export function buildSessionExport(args: {
  learner: string
  turns: ExportableTurn[]
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
