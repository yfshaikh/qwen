/** The whiteboard board: a draw prompt, a sandboxed panel canvas, and a
 *  filmstrip of generated panels. Ported from Marfini's Whiteboard.tsx,
 *  de-authed (no Supabase panel persistence) and restyled to the console's
 *  zinc/indigo palette (no lucide/design-token dependencies).
 *
 *  The generated SVG runs inside an opaque-origin iframe (withCsp); a trusted
 *  nonce-gated bridge postMessages each [data-clicky] rect back so the clicky
 *  cursor can point at sub-parts of the drawing.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { WhiteboardPanel } from './types'
import { withCsp } from './withCsp'
import { registerPanelIframe, setPanelRects } from './panelAnchors'

const LOADER_LINES = [
  'Sharpening the pencils…',
  'Sketching the layout…',
  'Inking the labels…',
  'Adding finishing touches…',
]

function PanelLoader({ intent }: { intent?: string }) {
  const [lineIdx, setLineIdx] = useState(0)
  useEffect(() => {
    const id = window.setInterval(() => setLineIdx((i) => (i + 1) % LOADER_LINES.length), 1600)
    return () => window.clearInterval(id)
  }, [])
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
      <svg viewBox="0 0 120 60" className="w-32 text-indigo-500" aria-hidden="true">
        <path
          d="M8 44 Q 24 10, 40 32 T 72 30 Q 84 16, 96 34 T 112 28"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray="160"
          strokeDashoffset="160"
          className="animate-[wb-draw_1.8s_ease-in-out_infinite]"
        />
        <style>{`@keyframes wb-draw { 0% { stroke-dashoffset: 160; } 55% { stroke-dashoffset: 0; } 100% { stroke-dashoffset: -160; } }`}</style>
      </svg>
      <div className="space-y-1">
        <p className="text-sm text-zinc-700" aria-live="polite">
          {LOADER_LINES[lineIdx]}
        </p>
        {intent && <p className="line-clamp-2 text-xs italic text-zinc-400">“{intent}”</p>}
      </div>
    </div>
  )
}

function PanelError({ intent }: { intent?: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <svg viewBox="0 0 120 60" className="w-28 text-zinc-300" aria-hidden="true">
        <path d="M8 40 Q 24 14, 40 34 T 68 32" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeDasharray="4 7" />
        <text x="86" y="42" fontSize="26" fill="currentColor">?</text>
      </svg>
      <div className="space-y-1">
        <p className="text-sm text-zinc-700">That sketch didn’t come out.</p>
        {intent && <p className="line-clamp-2 text-xs italic text-zinc-400">“{intent}”</p>}
        <p className="text-xs text-zinc-400">Ask again to retry the drawing.</p>
      </div>
    </div>
  )
}

function EmptyBoard() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
      <svg viewBox="0 0 120 60" className="w-32 text-zinc-300" aria-hidden="true">
        <rect x="10" y="8" width="100" height="44" rx="4" fill="none" stroke="currentColor" strokeWidth="2" />
        <path d="M30 44 L 48 24 L 62 36 L 78 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeDasharray="3 5" />
      </svg>
      <div className="max-w-sm space-y-1">
        <p className="text-sm text-zinc-700">The board is clean.</p>
        <p className="text-xs text-zinc-400">
          Type what you want drawn — “show me a right triangle with the sides labelled”.
        </p>
      </div>
    </div>
  )
}

interface WhiteboardProps {
  panels: WhiteboardPanel[]
  generating: boolean
  error: string | null
  onDraw: (intent: string) => void
  onDelete: (panelId: string) => void
  onExit: () => void
  /** Point the clicky cursor at an anchor (used by "Point" on the current panel). */
  onPoint?: (anchor: string) => void
}

export function Whiteboard({ panels, generating, error, onDraw, onDelete, onExit, onPoint }: WhiteboardProps) {
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [intent, setIntent] = useState('')
  const iframeRef = useRef<HTMLIFrameElement | null>(null)

  // Stable ref callback — an inline one re-invokes (null, then el) on every
  // parent re-render, wiping the panel's anchor rects mid-gesture.
  const setIframe = useCallback((el: HTMLIFrameElement | null) => {
    iframeRef.current = el
    registerPanelIframe(el)
  }, [])

  // Receive [data-clicky] rects from the current panel's bridge. Trust only
  // messages from our own iframe's window.
  useEffect(() => {
    const onMsg = (e: MessageEvent) => {
      if (e.source !== iframeRef.current?.contentWindow) return
      const d = e.data as { type?: string; rects?: unknown }
      if (d?.type === 'clicky-rects' && Array.isArray(d.rects)) {
        setPanelRects(d.rects as Parameters<typeof setPanelRects>[0])
      }
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [])

  // Newest panel becomes current when it arrives.
  useEffect(() => {
    if (panels.length) setCurrentId(panels[panels.length - 1].panelId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panels.length])

  const current = panels.find((p) => p.panelId === currentId) ?? panels[panels.length - 1]

  // Memoized per panel: withCsp mints a fresh nonce each call, so an inline
  // call would reload the iframe on every parent re-render (a visible flicker).
  const currentSrcDoc = useMemo(
    () =>
      current?.status === 'ready' && current.html ? withCsp(current.html, current.panelId) : null,
    [current?.status, current?.html, current?.panelId],
  )
  const currentIndex = current ? panels.findIndex((p) => p.panelId === current.panelId) : -1

  const submit = () => {
    const t = intent.trim()
    if (!t || generating) return
    onDraw(t)
    setIntent('')
  }

  return (
    <div className="flex h-full w-full flex-col bg-white">
      {/* Header: draw prompt + collapse */}
      <header className="flex shrink-0 items-center gap-2 border-b border-zinc-200 bg-white px-3 py-2">
        <span className="shrink-0 text-xs font-semibold text-zinc-700">Whiteboard</span>
        <input
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit()
          }}
          placeholder="Ask the tutor to draw a diagram…"
          className="min-w-0 flex-1 rounded-lg border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-xs text-zinc-800 placeholder:text-zinc-400 focus:border-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-200"
        />
        <button
          type="button"
          onClick={submit}
          disabled={generating || !intent.trim()}
          className="shrink-0 rounded-lg bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white transition hover:bg-indigo-500 disabled:opacity-40"
        >
          {generating ? 'Drawing…' : 'Draw'}
        </button>
        {current?.status === 'ready' && current.anchors && current.anchors.length > 0 && onPoint && (
          <button
            type="button"
            onClick={() => onPoint(current.anchors![0])}
            className="shrink-0 rounded-lg border border-zinc-200 px-2.5 py-1 text-xs font-medium text-zinc-600 transition hover:bg-zinc-50"
            title="Point the cursor at the first labelled part"
          >
            Point
          </button>
        )}
        <button
          type="button"
          onClick={onExit}
          className="shrink-0 rounded-lg border border-zinc-200 px-2.5 py-1 text-xs font-medium text-zinc-600 transition hover:bg-zinc-50"
        >
          Close
        </button>
      </header>

      {error && (
        <div className="border-b border-amber-100 bg-amber-50 px-3 py-1.5 text-xs text-amber-800">
          {error}
        </div>
      )}

      {/* Canvas */}
      <div data-clicky="panel-current" className="min-h-0 flex-1 overflow-hidden">
        {!current ? (
          <EmptyBoard />
        ) : currentSrcDoc ? (
          <iframe
            key={current.panelId}
            ref={setIframe}
            title={current.caption || 'whiteboard panel'}
            srcDoc={currentSrcDoc}
            // allow-scripts WITHOUT allow-same-origin: the panel runs our
            // nonce-gated bridge in an opaque origin — scripts execute but
            // cannot reach the parent DOM. Never add allow-same-origin.
            sandbox="allow-scripts"
            className="h-full w-full border-0"
          />
        ) : current.status === 'error' ? (
          <PanelError intent={current.intent} />
        ) : (
          <PanelLoader intent={current.intent} />
        )}
      </div>

      {/* Filmstrip */}
      {panels.length > 0 && (
        <div className="flex items-center gap-2 border-t border-zinc-200 px-3 py-2">
          <div className="flex flex-1 gap-2 overflow-x-auto">
            {panels.map((p, i) => (
              <button
                key={p.panelId}
                type="button"
                data-clicky={`panel-${i + 1}`}
                onClick={() => setCurrentId(p.panelId)}
                className={`flex h-12 w-24 shrink-0 flex-col items-center justify-center gap-0.5 rounded border px-1 text-xs transition ${
                  p.panelId === current?.panelId
                    ? 'border-indigo-400 bg-indigo-50'
                    : 'border-zinc-200 hover:border-zinc-300'
                }`}
                title={p.caption || p.intent || p.status}
              >
                <span className="text-[10px] text-zinc-400">#{i + 1}</span>
                <span className="max-w-full truncate text-[11px] text-zinc-700">
                  {p.status === 'ready' ? p.caption || 'Untitled' : p.status === 'error' ? '⚠ failed' : 'drawing…'}
                </span>
              </button>
            ))}
          </div>
          {current?.status === 'ready' && (
            <div className="flex shrink-0 items-center gap-2 px-1 text-[11px] text-zinc-400">
              {current.model && <span className="font-medium">{current.model}</span>}
              <button
                type="button"
                onClick={() => onDelete(current.panelId)}
                className="text-zinc-400 transition hover:text-red-500"
                title="Delete this panel"
              >
                Delete
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
