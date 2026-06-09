import type { GraphEdge, GraphNode } from "./types";

export interface Point {
  x: number;
  y: number;
}

/**
 * Deterministic client-side layout (the API returns no positions).
 *
 * Each node's initial position is derived from a hash of its id (so it is
 * stable across reloads and graph refreshes — a node keeps roughly the same
 * neighborhood even as other nodes come and go), then a fixed number of
 * force-directed iterations (pairwise repulsion + spring attraction along
 * edges + mild centering) are run with no randomness.
 */
export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[]): Map<string, Point> {
  const positions = new Map<string, Point>();
  if (nodes.length === 0) return positions;

  // Sort by id so iteration order (and therefore float accumulation) is
  // deterministic regardless of API response ordering.
  const sorted = [...nodes].sort((a, b) => a.id.localeCompare(b.id));

  // Initial placement: hash-derived angle + radius on a rough disc.
  for (const node of sorted) {
    const h1 = fnv1a(node.id);
    const h2 = fnv1a(node.id + "::r");
    const angle = ((h1 % 3600) / 3600) * Math.PI * 2;
    const radius = 120 + (h2 % 240);
    positions.set(node.id, {
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
    });
  }

  const ids = sorted.map((n) => n.id);
  const validEdges = edges.filter((e) => positions.has(e.source) && positions.has(e.target));

  const ITERATIONS = 200;
  const REPULSION = 28000;
  const SPRING = 0.015;
  const SPRING_LENGTH = 190;
  const CENTERING = 0.004;

  for (let iter = 0; iter < ITERATIONS; iter++) {
    const cooling = 1 - iter / ITERATIONS;
    const disp = new Map<string, Point>();
    for (const id of ids) disp.set(id, { x: 0, y: 0 });

    // Pairwise repulsion.
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = positions.get(ids[i])!;
        const b = positions.get(ids[j])!;
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) {
          // Coincident nodes: nudge apart deterministically by id order.
          dx = 1;
          dy = i - j;
          d2 = dx * dx + dy * dy;
        }
        const force = REPULSION / d2;
        const d = Math.sqrt(d2);
        const fx = (dx / d) * force;
        const fy = (dy / d) * force;
        const da = disp.get(ids[i])!;
        const db = disp.get(ids[j])!;
        da.x += fx;
        da.y += fy;
        db.x -= fx;
        db.y -= fy;
      }
    }

    // Spring attraction along edges.
    for (const edge of validEdges) {
      const a = positions.get(edge.source)!;
      const b = positions.get(edge.target)!;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const weight = edge.weight ?? 1;
      const force = SPRING * (d - SPRING_LENGTH) * Math.min(2, Math.max(0.3, weight));
      const fx = (dx / d) * force;
      const fy = (dy / d) * force;
      const da = disp.get(edge.source)!;
      const db = disp.get(edge.target)!;
      da.x += fx;
      da.y += fy;
      db.x -= fx;
      db.y -= fy;
    }

    // Mild pull toward the origin + apply displacement with cooling cap.
    const maxStep = 38 * cooling + 2;
    for (const id of ids) {
      const p = positions.get(id)!;
      const d = disp.get(id)!;
      d.x -= p.x * CENTERING;
      d.y -= p.y * CENTERING;
      const len = Math.sqrt(d.x * d.x + d.y * d.y);
      if (len > 0) {
        const step = Math.min(len, maxStep);
        p.x += (d.x / len) * step;
        p.y += (d.y / len) * step;
      }
    }
  }

  return positions;
}

/** FNV-1a 32-bit hash — deterministic across sessions. */
function fnv1a(str: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}
