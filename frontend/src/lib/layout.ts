// Deterministic force-directed layout computed client-side, since /graph does
// not return positions. Same input nodes/edges -> same positions every render
// (seeded from a hash of each node id), so the graph stays readable and stable.

import type { GraphEdge, GraphNode } from "./types";

export interface XY {
  x: number;
  y: number;
}

// Deterministic 32-bit hash of a string -> used to seed a node's start point.
function hash(str: string): number {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function computeLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  opts: { width?: number; height?: number; iterations?: number } = {},
): Map<string, XY> {
  const width = opts.width ?? 900;
  const height = opts.height ?? 640;
  const iterations = opts.iterations ?? 320;
  const pos = new Map<string, XY>();

  if (nodes.length === 0) return pos;

  // Single node: center it.
  if (nodes.length === 1) {
    pos.set(nodes[0].id, { x: width / 2, y: height / 2 });
    return pos;
  }

  const cx = width / 2;
  const cy = height / 2;

  // Seed deterministically on a circle, jittered by the id hash so the initial
  // configuration is spread out (avoids degenerate all-on-top starts).
  nodes.forEach((n, i) => {
    const h = hash(n.id);
    const angle = (i / nodes.length) * Math.PI * 2 + (h % 360) * (Math.PI / 720);
    const radius = 180 + (h % 140);
    pos.set(n.id, {
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    });
  });

  const ids = nodes.map((n) => n.id);
  const present = new Set(ids);
  const adjacency = edges.filter((e) => present.has(e.source) && present.has(e.target));

  // Fruchterman-Reingold-ish constants tuned for a small POC graph.
  const area = width * height;
  const k = Math.sqrt(area / nodes.length); // ideal edge length
  const kRepel = k * k;
  const kSpring = 1 / k;
  let temp = width / 8;
  const cool = temp / (iterations + 1);

  const disp = new Map<string, XY>();

  for (let iter = 0; iter < iterations; iter++) {
    for (const id of ids) disp.set(id, { x: 0, y: 0 });

    // Repulsion between every pair.
    for (let i = 0; i < ids.length; i++) {
      const a = pos.get(ids[i])!;
      for (let j = i + 1; j < ids.length; j++) {
        const b = pos.get(ids[j])!;
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let dist = Math.hypot(dx, dy);
        if (dist < 0.01) {
          // Deterministic nudge for coincident nodes.
          dx = ((hash(ids[i] + ids[j]) % 100) - 50) / 50;
          dy = ((hash(ids[j] + ids[i]) % 100) - 50) / 50;
          dist = Math.hypot(dx, dy) || 1;
        }
        const force = kRepel / dist;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        const da = disp.get(ids[i])!;
        const db = disp.get(ids[j])!;
        da.x += fx;
        da.y += fy;
        db.x -= fx;
        db.y -= fy;
      }
    }

    // Attraction along edges.
    for (const e of adjacency) {
      const a = pos.get(e.source)!;
      const b = pos.get(e.target)!;
      const dx = a.x - b.x;
      const dy = a.y - b.y;
      const dist = Math.hypot(dx, dy) || 0.01;
      const force = (dist * dist) * kSpring;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      const da = disp.get(e.source)!;
      const db = disp.get(e.target)!;
      da.x -= fx;
      da.y -= fy;
      db.x += fx;
      db.y += fy;
    }

    // Apply displacement, capped by temperature; keep within bounds.
    for (const id of ids) {
      const d = disp.get(id)!;
      const p = pos.get(id)!;
      const len = Math.hypot(d.x, d.y) || 0.01;
      p.x += (d.x / len) * Math.min(len, temp);
      p.y += (d.y / len) * Math.min(len, temp);
      p.x = Math.max(40, Math.min(width - 40, p.x));
      p.y = Math.max(40, Math.min(height - 40, p.y));
    }

    temp -= cool;
  }

  return pos;
}
