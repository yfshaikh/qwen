/** Types for the whiteboard + clicky feature, ported from Marfini's
 *  lesson/voice module and trimmed for the Engram console (no lesson/auth).
 */

/** A rendered (or in-flight) whiteboard panel. `html` is the model's SVG
 *  markup; the board sandboxes it in an opaque-origin iframe. */
export interface WhiteboardPanel {
  panelId: string
  status: 'pending' | 'ready' | 'error'
  /** SVG markup, present once status === 'ready'. */
  html?: string
  caption?: string
  intent?: string
  model?: string
  anchors?: string[]
}

/** The clicky cursor's gesture verbs. `point`/`circle`/`underline`/`arrow`
 *  are drawings the cursor performs on an anchor; `show` is not a drawing — it
 *  asks the board to switch to an earlier panel (routed to showPanelRequest,
 *  never reaches the cursor). */
export const GESTURE_KINDS = ['point', 'circle', 'underline', 'arrow', 'show'] as const
export type GestureKind = (typeof GESTURE_KINDS)[number]

/** A cursor gesture: fly to `anchor` (a data-clicky name) and draw `gesture`.
 *  `src-*` anchors live inside a rendered panel iframe. */
export interface ClickyGestureEvent {
  gestureId: string
  anchor: string
  gesture: GestureKind
  note?: string
}
