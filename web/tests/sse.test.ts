import { describe, expect, it } from 'vitest'
import { parseSSE, type SSEFrame } from '../src/sse'

function responseOf(chunks: string[]): Response {
  const enc = new TextEncoder()
  const stream = new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch))
      c.close()
    },
  })
  return new Response(stream)
}

async function collect(res: Response): Promise<SSEFrame[]> {
  const out: SSEFrame[] = []
  for await (const f of parseSSE(res)) out.push(f)
  return out
}

describe('parseSSE', () => {
  it('parses a single event/data frame', async () => {
    const frames = await collect(responseOf(['event: delta\ndata: {"text":"hi"}\n\n']))
    expect(frames).toEqual([{ event: 'delta', data: { text: 'hi' } }])
  })

  it('reassembles a frame split across chunks', async () => {
    const frames = await collect(responseOf(['event: del', 'ta\ndata: {"text', '":"x"}\n\n']))
    expect(frames).toEqual([{ event: 'delta', data: { text: 'x' } }])
  })

  it('parses multiple frames in one chunk and ignores heartbeats', async () => {
    const frames = await collect(
      responseOf([': ping\n\nevent: context\ndata: {"text_block":"m"}\n\nevent: done\ndata: {"reply":"r"}\n\n']),
    )
    expect(frames).toEqual([
      { event: 'context', data: { text_block: 'm' } },
      { event: 'done', data: { reply: 'r' } },
    ])
  })

  it('parses an error frame', async () => {
    const frames = await collect(responseOf(['event: error\ndata: {"detail":"boom"}\n\n']))
    expect(frames).toEqual([{ event: 'error', data: { detail: 'boom' } }])
  })
})
