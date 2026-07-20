/** ClickyCursor — the tutor's persistent on-screen pointer.
 *
 *  Ported from Marfini's clicky/ClickyCursor.tsx, rewritten without
 *  framer-motion (the sprite's "aliveness" mood layer is dropped; the core
 *  flight → draw → fade mechanics and the selection→menu morph are preserved).
 *
 *  The cursor idles beside the user's mouse (springy rAF lerp with an offset).
 *  Two things take it over:
 *   - A gesture arcs it to an anchor along a lifted quadratic bezier (WAAPI
 *     offset-path) and draws on it (pulse rings, swept circle, wavy underline,
 *     arrow), then it glides back to the mouse.
 *   - A text selection freezes it and morphs it into a small "Ask about this"
 *     menu; clearing the selection morphs it back.
 *
 *  Layering: pointer-events-none fixed inset-0 z-[25]. Environments without
 *  WAAPI (jsdom) or with prefers-reduced-motion skip the flight and jump
 *  straight to drawing.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { ClickyGestureEvent } from './types'
import { onPanelRectsChanged, resolvePanelAnchor, type AnchorRect } from './panelAnchors'
import { getSelection as getSelectionTarget, onSelectionChanged, requestAsk } from './selectionBus'
import { SelectionMenu } from './SelectionMenu'

/** Where the shape is drawn and the cursor flies to, per gesture kind. */
function targetPoint(rect: AnchorRect, gesture: ClickyGestureEvent['gesture']) {
  const cx = rect.left + rect.width / 2
  const cy = rect.top + rect.height / 2
  switch (gesture) {
    case 'underline':
      return { x: cx, y: rect.bottom - 4 }
    case 'arrow':
      return { x: rect.left - 6, y: cy }
    default:
      return { x: cx, y: cy }
  }
}

/** True for anchors that live inside a whiteboard panel iframe (resolved via
 *  the postMessage bridge, not the parent DOM). */
function isPanelSrc(anchor: string): boolean {
  return anchor.startsWith('src-')
}

/** Resolve a data-clicky anchor to its current viewport rect. Handles both
 *  parent-DOM anchors (panel-*) and panel-source anchors (src-*). */
export function resolveAnchorRect(anchor: string): AnchorRect | null {
  if (isPanelSrc(anchor)) return resolvePanelAnchor(anchor)
  const el = document.querySelector(`[data-clicky="${anchor}"]`)
  return el ? el.getBoundingClientRect() : null
}

const SETTLE_MS = 250
/** How long a src-* gesture waits for its (still-rendering) panel's anchors. */
const PANEL_ANCHOR_WAIT_MS = 20_000
const GLIDE_MS = 600
const HOLD_MS = 2500
const FADE_MS = 400
const IDLE_OFFSET = { x: 22, y: 18 }

type Phase = 'flight' | 'draw' | 'fade'
type ClickyMode = 'hidden' | 'gesture' | 'menu' | 'frozen' | 'follow'

interface Scene {
  key: string
  gesture: ClickyGestureEvent
  rect: { left: number; top: number; width: number; height: number; bottom: number }
  point: { x: number; y: number }
  from: { x: number; y: number }
  phase: Phase
}

interface Props {
  /** The cursor exists (idles + reacts) only while true. */
  active: boolean
  /** Tutor is narrating: hold wherever it is instead of chasing the mouse. */
  speaking?: boolean
  gesture: ClickyGestureEvent | null
  onDone: () => void
}

export function ClickyCursor({ active, speaking = false, gesture, onDone }: Props) {
  const [scene, setScene] = useState<Scene | null>(null)
  const [menuText, setMenuText] = useState<string | null>(null)
  const cursorRef = useRef<HTMLDivElement | null>(null)
  const posRef = useRef<{ x: number; y: number } | null>(null)
  const mouseRef = useRef<{ x: number; y: number } | null>(null)
  const sceneRef = useRef<Scene | null>(null)
  sceneRef.current = scene
  const timersRef = useRef<number[]>([])
  const onDoneRef = useRef(onDone)
  useEffect(() => {
    onDoneRef.current = onDone
  }, [onDone])

  const mode: ClickyMode = !active
    ? 'hidden'
    : scene
      ? 'gesture'
      : menuText !== null
        ? 'menu'
        : speaking
          ? 'frozen'
          : 'follow'
  const modeRef = useRef(mode)
  modeRef.current = mode

  const clearTimers = useCallback(() => {
    for (const t of timersRef.current) window.clearTimeout(t)
    timersRef.current = []
  }, [])
  const after = useCallback((ms: number, fn: () => void) => {
    timersRef.current.push(window.setTimeout(fn, ms))
  }, [])

  // ---- Idle: follow the user's mouse with a springy lag ----
  useEffect(() => {
    if (!active) return
    const onMove = (e: MouseEvent) => {
      mouseRef.current = { x: e.clientX, y: e.clientY }
    }
    window.addEventListener('mousemove', onMove, { passive: true })

    let raf = 0
    const tick = () => {
      raf = window.requestAnimationFrame(tick)
      const el = cursorRef.current
      if (!el) return
      const dockSpot = { x: window.innerWidth / 2 + 64, y: window.innerHeight - 84 }
      let target: { x: number; y: number }
      switch (modeRef.current) {
        case 'gesture': {
          const s = sceneRef.current!
          if (s.phase === 'flight') return // WAAPI owns the element mid-flight
          target = s.point
          break
        }
        case 'menu':
        case 'frozen':
          target = posRef.current ?? dockSpot
          break
        default:
          target = mouseRef.current
            ? { x: mouseRef.current.x + IDLE_OFFSET.x, y: mouseRef.current.y + IDLE_OFFSET.y }
            : dockSpot
      }
      const pos = posRef.current ?? target
      const next = { x: pos.x + (target.x - pos.x) * 0.18, y: pos.y + (target.y - pos.y) * 0.18 }
      posRef.current = next
      el.style.transform = `translate3d(${next.x}px, ${next.y}px, 0)`
    }
    raf = window.requestAnimationFrame(tick)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.cancelAnimationFrame(raf)
    }
  }, [active])

  // ---- Gesture driver: settle → flight → draw → fade → back to idle ----
  useEffect(() => {
    if (!gesture) return
    clearTimers()
    let unsubRects: (() => void) | null = null

    const begin = () => {
      after(SETTLE_MS, () => {
        const r = resolveAnchorRect(gesture.anchor)
        if (!r) {
          setScene(null)
          onDoneRef.current()
          return
        }
        const point = targetPoint(r, gesture.gesture)
        const from = posRef.current ?? { x: window.innerWidth / 2, y: window.innerHeight - 80 }
        setScene({
          key: gesture.gestureId,
          gesture,
          rect: { left: r.left, top: r.top, width: r.width, height: r.height, bottom: r.bottom },
          point,
          from,
          phase: 'flight',
        })
      })
    }

    if (resolveAnchorRect(gesture.anchor)) {
      begin()
    } else if (isPanelSrc(gesture.anchor)) {
      // The panel may still be rendering when the gesture arrives — wait
      // (bounded) for its bridge to report rects instead of dropping.
      unsubRects = onPanelRectsChanged(() => {
        if (resolveAnchorRect(gesture.anchor)) {
          unsubRects?.()
          unsubRects = null
          begin()
        }
      })
      after(PANEL_ANCHOR_WAIT_MS, () => {
        if (unsubRects) {
          unsubRects()
          unsubRects = null
          onDoneRef.current()
        }
      })
    } else {
      setScene(null)
      onDoneRef.current()
      return
    }

    return () => {
      unsubRects?.()
      clearTimers()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gesture?.gestureId])

  // ---- Selection → menu ----
  useEffect(() => {
    const sync = () => {
      const sel = getSelectionTarget()
      setMenuText(sel ? sel.text : null)
    }
    const unsub = onSelectionChanged(sync)
    sync()
    return unsub
  }, [])

  // ---- Flight: WAAPI offset-path arc; skipped without WAAPI/reduced motion ----
  useEffect(() => {
    if (!scene || scene.phase !== 'flight') return
    const el = cursorRef.current
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches

    const arrive = () => {
      posRef.current = scene.point
      if (el) {
        el.style.offsetPath = ''
        el.style.offsetRotate = ''
        el.style.transform = `translate3d(${scene.point.x}px, ${scene.point.y}px, 0)`
      }
      setScene((s) => (s && s.key === scene.key ? { ...s, phase: 'draw' } : s))
    }

    if (!el || typeof el.animate !== 'function' || reduced) {
      arrive()
      return
    }
    const { from, point } = scene
    const mx = (from.x + point.x) / 2
    const my = Math.min(from.y, point.y) - 120
    el.style.transform = ''
    el.style.offsetPath = `path("M ${from.x} ${from.y} Q ${mx} ${my} ${point.x} ${point.y}")`
    el.style.offsetRotate = 'auto 45deg'
    const anim = el.animate(
      [{ offsetDistance: '0%' }, { offsetDistance: '100%' }],
      { duration: GLIDE_MS, easing: 'cubic-bezier(0.4, 0, 0.2, 1)', fill: 'forwards' },
    )
    anim.finished.then(arrive).catch(() => {
      /* cancelled by a newer gesture */
    })
    return () => anim.cancel()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene?.key, scene?.phase])

  // ---- Draw → hold → fade; scroll/resize ends the hold early ----
  useEffect(() => {
    if (!scene || scene.phase !== 'draw') return
    const fade = () => setScene((s) => (s && s.key === scene.key ? { ...s, phase: 'fade' } : s))
    after(HOLD_MS, fade)
    window.addEventListener('scroll', fade, { passive: true, once: true })
    window.addEventListener('resize', fade, { once: true })
    return () => {
      window.removeEventListener('scroll', fade)
      window.removeEventListener('resize', fade)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene?.key, scene?.phase])

  useEffect(() => {
    if (!scene || scene.phase !== 'fade') return
    after(FADE_MS, () => {
      setScene(null)
      onDoneRef.current()
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene?.key, scene?.phase])

  if (mode === 'hidden') return null

  const drawing = scene && scene.phase !== 'flight' ? scene : null
  const pad = 8
  const showMenu = mode === 'menu'

  return (
    <div data-testid="clicky-cursor" className="pointer-events-none fixed inset-0 z-[25] text-indigo-600">
      <style>{`
        @keyframes clicky-sweep { to { stroke-dashoffset: 0; } }
        @keyframes clicky-pulse {
          0% { transform: scale(0.4); opacity: 0.9; }
          100% { transform: scale(1.6); opacity: 0; }
        }
        @keyframes clicky-pop { from { opacity: 0; } to { opacity: 1; } }
      `}</style>

      <div ref={cursorRef} className="absolute left-0 top-0 will-change-transform">
        {/* Pointer — shrinks/fades into its tip as the menu takes over. */}
        <div
          aria-hidden
          className="absolute left-0 top-0 drop-shadow-[0_2px_6px_rgba(0,0,0,0.4)]"
          style={{
            transformOrigin: '3px 3px',
            transform: showMenu ? 'scale(0.18)' : 'scale(1)',
            opacity: showMenu ? 0 : 1,
            transition: 'transform 180ms cubic-bezier(0.34,1.56,0.64,1), opacity 160ms ease',
          }}
        >
          <svg width="22" height="22" viewBox="0 0 22 22">
            <polygon points="2,2 20,9 11,12 8,21" fill="currentColor" stroke="white" strokeWidth="1.2" />
          </svg>
        </div>

        <SelectionMenu open={showMenu} text={menuText ?? ''} onAsk={requestAsk} />
      </div>

      {drawing && (
        <div
          data-testid="clicky-gesture-layer"
          className={`absolute inset-0 transition-opacity duration-300 ${
            drawing.phase === 'fade' ? 'opacity-0' : 'opacity-100'
          }`}
        >
          <svg className="absolute inset-0 h-full w-full" style={{ animation: 'clicky-pop 150ms ease-out' }}>
            {drawing.gesture.gesture === 'circle' && (
              <ellipse
                cx={drawing.rect.left + drawing.rect.width / 2}
                cy={drawing.rect.top + drawing.rect.height / 2}
                rx={drawing.rect.width / 2 + pad}
                ry={drawing.rect.height / 2 + pad}
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                pathLength={100}
                strokeDasharray={100}
                strokeDashoffset={100}
                style={{ animation: 'clicky-sweep 500ms ease-in-out forwards' }}
              />
            )}
            {drawing.gesture.gesture === 'underline' && (
              <path
                d={`M ${drawing.rect.left + 4} ${drawing.rect.bottom + 4} q ${drawing.rect.width / 4} 6 ${drawing.rect.width / 2} 0 t ${drawing.rect.width / 2 - 8} 0`}
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                pathLength={100}
                strokeDasharray={100}
                strokeDashoffset={100}
                style={{ animation: 'clicky-sweep 450ms ease-in-out forwards' }}
              />
            )}
            {drawing.gesture.gesture === 'arrow' && (
              <g>
                <path
                  d={`M ${drawing.point.x - 70} ${drawing.point.y - 50} Q ${drawing.point.x - 60} ${drawing.point.y} ${drawing.point.x - 12} ${drawing.point.y}`}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  pathLength={100}
                  strokeDasharray={100}
                  strokeDashoffset={100}
                  style={{ animation: 'clicky-sweep 400ms ease-in-out forwards' }}
                />
                <polygon
                  points={`${drawing.point.x - 2},${drawing.point.y} ${drawing.point.x - 14},${drawing.point.y - 6} ${drawing.point.x - 14},${drawing.point.y + 6}`}
                  fill="currentColor"
                  style={{ animation: 'clicky-pop 200ms ease-out 300ms both' }}
                />
              </g>
            )}
            {drawing.gesture.gesture === 'point' && (
              <g>
                {[0, 1, 2].map((i) => (
                  <circle
                    key={i}
                    cx={drawing.point.x}
                    cy={drawing.point.y}
                    r={18}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    style={{
                      transformOrigin: `${drawing.point.x}px ${drawing.point.y}px`,
                      animation: `clicky-pulse 1.2s ease-out ${i * 0.35}s infinite`,
                    }}
                  />
                ))}
              </g>
            )}
          </svg>

          {drawing.gesture.note && (
            <div
              className="absolute -translate-x-1/2 rounded-full bg-indigo-600 px-2.5 py-0.5 text-[11px] font-medium text-white shadow"
              style={{
                left: drawing.rect.left + drawing.rect.width / 2,
                top: Math.max(8, drawing.rect.top - 30),
                animation: 'clicky-pop 200ms ease-out 250ms both',
              }}
            >
              {drawing.gesture.note}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
