import { afterEach, describe, expect, it, vi } from 'vitest'
import * as api from '../src/api'

afterEach(() => vi.unstubAllGlobals())

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }) as Response
}

describe('api', () => {
  it('getGraph requests the learner and returns parsed JSON', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ nodes: [], edges: [] }))
    vi.stubGlobal('fetch', fetchMock)
    const g = await api.getGraph('alice')
    expect(fetchMock).toHaveBeenCalledWith('/graph?learner_id=alice')
    expect(g).toEqual({ nodes: [], edges: [] })
  })

  it('consolidate POSTs the learner_id body', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ skipped: false }))
    vi.stubGlobal('fetch', fetchMock)
    await api.consolidate('alice')
    expect(fetchMock).toHaveBeenCalledWith(
      '/consolidate',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ learner_id: 'alice' }) }),
    )
  })

  it('getAudit unwraps rows', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ rows: [{ id: '1', op: 'consolidate' }], cursor: null })))
    const rows = await api.getAudit('alice')
    expect(rows[0].op).toBe('consolidate')
  })

  it('getGraph throws on non-ok', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({}, false, 422)))
    await expect(api.getGraph('')).rejects.toThrow('422')
  })

  it('streamChat yields parsed SSE frames', async () => {
    const enc = new TextEncoder()
    const body = new ReadableStream({
      start(c) {
        c.enqueue(enc.encode('event: delta\ndata: {"text":"hi"}\n\nevent: done\ndata: {"reply":"hi"}\n\n'))
        c.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body) as Response))
    const events: string[] = []
    for await (const f of api.streamChat('alice', [{ role: 'user', content: 'q' }])) events.push(f.event)
    expect(events).toEqual(['delta', 'done'])
  })
})
