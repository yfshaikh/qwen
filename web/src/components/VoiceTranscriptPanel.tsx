/** Panel that shows the live tutor conversation for the voice session.
 *
 *  Scroll behavior: the panel auto-pins to the bottom of the assistant
 *  reply while it streams, so the live word the student hears stays
 *  on screen. If the user scrolls up to read prior text, we DON'T
 *  steal scroll — only re-pin when the user is already near the
 *  bottom (within 60px). Same convention as Discord/Slack chats.
 *
 *  Ported from Marfini's `frontend/src/modules/lesson/voice/VoiceTranscriptPanel.tsx`,
 *  de-dependencied for the Engram console:
 *   - No `model`/`onChangeModel`/`costSoFar`/`onClose` props — no model
 *     dropdown, no running-cost display, no close button.
 *   - `lucide-react` icons swapped for inline SVG/text (no new deps).
 */
import { useEffect, useRef } from 'react'
import type { VoiceMessage, VoicePhase } from '../voice/types'

interface Props {
  phase: VoicePhase
  connected: boolean
  /** Full running conversation, oldest first. The last assistant
   *  message grows as tokens stream in. */
  messages: VoiceMessage[]
  errorMsg: string | null
  /** TTS playback speed multiplier (1.0 = normal). */
  speed: number
  onChangeSpeed: (value: number) => void
  onDismissError: () => void
}

/** Discrete speed presets the user can pick from. OpenAI accepts any
 *  value in [0.25, 4.0] — these are the steps that actually feel useful
 *  in practice (podcast apps use the same set). */
const SPEED_OPTIONS: number[] = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0]

function phaseLabel(phase: VoicePhase): string {
  switch (phase) {
    case 'idle':
      return 'ready'
    case 'recording':
      return 'listening'
    case 'transcribing':
      return 'transcribing'
    case 'thinking':
      return 'thinking'
    case 'speaking':
      return 'speaking'
  }
}

function Spinner() {
  return (
    <svg
      className="size-3 animate-spin"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  )
}

export function VoiceTranscriptPanel({
  phase,
  connected,
  messages,
  errorMsg,
  speed,
  onChangeSpeed,
  onDismissError,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // Length of the last message — including text growth as tokens
  // stream — is what we want to react to for the autoscroll. Using
  // the messages array reference alone wouldn't trigger when only
  // the last message's text mutates (we pass new array each time
  // but conceptually it's the same dependency).
  const tail = messages[messages.length - 1]
  const tailLen = tail ? tail.text.length : 0

  // Auto-pin to bottom while the assistant is streaming, unless the
  // user has scrolled up to read prior content. "Near bottom" =
  // within 60px is the Discord/Slack convention — close enough to
  // count as "still following along."
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.clientHeight - el.scrollTop < 60
    if (nearBottom) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages.length, tailLen])

  const busy = phase === 'transcribing' || phase === 'thinking' || phase === 'speaking'
  const hasExchange = messages.some((m) => m.text.length > 0)

  return (
    <aside className="hidden md:flex w-80 lg:w-96 flex-1 min-h-0 flex-col border-r border-zinc-200 bg-white">
      <header className="border-b border-zinc-200">
        {/* Row 1: status. Compact and stable; nothing here changes
            shape as the conversation progresses. */}
        <div className="flex items-center gap-2 px-4 py-3">
          <span className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-zinc-400">
            {!connected || busy ? (
              <Spinner />
            ) : (
              <span
                className={[
                  'inline-block size-2 rounded-full',
                  phase === 'recording' ? 'bg-red-600' : 'bg-zinc-400',
                ].join(' ')}
              />
            )}
            {connected ? phaseLabel(phase) : 'connecting…'}
          </span>
          <span className="text-sm font-medium text-zinc-800">Tutor</span>
        </div>
        {/* Row 2: speed control. */}
        <div className="flex items-center gap-3 px-4 pb-2 text-xs text-zinc-400">
          <label className="ml-auto flex items-center gap-1.5">
            <span>Speed</span>
            <select
              value={speed}
              onChange={(e) => onChangeSpeed(Number(e.target.value))}
              className="rounded border border-zinc-200 bg-zinc-50 px-1.5 py-0.5 text-xs tabular-nums text-zinc-700 focus:outline-none focus:ring-1 focus:ring-indigo-300"
              title="Tutor speaking speed"
            >
              {SPEED_OPTIONS.map((v) => (
                <option key={v} value={v}>
                  {v.toFixed(2).replace(/\.?0+$/, '')}x
                </option>
              ))}
              {SPEED_OPTIONS.includes(speed) ? null : <option value={speed}>{speed}x</option>}
            </select>
          </label>
        </div>
      </header>

      {errorMsg ? (
        <div className="flex items-start gap-2 border-b border-zinc-200 px-4 py-2 text-xs text-red-600">
          <span className="flex-1">{errorMsg}</span>
          <button
            type="button"
            onClick={onDismissError}
            className="shrink-0 underline hover:no-underline"
          >
            dismiss
          </button>
        </div>
      ) : null}

      <div
        ref={scrollRef}
        className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3 text-sm leading-relaxed"
      >
        {hasExchange ? (
          messages.map((m) =>
            m.text ? (
              <div key={m.id}>
                <div className="mb-0.5 flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-zinc-400">
                  <span>{m.role === 'user' ? 'you' : 'tutor'}</span>
                </div>
                <p
                  className={
                    m.role === 'user'
                      ? 'whitespace-pre-wrap text-zinc-500'
                      : 'whitespace-pre-wrap text-zinc-800'
                  }
                >
                  {m.text}
                </p>
              </div>
            ) : null,
          )
        ) : (
          <p className="text-sm italic text-zinc-400">
            Hold the mic (or spacebar) and ask about what you're studying.
          </p>
        )}
      </div>
    </aside>
  )
}
