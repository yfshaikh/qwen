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
