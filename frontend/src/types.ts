// Shapes from docs/API.md — the single source of truth for the contract.

export type NodeType = "concept" | "preference" | "goal";
export type EdgeType = "prerequisite" | "relates_to" | "part_of";

export interface GraphNode {
  id: string;
  type: NodeType;
  label: string;
  summary?: string | null;
  mastery: number | null;
  confidence: number | null;
  salience: number | null;
  last_seen_at: string | null;
  evidence_count: number | null;
  forgotten_at: string | null;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: EdgeType;
  weight: number | null;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Evidence {
  id: string;
  kind: string;
  content: string | null;
  importance: number | null;
  created_at: string | null;
}

export interface EvidenceResponse {
  evidence: Evidence[];
}

export interface AuditEntry {
  op: string;
  rationale: string | null;
  model: string | null;
  tokens: number | null;
  ts: string | null;
  input_refs: Record<string, unknown> | null;
  output_refs: Record<string, unknown> | null;
}

export interface AuditResponse {
  entries: AuditEntry[];
}

export interface IngestResponse {
  ids: string[];
}

export interface ConsolidateStats {
  events_processed: number;
  nodes_created: number;
  nodes_updated: number;
  edges_created: number;
  merged: number;
  pruned: number;
}

export interface ConsolidateResponse {
  stats: ConsolidateStats;
}

export interface RecallResult {
  text_block: string;
  subgraph: GraphResponse;
}

export interface TutorTurnResponse {
  reply: string;
  recall: RecallResult;
  events_emitted: number;
}
