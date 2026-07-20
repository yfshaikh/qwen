/** Shared types for the voice tutor (push-to-talk audio loop).
 *
 *  Ported from Marfini's `frontend/src/modules/lesson/voice/{types,models}.ts`,
 *  stripped of lesson/model-selection concepts for the Engram console.
 */
import type { ClickyGestureEvent } from './whiteboard/types';

/** Server-emitted whiteboard lifecycle events (camelCased in voice.ts from the
 *  WS snake_case). A `panelId` ties pending -> panel/error together. */
export interface WhiteboardPendingEvent {
  panelId: string;
  intent?: string;
}
export interface WhiteboardPanelEvent {
  panelId: string;
  html: string;
  caption?: string;
  intent?: string;
  /** src-* anchors GLM stamped into the SVG (the tutor's declared points). */
  anchors?: string[];
  model?: string;
}
export interface WhiteboardErrorEvent {
  panelId: string;
  message: string;
  intent?: string;
}

/** Lifecycle phases reported by the backend during a turn. */
export type VoicePhase =
  | 'idle'
  | 'recording'
  | 'transcribing'
  | 'thinking'
  | 'speaking';

/** Cost + token report sent by the server after each turn. `cost` is the
 *  true total across LLM + STT + TTS. Individual breakdowns are present
 *  when the backend has per-stage cost data. */
export interface VoiceUsage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  /** Per-turn cost in USD — the key the backend pipeline actually emits. */
  cost_usd?: number;
  cost?: number;
  llm_cost?: number;
  stt_cost?: number;
  tts_cost?: number;
}

/** One side of the conversation, appended to as the turn unfolds.
 *  Both roles share this shape; the panel renders them as separate bubbles.
 *  `text` accumulates as tokens stream for the assistant role. */
export interface VoiceMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
}

/** Event payloads emitted by `VoiceSession`. Keys mirror the JSON `type`
 *  field on the WebSocket protocol, plus connection lifecycle events
 *  (`open`, `close`) that have no server-side equivalent. */
export interface VoiceEvents {
  open: void;
  close: { code?: number; reason?: string };
  session_started: { sessionId: string };
  status: { phase: VoicePhase };
  transcript: { role: 'user' | 'assistant'; text: string };
  token: { text: string };
  usage: VoiceUsage;
  turn_done: void;
  error: { message: string };
  whiteboard_pending: WhiteboardPendingEvent;
  whiteboard_panel: WhiteboardPanelEvent;
  whiteboard_error: WhiteboardErrorEvent;
  /** A clicky gesture, emitted only when the sentence it belongs to STARTS
   *  playing (held in the blob-audio queue until then). */
  clicky_gesture: ClickyGestureEvent;
  /** True while tutor audio is actually PLAYING on this client — outlives the
   *  server's phase==='speaking'. Drives the cursor's hold-in-place. */
  narrating: { active: boolean };
}
