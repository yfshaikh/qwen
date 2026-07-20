/** Voice-tutor hook for the Engram console (push-to-talk).
 *
 *  Encapsulates everything the voice overlay needs:
 *   - Opens a `VoiceSession` on mount for the given learner
 *   - Tracks phase, connection, transcripts, errors
 *   - Exposes hold/release callbacks for the mic pill + spacebar
 *   - Tears the session down on unmount
 *
 *  The component just consumes the return value and forwards bits to
 *  the transcript panel and mic pill.
 *
 *  Ported from Marfini's `frontend/src/modules/lesson/voice/useVoiceTutor.ts`,
 *  de-authed (no Supabase session/token) and stripped of lesson gating
 *  and per-turn cost tracking for the Engram console.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { VoiceSession } from './voice';
import type {
  VoicePhase,
  VoiceMessage,
  WhiteboardPanelEvent,
  WhiteboardPendingEvent,
  WhiteboardErrorEvent,
} from './types';
import type { ClickyGestureEvent, WhiteboardPanel } from './whiteboard/types';

/** Pure reducer that advances the whiteboard panel list from a WS event.
 *  Exported for unit testing without a live socket. Ported from Marfini's
 *  reduceWhiteboard — upsert by panelId so a panel whose `pending` was missed
 *  (WS reconnect) still lands instead of being dropped. */
export function reduceWhiteboard(
  panels: WhiteboardPanel[],
  msg:
    | ({ type: 'whiteboard_pending' } & WhiteboardPendingEvent)
    | ({ type: 'whiteboard_panel' } & WhiteboardPanelEvent)
    | ({ type: 'whiteboard_error' } & WhiteboardErrorEvent),
): WhiteboardPanel[] {
  switch (msg.type) {
    case 'whiteboard_pending':
      return [...panels, { panelId: msg.panelId, status: 'pending', intent: msg.intent }];
    case 'whiteboard_panel': {
      const ready: WhiteboardPanel = {
        panelId: msg.panelId,
        status: 'ready',
        html: msg.html,
        caption: msg.caption,
        intent: msg.intent,
        model: msg.model,
        anchors: msg.anchors,
      };
      const exists = panels.some((p) => p.panelId === msg.panelId);
      return exists
        ? panels.map((p) => (p.panelId === msg.panelId ? { ...p, ...ready } : p))
        : [...panels, ready];
    }
    case 'whiteboard_error': {
      const exists = panels.some((p) => p.panelId === msg.panelId);
      if (!exists) {
        return [...panels, { panelId: msg.panelId, status: 'error', intent: msg.intent }];
      }
      return panels.map((p) =>
        p.panelId === msg.panelId
          ? { ...p, status: 'error' as const, intent: msg.intent ?? p.intent }
          : p,
      );
    }
    default:
      return panels;
  }
}

export interface UseVoiceTutorReturn {
  phase: VoicePhase;
  connected: boolean;
  isHolding: boolean;
  /** Full running log of the conversation this session, oldest first.
   *  Appended to, never replaced — so the panel shows the whole
   *  exchange, not just the latest turn. */
  messages: VoiceMessage[];
  errorMsg: string | null;
  /** Hold semantics: pair startHold/endHold via pointerdown/up or keydown/up. */
  startHold: () => void;
  endHold: () => void;
  /** Escape: silence the tutor without opening the mic. */
  cancelPlayback: () => void;
  /** Dismiss the latest error banner. */
  clearError: () => void;
  /** Current TTS playback speed (1.0 = normal). */
  speed: number;
  /** Change TTS speed for subsequent turns. Persists to localStorage. */
  setSpeed: (value: number) => void;
  /** Whiteboard panels the tutor drew this session (oldest first). A pending
   *  slot appears on a `[draw:…]` tag, then patches to ready/error. */
  panels: WhiteboardPanel[];
  /** Latest clicky gesture (null when idle). Newest wins — one cursor, one
   *  gesture at a time. Fired in sync with the sentence it belongs to. */
  activeGesture: ClickyGestureEvent | null;
  /** Mark the active gesture finished (called by the cursor overlay). */
  clearGesture: () => void;
  /** Latest `[show:panel-N]` request — kept separate from activeGesture so a
   *  following draw gesture can't clobber the board switch. `seq` re-fires. */
  showPanelRequest: { anchor: string; seq: number } | null;
  /** True while tutor audio is audibly playing on THIS client. Outlives
   *  phase==='speaking'. */
  narrating: boolean;
}

/** localStorage key for the TTS speed preference. Per-browser, not
 *  per-account — feels right for a "how I like my voice tutor" knob. */
const SPEED_PREF_KEY = 'engram:voice-speed';
const DEFAULT_SPEED = 1.2;

/** Monotonic counter scoped to this module so message ids never collide
 *  across remounts within the same session. Combined with Date.now()
 *  so React doesn't reuse keys after a quick remount + re-fire. */
let _msgIdSeq = 0;
function _nextMsgId(): string {
  _msgIdSeq += 1;
  return `${Date.now()}-${_msgIdSeq}`;
}

export function useVoiceTutor(learnerId: string): UseVoiceTutorReturn {
  const [phase, setPhase] = useState<VoicePhase>('idle');
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState<VoiceMessage[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isHolding, setIsHolding] = useState(false);
  const [panels, setPanels] = useState<WhiteboardPanel[]>([]);
  const [activeGesture, setActiveGesture] = useState<ClickyGestureEvent | null>(null);
  const [showPanelRequest, setShowPanelRequest] =
    useState<{ anchor: string; seq: number } | null>(null);
  const showReqSeqRef = useRef(0);
  const [narrating, setNarrating] = useState(false);
  const [speed, setSpeedState] = useState<number>(() => {
    const raw = window.localStorage.getItem(SPEED_PREF_KEY);
    const parsed = raw ? Number(raw) : NaN;
    return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_SPEED;
  });
  // Ref version so event-handler closures (connect's 'open' listener)
  // can read the latest value without re-running the entire connect
  // effect on every change.
  const speedRef = useRef(speed);
  useEffect(() => {
    speedRef.current = speed;
  }, [speed]);

  // The VoiceSession instance lives in a ref — it's pure side-effects,
  // nothing in the tree reacts to its identity.
  const sessionRef = useRef<VoiceSession | null>(null);
  const holdingRef = useRef(false);

  // ----- Open the session on mount, tear down on unmount -----
  useEffect(() => {
    let cancelled = false;
    let voiceSession: VoiceSession | null = null;

    if (!learnerId) return;

    (async () => {
      try {
        voiceSession = new VoiceSession({ learnerId });

        // Subscribe BEFORE connect() so we don't miss the first 'open'
        // and 'status:idle' events the server sends on accept.
        voiceSession.on('open', () => {
          setConnected(true);
          // Restore the user's saved TTS speed on every (re)connect so
          // the server-side default never leaks into a turn after the
          // user explicitly picked one. Read from ref so changes
          // between mount and WS-open are respected.
          voiceSession?.setSpeed(speedRef.current);
        });
        voiceSession.on('close', ({ code, reason }) => {
          setConnected(false);
          // 1000 (normal) and 1001 (going away) are clean; anything
          // else is worth surfacing so a server-closed WS isn't
          // silently invisible to the user.
          if (code && code !== 1000 && code !== 1001) {
            setErrorMsg(
              reason || `Voice connection closed unexpectedly (${code})`,
            );
          }
        });
        voiceSession.on('status', ({ phase: p }) => setPhase(p));
        voiceSession.on('transcript', ({ role, text }) => {
          if (role !== 'user') return;
          // Each turn appends two messages: the user's final STT
          // transcript, then an empty assistant placeholder that the
          // 'token' handler grows as the model streams its reply.
          // Both stay in the array forever (or until unmount), so the
          // panel shows the full running conversation.
          setMessages((prev) => [
            ...prev,
            { id: _nextMsgId(), role: 'user', text },
            { id: _nextMsgId(), role: 'assistant', text: '' },
          ]);
        });
        voiceSession.on('token', ({ text }) => {
          // Append to the LAST message — by invariant it's the empty
          // assistant placeholder we pushed when the user turn arrived.
          // If the very first event is somehow a token (server bug),
          // fall back to creating a fresh assistant message so the
          // text isn't dropped on the floor.
          setMessages((prev) => {
            if (prev.length === 0 || prev[prev.length - 1].role !== 'assistant') {
              return [
                ...prev,
                { id: _nextMsgId(), role: 'assistant', text },
              ];
            }
            const last = prev[prev.length - 1];
            return [
              ...prev.slice(0, -1),
              { ...last, text: last.text + text },
            ];
          });
        });
        voiceSession.on('error', ({ message }) => setErrorMsg(message));
        voiceSession.on('whiteboard_pending', (e) =>
          setPanels((prev) => reduceWhiteboard(prev, { type: 'whiteboard_pending', ...e })),
        );
        voiceSession.on('whiteboard_panel', (e) =>
          setPanels((prev) => reduceWhiteboard(prev, { type: 'whiteboard_panel', ...e })),
        );
        voiceSession.on('whiteboard_error', (e) =>
          setPanels((prev) => reduceWhiteboard(prev, { type: 'whiteboard_error', ...e })),
        );
        voiceSession.on('narrating', ({ active }) => setNarrating(active));
        voiceSession.on('clicky_gesture', (e) => {
          if (e.gesture === 'show') {
            // Board-switch command — its own slot so a co-flushed draw gesture
            // can't clobber it before the UI acts on the switch.
            showReqSeqRef.current += 1;
            setShowPanelRequest({ anchor: e.anchor, seq: showReqSeqRef.current });
            return;
          }
          setActiveGesture(e); // latest wins — one cursor
        });

        await voiceSession.connect();
        if (cancelled) {
          await voiceSession.disconnect();
          return;
        }
        sessionRef.current = voiceSession;
      } catch (e: unknown) {
        if (cancelled) return;
        const msg =
          e instanceof Error ? e.message : 'Failed to open voice session';
        setErrorMsg(msg);
      }
    })();

    return () => {
      cancelled = true;
      const s = sessionRef.current ?? voiceSession;
      sessionRef.current = null;
      if (s) s.disconnect().catch(() => {});
    };
  }, [learnerId]);

  // ----- Hold handlers (shared by mic button + spacebar) -----
  const startHold = useCallback(() => {
    if (holdingRef.current) return;
    const s = sessionRef.current;
    if (!s) return;
    // Barge-in: cut the tutor off so the user doesn't have to talk
    // over their own AI.
    s.interrupt();
    setPhase('idle');
    holdingRef.current = true;
    setIsHolding(true);
    s.startSpeaking().catch((e: unknown) => {
      holdingRef.current = false;
      setIsHolding(false);
      setErrorMsg(e instanceof Error ? e.message : 'Mic access denied');
    });
  }, []);

  const endHold = useCallback(() => {
    if (!holdingRef.current) return;
    const s = sessionRef.current;
    holdingRef.current = false;
    setIsHolding(false);
    s?.stopSpeaking().catch(() => {
      /* surfaced via WS 'error' event */
    });
  }, []);

  const cancelPlayback = useCallback(() => {
    const s = sessionRef.current;
    if (!s) return;
    s.interrupt();
    setPhase('idle');
  }, []);

  // ----- Spacebar push-to-talk + Escape silence -----
  useEffect(() => {
    const isTyping = (el: EventTarget | null): boolean => {
      const target = el as HTMLElement | null;
      if (!target) return false;
      const tag = target.tagName;
      return (
        tag === 'INPUT' ||
        tag === 'TEXTAREA' ||
        target.isContentEditable === true
      );
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return;
      if (e.code === 'Escape') {
        e.preventDefault();
        cancelPlayback();
        return;
      }
      if (e.code !== 'Space') return;
      // Suppress default page-scroll-on-space ALWAYS, including on
      // auto-repeat keydowns. Returning early on `e.repeat` before
      // preventDefault leaks the repeats through and the page scrolls
      // while the user holds the key.
      e.preventDefault();
      if (e.repeat) return;
      startHold();
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return;
      if (isTyping(e.target)) return;
      e.preventDefault();
      endHold();
    };

    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, [startHold, endHold, cancelPlayback]);

  const clearError = useCallback(() => setErrorMsg(null), []);
  const clearGesture = useCallback(() => setActiveGesture(null), []);

  const setSpeed = useCallback((value: number) => {
    if (!Number.isFinite(value) || value <= 0) return;
    setSpeedState(value);
    window.localStorage.setItem(SPEED_PREF_KEY, String(value));
    // Push to the live session if connected; takes effect on the NEXT
    // turn (not the currently-streaming audio).
    sessionRef.current?.setSpeed(value);
  }, []);

  return {
    phase,
    connected,
    isHolding,
    messages,
    errorMsg,
    startHold,
    endHold,
    cancelPlayback,
    clearError,
    speed,
    setSpeed,
    panels,
    activeGesture,
    clearGesture,
    showPanelRequest,
    narrating,
  };
}
