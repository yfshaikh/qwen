// Tiny fetch wrapper around the Engram HTTP API.
//
// Base URL: when VITE_API_BASE is set (e.g. production / Docker), requests go
// there directly. When it is empty (default in dev), requests are same-origin
// ("/graph", ...) and Vite's dev proxy forwards them to the backend — so no
// CORS setup is needed locally.

import type {
  AuditView,
  ConsolidateResult,
  GraphView,
  IngestResult,
  RawEvent,
  RecallResult,
  TutorTurnResult,
} from "./types";

export const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  body: string;
  constructor(status: number, message: string, body = "") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch (err) {
    // Network failure (backend down, DNS, CORS preflight, ...).
    const detail = err instanceof Error ? err.message : String(err);
    throw new ApiError(0, `Network error reaching ${path}: ${detail}`);
  }

  const raw = await res.text();
  if (!res.ok) {
    // FastAPI returns {"detail": ...}; surface it if present.
    let message = `${res.status} ${res.statusText}`;
    try {
      const parsed = JSON.parse(raw);
      const detail = parsed?.detail;
      if (detail) {
        message += `: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`;
      }
    } catch {
      if (raw) message += `: ${raw.slice(0, 300)}`;
    }
    throw new ApiError(res.status, message, raw);
  }

  if (!raw) return undefined as T;
  return JSON.parse(raw) as T;
}

const q = (params: Record<string, string | number | undefined>): string => {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
};

export const api = {
  getGraph(learnerId: string, focus?: string, hops = 1): Promise<GraphView> {
    return request<GraphView>(`/graph${q({ learner_id: learnerId, focus, hops })}`);
  },

  getAudit(learnerId: string, limit = 50): Promise<AuditView> {
    return request<AuditView>(`/audit${q({ learner_id: learnerId, limit })}`);
  },

  consolidate(learnerId: string): Promise<ConsolidateResult> {
    return request<ConsolidateResult>("/consolidate", {
      method: "POST",
      body: JSON.stringify({ learner_id: learnerId }),
    });
  },

  recall(learnerId: string, query: string, budget?: number): Promise<RecallResult> {
    return request<RecallResult>("/recall", {
      method: "POST",
      body: JSON.stringify({ learner_id: learnerId, query, budget }),
    });
  },

  tutorTurn(learnerId: string, message: string, sessionId?: string): Promise<TutorTurnResult> {
    return request<TutorTurnResult>("/tutor/turn", {
      method: "POST",
      body: JSON.stringify({ learner_id: learnerId, message, session_id: sessionId }),
    });
  },

  ingest(learnerId: string, events: RawEvent[]): Promise<IngestResult> {
    return request<IngestResult>("/ingest", {
      method: "POST",
      body: JSON.stringify({ learner_id: learnerId, events }),
    });
  },
};
