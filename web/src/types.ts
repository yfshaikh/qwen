export interface GraphEvidence {
  kind: string
  content: string | null
  importance: number | null
}

export interface GraphNode {
  id: string
  label: string
  type: string
  summary: string | null
  mastery: number | null
  confidence: number | null
  salience: number | null
  importance?: number | null
  evidence: GraphEvidence[]
}

export interface GraphEdge {
  id: string | null
  source: string
  target: string
  type: string
  weight: number
}

export interface GraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface AuditRow {
  id: string
  op: string
  rationale: string | null
  model: string | null
  tokens: number | null
  cost: number | null
  ts: string
}

export interface ConsolidateReport {
  learner_id: string
  processed_events: number
  nodes_created: number
  nodes_updated: number
  edges_created: number
  merged: number
  forgotten: number
  errors: string[]
  skipped: boolean
}

export interface SavedEvent {
  type: string // LearningEvent kind: 'utterance' | 'tutor_explanation'
  text: string | null
}

export interface ChatMessage {
  role: string
  content: string
}

export interface VoiceSession {
  id: string
  started_at: string | null
  ended_at: string | null
  turns: number
}

export interface VoiceTurn {
  id: string
  role: 'user' | 'assistant'
  text: string
  ts: string | null
}

export interface EvalScenario {
  id: string
  path: string
  checks: string[]
}

export interface EvalCheckResult {
  name: string
  metrics: Record<string, number>
  passed: boolean
  details: string[]
  error: string | null
}

export interface EvalRunCost {
  tokens_in: number
  tokens_out: number
  usd: number
  by_role: Record<string, { tokens_in: number; tokens_out: number }>
}

export interface EvalRun {
  run_id: string
  dir?: string
  scenario_id: string
  status: string
  started_at: string
  finished_at: string | null
  checks: EvalCheckResult[]
  cost: EvalRunCost
  error: string | null
  alive?: boolean
  // Inlined by the runner at finish (absent while a run is live).
  transcript?: { role: string; content: string; session: number }[]
}

export interface EvalSnapshot {
  session: number
  sim_ts: string
  graph: GraphResponse & { evidence?: Record<string, unknown[]> }
  report: Record<string, number>
}

export interface InsightsSummary {
  concepts: number
  edges: number
  evidence: number
  avg_mastery: number | null
  avg_confidence: number | null
  forgotten: number
  fading: number
  open_misconceptions: number
  sessions: number
  last_active: string | null
}

export interface MasteryPoint {
  ts: string | null
  mastery: number | null
  confidence: number | null
}

export interface Hotspot {
  node_id: string
  label: string
  struggle: number
  mastery: number | null
  trend: string
}

export interface ActivityDay {
  day: string
  count: number
}

export interface ReviewItem {
  node_id: string
  label: string
  score: number
  reason: string
}

export interface Blocker {
  node_id: string
  label: string
  mastery: number
  path: string[]
}
