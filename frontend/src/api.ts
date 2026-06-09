import type {
  AuditResponse,
  ConsolidateResponse,
  EvidenceResponse,
  GraphResponse,
  IngestResponse,
  TutorTurnResponse,
} from "./types";

// In dev the Vite proxy forwards these paths to http://localhost:8000.
// In production builds, VITE_API_BASE (baked at build time) prefixes all
// requests; when unset we keep relative paths (same-origin / reverse proxy).
const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method ?? "GET";
  let res: Response;
  try {
    res = await fetch(API_BASE + path, init);
  } catch (err) {
    throw new Error(
      `${method} ${path}: network error — is the backend running? (${(err as Error).message})`,
    );
  }
  if (!res.ok) {
    let detail = "";
    try {
      detail = (await res.text()).slice(0, 300);
    } catch {
      /* ignore */
    }
    throw new Error(`${method} ${path} failed with ${res.status}${detail ? ` — ${detail}` : ""}`);
  }
  return (await res.json()) as T;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getGraph(learnerId: string, focus?: string, hops = 1): Promise<GraphResponse> {
  const params = new URLSearchParams({ learner_id: learnerId, hops: String(hops) });
  if (focus) params.set("focus", focus);
  return request<GraphResponse>(`/graph?${params}`);
}

export function getEvidence(nodeId: string, limit = 20): Promise<EvidenceResponse> {
  const params = new URLSearchParams({ node_id: nodeId, limit: String(limit) });
  return request<EvidenceResponse>(`/evidence?${params}`);
}

export function getAudit(learnerId: string, limit = 100): Promise<AuditResponse> {
  const params = new URLSearchParams({ learner_id: learnerId, limit: String(limit) });
  return request<AuditResponse>(`/audit?${params}`);
}

export function postIngest(
  learnerId: string,
  events: Array<{ type: string; text?: string; refs?: Record<string, unknown>; signals?: Record<string, unknown> }>,
): Promise<IngestResponse> {
  return post<IngestResponse>("/ingest", { learner_id: learnerId, events });
}

export function postConsolidate(learnerId: string): Promise<ConsolidateResponse> {
  return post<ConsolidateResponse>("/consolidate", { learner_id: learnerId });
}

export function postTutorTurn(
  learnerId: string,
  message: string,
  sessionId?: string,
): Promise<TutorTurnResponse> {
  const body: Record<string, unknown> = { learner_id: learnerId, message };
  if (sessionId) body.session_id = sessionId;
  return post<TutorTurnResponse>("/tutor/turn", body);
}
