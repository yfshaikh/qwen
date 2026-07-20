/** The blob-queue gesture↔audio sync: a clicky_gesture arrives ahead of its
 *  sentence's audio; it must be held, attached to the NEXT audio item, and
 *  fired only when that item STARTS playing (drainPlayback). A later gesture
 *  must wait for its own audio. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { VoiceSession } from './voice'
import type { ClickyGestureEvent } from './whiteboard/types'

// Minimal audio-element stub that records its event listeners so a test can
// fire 'ended' to advance the queue. play() resolves (jsdom has no real audio).
function makeAudioStub() {
  const handlers: Record<string, Array<() => void>> = {}
  return {
    playbackRate: 1,
    src: '',
    currentTime: 0,
    play: () => Promise.resolve(),
    pause: () => {},
    removeAttribute: () => {},
    load: () => {},
    addEventListener: (ev: string, fn: () => void) => {
      ;(handlers[ev] ||= []).push(fn)
    },
    fire: (ev: string) => (handlers[ev] || []).forEach((fn) => fn()),
  }
}

describe('VoiceSession gesture↔audio sync', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', {
      createObjectURL: () => 'blob:x',
      revokeObjectURL: () => {},
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  function setup() {
    const vs = new VoiceSession({ learnerId: 'a' })
    const audio = makeAudioStub()
    ;(vs as unknown as { audioEl: unknown }).audioEl = audio
    ;(vs as unknown as { setupPlayback: () => void }).setupPlayback()
    const fired: string[] = []
    vs.on('clicky_gesture', (e: ClickyGestureEvent) => fired.push(`${e.gesture}:${e.anchor}`))
    const handle = (vs as unknown as { handleMessage: (e: unknown) => void }).handleMessage.bind(vs)
    return { vs, audio, fired, handle }
  }

  const gestureFrame = (anchor: string, gesture = 'point') => ({
    data: JSON.stringify({ type: 'clicky_gesture', gesture_id: anchor, anchor, gesture }),
  })
  const audioFrame = () => ({ data: new ArrayBuffer(4) })

  it('holds a gesture on receipt and fires it when its audio starts playing', () => {
    const { fired, handle } = setup()
    handle(gestureFrame('src-gate'))
    expect(fired).toEqual([]) // NOT emitted on receipt — it arrived ahead of audio
    handle(audioFrame()) // sentence audio arrives → drainPlayback starts it
    expect(fired).toEqual(['point:src-gate']) // fires as the sentence starts
  })

  it('makes a later gesture wait for its own sentence audio', () => {
    const { audio, fired, handle } = setup()
    handle(gestureFrame('src-gate'))
    handle(audioFrame()) // A1 starts → gate fires
    handle(gestureFrame('src-channel', 'circle')) // arrives while A1 plays
    handle(audioFrame()) // A2 queued behind A1 — channel must NOT fire yet
    expect(fired).toEqual(['point:src-gate'])
    audio.fire('ended') // A1 done → A2 starts → channel fires now
    expect(fired).toEqual(['point:src-gate', 'circle:src-channel'])
  })

  it('flushes a trailing gesture with no following audio on turn_done', () => {
    const { fired, handle } = setup()
    handle(gestureFrame('panel-current', 'circle'))
    handle({ data: JSON.stringify({ type: 'turn_done' }) })
    expect(fired).toEqual(['circle:panel-current'])
  })

  it('emits whiteboard_panel immediately (camelCased) on receipt', () => {
    const { vs, handle } = setup()
    const panels: string[] = []
    vs.on('whiteboard_panel', (e) => panels.push(`${e.panelId}:${e.anchors?.join(',')}`))
    handle({
      data: JSON.stringify({
        type: 'whiteboard_panel',
        panel_id: 'p1',
        html: '<svg/>',
        anchors: ['src-gate'],
      }),
    })
    expect(panels).toEqual(['p1:src-gate'])
  })
})
