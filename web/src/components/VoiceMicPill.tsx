/** Floating push-to-talk pill, anchored bottom-center of the console view.
 *
 *  Always visible, small and glass — designed so the user can ignore
 *  it while reading while studying and notice it the moment they want to ask.
 *
 *  Pointer capture: setPointerCapture on pointerdown keeps the up
 *  event arriving on the button even if the cursor drifts off mid-hold
 *  (common with trackpad tap-and-hold).
 *
 *  Ported from Marfini's `frontend/src/modules/lesson/voice/VoiceMicPill.tsx`,
 *  with `lucide-react` icons swapped for an inline emoji/SVG (no new deps).
 */
import type { VoicePhase } from '../voice/types'

interface Props {
  phase: VoicePhase
  connected: boolean
  isHolding: boolean
  onHoldStart: () => void
  onHoldEnd: () => void
}

function phaseLabel(phase: VoicePhase): string {
  switch (phase) {
    case 'idle':
      return 'hold space'
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

export function VoiceMicPill({ phase, connected, isHolding, onHoldStart, onHoldEnd }: Props) {
  const canStart = connected && (phase === 'idle' || phase === 'recording')
  const busy = phase === 'transcribing' || phase === 'thinking' || phase === 'speaking'
  const accentText = !connected
    ? 'text-zinc-400'
    : phase === 'recording'
      ? 'text-red-600'
      : busy
        ? 'text-indigo-600'
        : 'text-zinc-400'

  return (
    <div className="pointer-events-none fixed bottom-4 left-1/2 -translate-x-1/2 z-30">
      <div className="pointer-events-auto flex items-center gap-3 rounded-full bg-white/85 px-3 py-2 shadow-lg ring-1 ring-zinc-200 backdrop-blur">
        <span
          className={`flex select-none items-center gap-1.5 text-xs uppercase tracking-wider ${accentText}`}
        >
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
        <button
          type="button"
          disabled={!canStart}
          onPointerDown={(e) => {
            if (!canStart) return
            ;(e.currentTarget as HTMLButtonElement).setPointerCapture(e.pointerId)
            onHoldStart()
          }}
          onPointerUp={(e) => {
            try {
              ;(e.currentTarget as HTMLButtonElement).releasePointerCapture(e.pointerId)
            } catch {
              /* already released */
            }
            onHoldEnd()
          }}
          onPointerCancel={onHoldEnd}
          className={[
            'grid h-9 w-9 shrink-0 select-none place-items-center rounded-full transition',
            isHolding
              ? 'scale-110 bg-red-600 text-white shadow-md'
              : canStart
                ? 'bg-indigo-600 text-white hover:bg-indigo-700'
                : 'cursor-not-allowed bg-zinc-100 text-zinc-400 opacity-50',
          ].join(' ')}
          aria-pressed={isHolding}
          aria-label="Hold to talk to the tutor"
          title={isHolding ? 'Release to send' : 'Hold to talk (or press space)'}
        >
          <span className="text-base leading-none" aria-hidden="true">
            🎙️
          </span>
        </button>
      </div>
    </div>
  )
}
