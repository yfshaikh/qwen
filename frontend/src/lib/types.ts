// Mirrors the Engram HTTP API contract (see /docs/API.md).

export type NodeType = "concept" | "preference" | "goal";
export type EdgeType = "prerequisite" | "relates_to" | "part_of";

export interface GraphNode {
  id: string;
  type: NodeType;
  label: string;
  summary: string | null;
  mastery: number | null;
  confidence: number | null;
  salience: number | null;
  last_seen_at: string | null;
  evidence_count: number;
  forgotten_at: string | null;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: EdgeType;
  weight: number;
}

export interface GraphView {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface AuditEntryItem {
  op: string;
  rationale: string | null;
  model: string | null;
  tokens: number | null;
  ts: string;
  input_refs: Record<string, unknown> | null;
  output_refs: Record<string, unknown> | null;
}

export interface AuditView {
  entries: AuditEntryItem[];
}

export interface ConsolidateStats {
  events_processed: number;
  nodes_created: number;
  nodes_updated: number;
  edges_created: number;
  merged: number;
  pruned: number;
}

export interface ConsolidateResult {
  stats: ConsolidateStats;
}

export interface RecallResult {
  text_block: string;
  subgraph: GraphView;
}

export interface TutorTurnResult {
  reply: string;
  recall: RecallResult;
  events_emitted: number;
}

export interface IngestResult {
  ids: string[];
}

// A single learning event as accepted by POST /ingest.
export interface RawEvent {
  type: string;
  text?: string;
  refs?: Record<string, unknown>;
  signals?: Record<string, unknown>;
}
