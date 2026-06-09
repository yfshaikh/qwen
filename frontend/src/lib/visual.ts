// Visual encoding of node/edge attributes -> pixels & color.

import type { EdgeType, GraphNode, NodeType } from "./types";

export const clamp01 = (x: number): number => Math.max(0, Math.min(1, x));

// mastery 0..1 -> red -> amber -> green. null mastery -> neutral grey.
export function masteryColor(mastery: number | null): string {
  if (mastery == null) return "#9ca3af"; // grey for "unknown"
  const m = clamp01(mastery);
  // hue 0 (red) -> 45 (amber) -> 130 (green)
  const hue = m < 0.5 ? 0 + (m / 0.5) * 45 : 45 + ((m - 0.5) / 0.5) * 85;
  return `hsl(${Math.round(hue)}, 75%, 45%)`;
}

// salience 0..1 -> opacity. Faded = forgotten/decayed. Floor so faint nodes
// stay clickable. Forgotten nodes (forgotten_at set) are dimmed further.
export function salienceOpacity(node: GraphNode): number {
  const base = node.salience == null ? 0.85 : 0.25 + clamp01(node.salience) * 0.75;
  return node.forgotten_at ? base * 0.45 : base;
}

// mastery -> node diameter in px. More mastered = larger/more prominent.
export function masterySize(mastery: number | null): number {
  const m = mastery == null ? 0.35 : clamp01(mastery);
  return Math.round(46 + m * 44); // 46..90 px
}

// Short badge + accent per node type (concept / preference / goal).
const TYPE_META: Record<NodeType, { badge: string; label: string; accent: string }> = {
  concept: { badge: "C", label: "concept", accent: "#2563eb" },
  preference: { badge: "P", label: "preference", accent: "#7c3aed" },
  goal: { badge: "G", label: "goal", accent: "#0d9488" },
};

export function typeMeta(type: NodeType) {
  return TYPE_META[type] ?? { badge: "?", label: type, accent: "#6b7280" };
}

// Edge rendering convention (concept-map style).
//  prerequisite -> solid, thicker, arrow
//  relates_to   -> dashed
//  part_of      -> solid, thin
export function edgeStyle(type: EdgeType, weight: number): {
  dash?: string;
  width: number;
  animated: boolean;
} {
  const w = Number.isFinite(weight) ? weight : 1;
  switch (type) {
    case "prerequisite":
      return { width: 2 + w * 1.5, animated: false };
    case "relates_to":
      return { dash: "6 4", width: 1.5 + w, animated: false };
    case "part_of":
      return { width: 1, animated: false };
    default:
      return { width: 1.5, animated: false };
  }
}

export const fmtNum = (x: number | null | undefined, digits = 2): string =>
  x == null ? "—" : x.toFixed(digits);

export const fmtTime = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
};
