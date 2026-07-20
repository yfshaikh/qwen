/** Live coordinates of data-clicky anchors *inside* the current whiteboard
 *  panel iframe. Ported verbatim from Marfini (framework-free).
 *
 *  The panel runs a tiny trusted bridge (injected by withCsp) that postMessages
 *  each [data-clicky] element's rect in iframe-local coords. We offset by the
 *  iframe's on-screen box so clicky can point at sub-parts of a rendered panel
 *  (`src-*` anchors), not just the whole panel. The bridge is read-only outbound
 *  and runs in an opaque-origin sandbox, so this never gives panel code a way
 *  into the app — we only ever receive coordinates. */

export interface AnchorRect {
  left: number
  top: number
  width: number
  height: number
  right: number
  bottom: number
}

let iframeEl: HTMLIFrameElement | null = null
const localRects = new Map<string, { x: number; y: number; w: number; h: number }>()
const listeners = new Set<() => void>()

function notify(): void {
  for (const fn of listeners) fn()
}

/** Subscribe to rect updates (a panel finished rendering / resized). Lets a
 *  gesture that arrived BEFORE its panel wait for the anchors instead of
 *  dropping. Returns an unsubscribe. */
export function onPanelRectsChanged(fn: () => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** Called when a panel iframe mounts (el) or unmounts (null). Resets rects so
 *  a swapped panel can't resolve stale coordinates. */
export function registerPanelIframe(el: HTMLIFrameElement | null): void {
  iframeEl = el
  localRects.clear()
  notify()
}

/** Store the rects reported by the current panel's bridge (iframe-local). */
export function setPanelRects(
  rects: Array<{ anchor: string; x: number; y: number; w: number; h: number }>,
): void {
  localRects.clear()
  for (const r of rects) {
    if (typeof r.anchor === 'string') {
      localRects.set(r.anchor, { x: r.x, y: r.y, w: r.w, h: r.h })
    }
  }
  notify()
}

/** src-* anchor names the current panel's bridge has reported. */
export function panelAnchorNames(): string[] {
  return iframeEl ? Array.from(localRects.keys()) : []
}

/** Resolve a src-* anchor to a viewport rect, or null if unknown or the panel
 *  isn't currently mounted. */
export function resolvePanelAnchor(anchor: string): AnchorRect | null {
  const r = localRects.get(anchor)
  if (!r || !iframeEl) return null
  const box = iframeEl.getBoundingClientRect()
  const left = box.left + r.x
  const top = box.top + r.y
  return { left, top, width: r.w, height: r.h, right: left + r.w, bottom: top + r.h }
}
