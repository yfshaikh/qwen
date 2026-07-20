/** Whiteboard state: the list of panels, the draw() action that generates one
 *  via the GLM diagram route, and the clicky gesture the cursor should perform
 *  next. Kept UI-agnostic so App wires the board + cursor to it.
 */
import { useCallback, useRef, useState } from 'react'
import { generatePanel } from './api'
import type { ClickyGestureEvent, GestureKind, WhiteboardPanel } from './types'

let _seq = 0
function nextId(prefix: string): string {
  _seq += 1
  return `${prefix}-${Date.now()}-${_seq}`
}

export interface UseWhiteboardReturn {
  panels: WhiteboardPanel[]
  generating: boolean
  error: string | null
  /** Generate a panel for `intent` and, once its anchors resolve, point the
   *  clicky cursor at the first one. */
  draw: (intent: string) => Promise<void>
  deletePanel: (panelId: string) => void
  clearError: () => void
  /** Fire a clicky gesture at a specific anchor (e.g. from a filmstrip click). */
  fireGesture: (anchor: string, gesture?: GestureKind, note?: string) => void
  /** The gesture the ClickyCursor should currently perform (null when idle). */
  gesture: ClickyGestureEvent | null
  /** Called by ClickyCursor when a gesture finishes. */
  onGestureDone: () => void
}

export function useWhiteboard(learnerId?: string): UseWhiteboardReturn {
  const [panels, setPanels] = useState<WhiteboardPanel[]>([])
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [gesture, setGesture] = useState<ClickyGestureEvent | null>(null)
  const learnerRef = useRef(learnerId)
  learnerRef.current = learnerId

  const fireGesture = useCallback(
    (anchor: string, kind: GestureKind = 'point', note?: string) => {
      setGesture({ gestureId: nextId('g'), anchor, gesture: kind, note })
    },
    [],
  )

  const onGestureDone = useCallback(() => setGesture(null), [])

  const draw = useCallback(async (intent: string) => {
    const trimmed = intent.trim()
    if (!trimmed) return
    setError(null)
    setGenerating(true)
    const pendingId = nextId('pending')
    // Optimistic pending slot so the board shows a loader immediately.
    setPanels((prev) => [...prev, { panelId: pendingId, status: 'pending', intent: trimmed }])
    try {
      const panel = await generatePanel(trimmed, learnerRef.current)
      setPanels((prev) => prev.map((p) => (p.panelId === pendingId ? panel : p)))
      // Point the cursor at the panel's first labelled anchor once it renders;
      // the ClickyCursor waits (bounded) for the iframe bridge to report rects.
      const firstAnchor = panel.anchors?.[0]
      fireGesture(firstAnchor ?? 'panel-current', firstAnchor ? 'circle' : 'point', panel.caption)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to draw that.'
      setError(message)
      setPanels((prev) =>
        prev.map((p) =>
          p.panelId === pendingId ? { ...p, status: 'error' as const } : p,
        ),
      )
    } finally {
      setGenerating(false)
    }
  }, [fireGesture])

  const deletePanel = useCallback((panelId: string) => {
    setPanels((prev) => prev.filter((p) => p.panelId !== panelId))
  }, [])

  const clearError = useCallback(() => setError(null), [])

  return {
    panels,
    generating,
    error,
    draw,
    deletePanel,
    clearError,
    fireGesture,
    gesture,
    onGestureDone,
  }
}
