import { afterEach, describe, expect, it, vi } from 'vitest'
import { withCsp } from './withCsp'
import { generatePanel } from './api'
import {
  panelAnchorNames,
  registerPanelIframe,
  resolvePanelAnchor,
  setPanelRects,
} from './panelAnchors'

describe('withCsp', () => {
  it('wraps a bare SVG fragment in a full sandboxed document with a CSP', () => {
    const doc = withCsp('<svg viewBox="0 0 10 10"><rect data-clicky="src-box"/></svg>', 'p1')
    expect(doc).toMatch(/<!doctype html>/i)
    expect(doc).toContain('Content-Security-Policy')
    // The bridge script is nonce-gated; the CSP only allows that nonce.
    const nonce = doc.match(/nonce="([0-9a-f]+)"/)?.[1]
    expect(nonce).toBeTruthy()
    expect(doc).toContain(`script-src 'nonce-${nonce}'`)
    // The panelId is threaded into the bridge's postMessage payload.
    expect(doc).toContain('"p1"')
    // The model's markup survives intact.
    expect(doc).toContain('data-clicky="src-box"')
  })

  it('mints a fresh nonce each call', () => {
    const a = withCsp('<svg></svg>').match(/nonce="([0-9a-f]+)"/)?.[1]
    const b = withCsp('<svg></svg>').match(/nonce="([0-9a-f]+)"/)?.[1]
    expect(a).not.toBe(b)
  })
})

describe('panelAnchors', () => {
  afterEach(() => registerPanelIframe(null))

  it('resolves a src-* anchor to a viewport rect offset by the iframe box', () => {
    const fakeIframe = {
      getBoundingClientRect: () => ({ left: 100, top: 50 }),
    } as unknown as HTMLIFrameElement
    registerPanelIframe(fakeIframe)
    setPanelRects([{ anchor: 'src-box', x: 10, y: 20, w: 30, h: 40 }])
    expect(panelAnchorNames()).toEqual(['src-box'])
    const rect = resolvePanelAnchor('src-box')
    expect(rect).toEqual({ left: 110, top: 70, width: 30, height: 40, right: 140, bottom: 110 })
  })

  it('returns null when no panel iframe is mounted', () => {
    setPanelRects([{ anchor: 'src-box', x: 0, y: 0, w: 1, h: 1 }])
    registerPanelIframe(null)
    expect(resolvePanelAnchor('src-box')).toBeNull()
  })
})

describe('generatePanel', () => {
  afterEach(() => vi.restoreAllMocks())

  it('POSTs the intent and maps the response to a ready panel', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        panel_id: 'abc',
        intent: 'a neuron',
        caption: 'A neuron',
        html: '<svg><g data-clicky="src-nucleus"/></svg>',
        anchors: ['src-nucleus'],
        model: 'glm-5.2',
      }),
    }))
    vi.stubGlobal('fetch', fetchMock)
    const panel = await generatePanel('a neuron', 'learner-1')
    expect(fetchMock).toHaveBeenCalledWith('/whiteboard/panels', expect.objectContaining({ method: 'POST' }))
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1]
    const body = JSON.parse(init.body as string)
    expect(body).toEqual({ intent: 'a neuron', learner_id: 'learner-1' })
    expect(panel).toMatchObject({ panelId: 'abc', status: 'ready', model: 'glm-5.2', anchors: ['src-nucleus'] })
  })

  it('throws the backend detail on a 422 (no drawable SVG)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 422, json: async () => ({ detail: 'model returned no <svg> markup' }) })),
    )
    await expect(generatePanel('nonsense')).rejects.toThrow(/no <svg>/)
  })
})
