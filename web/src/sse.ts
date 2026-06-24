export interface SSEFrame {
  event: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any
}

export async function* parseSSE(res: Response): AsyncGenerator<SSEFrame> {
  if (!res.body) return
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let sep: number
    while ((sep = buf.indexOf('\n\n')) !== -1) {
      const frame = parseFrame(buf.slice(0, sep))
      buf = buf.slice(sep + 2)
      if (frame) yield frame
    }
  }
  const tail = parseFrame(buf)
  if (tail) yield tail
}

function parseFrame(raw: string): SSEFrame | null {
  let event = 'message'
  const data: string[] = []
  for (const line of raw.split('\n')) {
    if (line.startsWith(':')) continue // comment / heartbeat
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trim())
  }
  if (data.length === 0) return null
  return { event, data: JSON.parse(data.join('\n')) }
}
