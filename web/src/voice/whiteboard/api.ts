/** Whiteboard REST client. `generatePanel` hits the backend route that draws an
 *  SVG diagram via the GLM "diagram" role on DashScope (see
 *  src/engram/whiteboard/routes.py). */
import type { WhiteboardPanel } from './types'

interface PanelResponse {
  panel_id: string
  intent: string
  caption: string
  html: string
  anchors: string[]
  model?: string | null
}

export async function generatePanel(
  intent: string,
  learnerId?: string,
): Promise<WhiteboardPanel> {
  const r = await fetch('/whiteboard/panels', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ intent, learner_id: learnerId }),
  })
  if (!r.ok) {
    // 422 = model produced no drawable SVG; surface a friendly message.
    const detail = await r.json().catch(() => null)
    throw new Error(
      (detail && (detail.detail as string)) || `/whiteboard/panels ${r.status}`,
    )
  }
  const d: PanelResponse = await r.json()
  return {
    panelId: d.panel_id,
    status: 'ready',
    html: d.html,
    caption: d.caption,
    intent: d.intent,
    model: d.model ?? undefined,
    anchors: d.anchors,
  }
}
