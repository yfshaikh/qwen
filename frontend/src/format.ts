// Small shared helpers for color / number / date formatting.

/** mastery 0..1 mapped red -> amber -> green. null -> neutral grey. */
export function masteryColor(mastery: number | null): string {
  if (mastery == null) return "#94a3b8";
  const m = clamp01(mastery);
  const red: RGB = [220, 38, 38]; // #dc2626
  const amber: RGB = [245, 158, 11]; // #f59e0b
  const green: RGB = [22, 163, 74]; // #16a34a
  const rgb = m < 0.5 ? lerpRgb(red, amber, m / 0.5) : lerpRgb(amber, green, (m - 0.5) / 0.5);
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
}

/** salience 0..1 mapped to opacity (fading = forgetting). null -> fully visible. */
export function salienceOpacity(salience: number | null): number {
  if (salience == null) return 1;
  return 0.3 + clamp01(salience) * 0.7;
}

/** mastery 0..1 mapped to node diameter in px. null -> mid size. */
export function masteryDiameter(mastery: number | null): number {
  const m = mastery == null ? 0.5 : clamp01(mastery);
  return Math.round(34 + m * 42);
}

export function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

export function pct(v: number | null): string {
  return v == null ? "—" : `${Math.round(clamp01(v) * 100)}%`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

type RGB = [number, number, number];

function lerpRgb(a: RGB, b: RGB, t: number): RGB {
  const u = clamp01(t);
  return [
    Math.round(a[0] + (b[0] - a[0]) * u),
    Math.round(a[1] + (b[1] - a[1]) * u),
    Math.round(a[2] + (b[2] - a[2]) * u),
  ];
}
