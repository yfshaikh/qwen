import { describe, expect, it } from 'vitest'
import { reduceWhiteboard } from './useVoiceTutor'
import type { WhiteboardPanel } from './whiteboard/types'

describe('reduceWhiteboard', () => {
  it('appends a pending slot on whiteboard_pending', () => {
    const out = reduceWhiteboard([], { type: 'whiteboard_pending', panelId: 'p1', intent: 'nmos' })
    expect(out).toEqual([{ panelId: 'p1', status: 'pending', intent: 'nmos' }])
  })

  it('patches the pending slot to ready on whiteboard_panel', () => {
    const start: WhiteboardPanel[] = [{ panelId: 'p1', status: 'pending', intent: 'nmos' }]
    const out = reduceWhiteboard(start, {
      type: 'whiteboard_panel',
      panelId: 'p1',
      html: '<svg/>',
      caption: 'NMOS',
      anchors: ['src-gate'],
      model: 'glm-4.6',
    })
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({
      panelId: 'p1',
      status: 'ready',
      html: '<svg/>',
      caption: 'NMOS',
      anchors: ['src-gate'],
      model: 'glm-4.6',
    })
  })

  it('appends (upsert) a panel whose pending slot was never seen', () => {
    const out = reduceWhiteboard([], { type: 'whiteboard_panel', panelId: 'p9', html: '<svg/>' })
    expect(out).toEqual([{ panelId: 'p9', status: 'ready', html: '<svg/>', caption: undefined, intent: undefined, model: undefined, anchors: undefined }])
  })

  it('marks the slot errored on whiteboard_error', () => {
    const start: WhiteboardPanel[] = [{ panelId: 'p1', status: 'pending', intent: 'nmos' }]
    const out = reduceWhiteboard(start, { type: 'whiteboard_error', panelId: 'p1', message: 'boom' })
    expect(out[0].status).toBe('error')
    expect(out[0].intent).toBe('nmos') // preserved
  })
})
