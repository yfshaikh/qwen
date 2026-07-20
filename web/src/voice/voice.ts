/** Voice tutor client: WebSocket + MediaRecorder + queued audio playback.
 *
 *  Wraps three browser APIs that don't naturally compose:
 *
 *  - `WebSocket` to talk to `/voice?learner_id=<id>`. Auth is just the
 *    learner id as a query param — no JWT, no subprotocol. Sessions are
 *    lazy: opening the WS does NOT create a voice_sessions row. The server
 *    only persists one when the user first pushes to talk, and reports the
 *    id back via a `session_started` message.
 *
 *  - `MediaRecorder` to capture the student's audio between hotkey press
 *    (`startSpeaking`) and release (`stopSpeaking`). We send the `'end'`
 *    JSON message only after `MediaRecorder` flushes its final `dataavailable`
 *    event — otherwise the server runs STT before the last 150ms of audio
 *    arrives.
 *
 *  - A Blob-URL playback queue. The server sends each sentence's TTS as ONE
 *    complete audio file (one WS binary message = one file — the WS preserves
 *    message boundaries). We queue the files and play them one at a time
 *    through a single `<audio>` element, advancing on `ended`. Format-agnostic
 *    (the audio element decodes WAV/MP3/etc natively) — which is why this
 *    replaced the old MP3-only `MediaSource` path when TTS moved to DashScope's
 *    WAV output.
 *
 *  Event delivery is a small typed pub-sub — no need to pull in an event
 *  emitter library. Callers do `session.on('transcript', cb)` and get
 *  back an unsubscribe.
 */

import type { VoiceEvents } from './types';
import type { ClickyGestureEvent } from './whiteboard/types';

type Listener<K extends keyof VoiceEvents> = (data: VoiceEvents[K]) => void;

interface VoiceSessionOptions {
  /** Learner id this voice tutor is bound to. The server uses it to
   *  scope context and as the FK when it lazy-inserts the voice_sessions
   *  row on first push-to-talk. */
  learnerId: string;
  /** Optional override of the HTTP API base, used to derive the WS URL.
   *  Default: `import.meta.env.VITE_API_BASE ?? ''`. When empty, the WS
   *  URL is derived from `location` (Vite dev proxy). */
  apiBase?: string;
  /** MIME type for captured audio. Default 'audio/webm' (MediaRecorder's
   *  default on Chrome/Edge/Firefox). Override if running on Safari, which
   *  records 'audio/mp4'. */
  recorderMimeType?: string;
}

/** Map an http(s) API base to its ws(s) equivalent, or fall back to the
 *  current page's origin (for the Vite dev proxy) when apiBase is empty. */
function deriveWsBase(apiBase: string): string {
  if (!apiBase) {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    return `${scheme}://${location.host}`;
  }
  return apiBase.replace(/^http/, 'ws');
}

export class VoiceSession {
  private ws: WebSocket | null = null;

  private mediaStream: MediaStream | null = null;
  private mediaRecorder: MediaRecorder | null = null;

  private audioEl: HTMLAudioElement | null = null;
  /** Queue of complete audio files (one per sentence) awaiting playback, each
   *  carrying the clicky gestures the server emitted just before it. The
   *  gestures fire when the item STARTS playing, so the pointer tracks the
   *  heard sentence (the blob-queue analogue of Marfini's MSE buffered-clock
   *  scheduling — MediaSource doesn't exist on this path). */
  private audioQueue: { buf: ArrayBuffer; gestures: ClickyGestureEvent[] }[] = [];
  /** Clicky gestures received since the last audio message — they belong to
   *  the NEXT sentence's audio (the server emits each gesture just before its
   *  sentence's bytes). Attached to that audio item when it arrives. */
  private pendingGestures: ClickyGestureEvent[] = [];
  /** True while an utterance is playing; gates the queue so the next file
   *  starts only once the element is free (on `ended`). */
  private playing = false;
  /** Object URL of the file currently loaded in the element, tracked so we
   *  can revoke it on advance/interrupt/disconnect and not leak blobs. */
  private audioObjectUrl: string | null = null;
  /** Set by interrupt() only when a turn is actually in flight; cleared
   *  on the next status:idle or turn_done. While true, incoming binary
   *  audio frames from the WebSocket are dropped instead of queued for
   *  playback — the server is still streaming the cancelled turn's TTS
   *  but we don't want to hear it. Without this gate, audio silences
   *  for a beat (during teardown) and then resumes as new chunks land
   *  in the fresh MediaSource. */
  private discardIncomingAudio = false;
  /** Server-tracked turn state. True between any non-idle status event
   *  (recording/transcribing/thinking/speaking) and the next
   *  status:idle (or turn_done). interrupt() consults this so a
   *  no-op interrupt (user pressing space when nothing is playing)
   *  doesn't accidentally trip the audio discard for the new turn
   *  they're about to start. */
  private turnInProgress = false;

  private readonly listeners = new Map<keyof VoiceEvents, Set<Listener<keyof VoiceEvents>>>();

  private readonly learnerId: string;
  private readonly wsBase: string;
  private readonly recorderMimeType: string;
  /** Client-side TTS playback speed multiplier, applied to the audio
   *  element directly. Never sent to the server. */
  private playbackRate = 1;
  /** Server-assigned session id, populated when the WS emits its first
   *  `session_started` event (right after the user's first PTT causes
   *  the lazy voice_sessions row insert). null until then. */
  private sessionId: string | null = null;
  /** Monotonic timestamp of the most recent startSpeaking() call. Used
   *  to compute the recording's true duration on stop, which the server
   *  needs for accurate STT cost ($/audio-second). */
  private recordingStartedAt: number | null = null;

  constructor(opts: VoiceSessionOptions) {
    this.learnerId = opts.learnerId;
    const apiBase = opts.apiBase ?? (import.meta.env.VITE_API_BASE as string | undefined) ?? '';
    this.wsBase = deriveWsBase(apiBase);
    this.recorderMimeType = opts.recorderMimeType ?? 'audio/webm';

    // NOTE: no browser media/WebSocket APIs are touched here — the audio
    // element, MediaSource, and WebSocket are all created lazily inside
    // connect()/startSpeaking() so this constructor is safe to call in
    // environments (e.g. jsdom under Vitest) that lack those APIs.
  }

  /** Server-assigned session id, or null if no PTT has happened yet. */
  getSessionId(): string | null {
    return this.sessionId;
  }

  // ---------------------------------------------------------------------
  // Connection lifecycle
  // ---------------------------------------------------------------------

  /** Open the WebSocket and set up MSE-backed audio playback. */
  async connect(): Promise<void> {
    if (this.ws) return; // already connected

    // Audio element doesn't need to be in the DOM — Chrome and Firefox
    // play detached elements fine. Safari needs `playsInline` for video
    // but is happy with detached audio.
    if (!this.audioEl) {
      this.audioEl = new Audio();
      this.audioEl.autoplay = true;
      this.audioEl.playbackRate = this.playbackRate;
    }

    const url = `${this.wsBase}/voice?learner_id=${encodeURIComponent(this.learnerId)}`;
    const ws = new WebSocket(url);
    ws.binaryType = 'arraybuffer';
    this.ws = ws;

    await new Promise<void>((resolve, reject) => {
      const onOpen = () => {
        ws.removeEventListener('error', onError);
        resolve();
      };
      const onError = () => {
        ws.removeEventListener('open', onOpen);
        reject(new Error('WebSocket connection failed'));
      };
      ws.addEventListener('open', onOpen, { once: true });
      ws.addEventListener('error', onError, { once: true });
    });

    this.setupPlayback();

    ws.addEventListener('message', (e) => this.handleMessage(e));
    ws.addEventListener('close', (e) => {
      this.emit('close', { code: e.code, reason: e.reason });
    });

    this.emit('open', undefined);
  }

  /** Cleanly shut everything down: notify server, stop the mic, halt any
   *  in-progress audio playback, tear down the WS + MediaSource. Safe to
   *  call multiple times. */
  async disconnect(): Promise<void> {
    this.stopPlayback();
    this.send({ type: 'goodbye' });

    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      try {
        this.mediaRecorder.stop();
      } catch {
        /* recorder might already be stopping */
      }
    }
    this.mediaRecorder = null;

    this.mediaStream?.getTracks().forEach((t) => t.stop());
    this.mediaStream = null;

    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        /* already closed */
      }
      this.ws = null;
    }

  }

  // ---------------------------------------------------------------------
  // Per-turn control
  // ---------------------------------------------------------------------

  /** Cancel the in-progress tutor reply immediately: silence the audio
   *  element, drop any queued chunks, rebuild a fresh MediaSource for
   *  the next turn. Sends a best-effort `cancel` message to the server
   *  so a future server-side cancellation path can wire to the same
   *  trigger without a protocol bump.
   *
   *  Caveat: if the server's WS handler blocks on running the turn until
   *  it finishes, the server keeps producing tokens + TTS bytes for the
   *  rest of the old turn. Those bytes hit our dropped MediaSource and go
   *  nowhere — silent on the client, billable on the server. True
   *  server-side cancel needs the loop to run the turn as a background
   *  task. */
  interrupt(): void {
    this.stopPlayback();

    // Gate incoming audio frames ONLY if there was actually a turn
    // streaming — otherwise the new turn the user is about to start
    // gets its audio dropped because no offsetting status:idle ever
    // arrives. Cleared on the next status:idle or turn_done from the
    // cancelled turn.
    if (this.turnInProgress) {
      this.discardIncomingAudio = true;
    }

    // Best-effort cancel hint. The server may finish the in-flight turn
    // before it reads this; when server-side cancel lands, that handler
    // picks up this same message without a protocol change.
    this.send({ type: 'cancel' });
  }

  /** Hotkey press: start capturing audio and tell the server a new turn
   *  has begun. The server starts buffering on receipt of `'start'`. */
  async startSpeaking(): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('VoiceSession not connected');
    }
    if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
      return; // already recording — idempotent for stuck-key cases
    }
    if (!this.mediaStream) {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
    }

    // Confirm the requested MIME is supported; fall back to the
    // browser-picked default if not. Safari and some Chrome versions
    // refuse `'audio/webm'` despite advertising MediaRecorder support.
    const mimeType = MediaRecorder.isTypeSupported(this.recorderMimeType)
      ? this.recorderMimeType
      : '';

    const mr = new MediaRecorder(
      this.mediaStream,
      mimeType ? { mimeType } : undefined,
    );
    this.mediaRecorder = mr;

    mr.addEventListener('dataavailable', (e) => {
      if (e.data.size === 0) return;
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      // .arrayBuffer() is async; fire-and-forget — order is preserved
      // within a Blob because each chunk is enqueued via the same
      // microtask channel.
      e.data
        .arrayBuffer()
        .then((buf) => {
          if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(buf);
          }
        })
        .catch(() => {
          /* swallow — surfaced via close event if WS dies */
        });
    });

    this.recordingStartedAt = performance.now();
    const mime_type = mr.mimeType || 'audio/webm';
    this.send({ type: 'start', mime_type });
    // 150ms chunks: small enough that the user sees a tight latency
    // round-trip; large enough that we don't overwhelm the WS with
    // tiny messages on slow connections.
    mr.start(150);
  }

  /** Hotkey release: stop the mic, flush the final audio chunk, then
   *  tell the server to run STT → LLM → TTS for this turn. */
  async stopSpeaking(): Promise<void> {
    const mr = this.mediaRecorder;
    this.mediaRecorder = null;
    // Compute the recording duration before we clear the start ts.
    // performance.now() is monotonic so clock-skew during a long PTT
    // can't cause negative or wildly-off values. The server uses this
    // to compute accurate STT cost ($/audio-second).
    const durationMs =
      this.recordingStartedAt != null
        ? Math.max(0, Math.round(performance.now() - this.recordingStartedAt))
        : undefined;
    this.recordingStartedAt = null;

    const endPayload: { type: 'end'; duration_ms?: number } = { type: 'end' };
    if (durationMs != null) endPayload.duration_ms = durationMs;

    if (!mr || mr.state === 'inactive') {
      // Recorder never started or already finished — still signal end
      // so the server doesn't sit on an unflushed buffer.
      this.send(endPayload);
      return;
    }
    await new Promise<void>((resolve) => {
      mr.addEventListener(
        'stop',
        () => {
          // 'stop' fires AFTER the recorder's final 'dataavailable',
          // so the last chunk is already in flight to the server.
          this.send(endPayload);
          resolve();
        },
        { once: true },
      );
      try {
        mr.stop();
      } catch {
        // Already-stopped recorders throw InvalidStateError. Resolve
        // anyway — the 'stop' listener may not fire in that case.
        this.send(endPayload);
        resolve();
      }
    });
  }

  /** Set the TTS playback speed. Applied client-side to the audio element
   *  (`playbackRate`) — never sent to the server. Takes effect immediately
   *  on any audio currently playing, and on subsequent turns. */
  setSpeed(value: number): void {
    this.playbackRate = value;
    if (this.audioEl) {
      this.audioEl.playbackRate = value;
    }
  }

  // ---------------------------------------------------------------------
  // Event pub-sub
  // ---------------------------------------------------------------------

  /** Subscribe to a typed event. Returns an unsubscribe function. */
  on<K extends keyof VoiceEvents>(
    event: K,
    listener: Listener<K>,
  ): () => void {
    let set = this.listeners.get(event);
    if (!set) {
      set = new Set();
      this.listeners.set(event, set);
    }
    set.add(listener as Listener<keyof VoiceEvents>);
    return () => {
      set!.delete(listener as Listener<keyof VoiceEvents>);
    };
  }

  private emit<K extends keyof VoiceEvents>(
    event: K,
    data: VoiceEvents[K],
  ): void {
    const set = this.listeners.get(event);
    if (!set) return;
    for (const fn of set) {
      try {
        (fn as Listener<K>)(data);
      } catch (err) {
        // A throwing listener shouldn't kill the rest. The next
        // listener in the set should still see the event.
        console.error('VoiceSession listener threw:', err);
      }
    }
  }

  // ---------------------------------------------------------------------
  // Internals
  // ---------------------------------------------------------------------

  private send(payload: object): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  private handleMessage(e: MessageEvent): void {
    if (e.data instanceof ArrayBuffer) {
      // Drop bytes that belong to a cancelled turn. The server may
      // still be finishing the old turn's TTS (no server-side cancel
      // yet); those bytes would play on the freshly-rebuilt
      // MediaSource if we let them through. discardIncomingAudio
      // gets cleared when the server sends turn_done.
      if (this.discardIncomingAudio) return;
      // This sentence's audio just arrived — claim the gestures that streamed
      // ahead of it, so they fire exactly when it starts playing.
      const gestures = this.pendingGestures;
      this.pendingGestures = [];
      this.audioQueue.push({ buf: e.data, gestures });
      this.drainPlayback();
      return;
    }
    if (typeof e.data !== 'string') return;

    let msg: { type?: string; [k: string]: unknown };
    try {
      msg = JSON.parse(e.data);
    } catch {
      return;
    }
    switch (msg.type) {
      case 'session_started': {
        // Server either lazy-inserted the voice_sessions row on first
        // PTT, or it found an existing row for this learner and is
        // reusing it. Either way, remember the id.
        const sid =
          typeof msg.session_id === 'string' ? msg.session_id : null;
        if (sid) {
          this.sessionId = sid;
          this.emit('session_started', { sessionId: sid });
        }
        break;
      }
      case 'status': {
        const phase = msg.phase as VoiceEvents['status']['phase'];
        // idle is the only phase that means "no turn in progress."
        // Use it as the authoritative signal to release the discard
        // gate — defends against turn_done getting reordered or lost.
        if (phase === 'idle') {
          this.turnInProgress = false;
          this.discardIncomingAudio = false;
        } else {
          this.turnInProgress = true;
        }
        this.emit('status', { phase });
        break;
      }
      case 'transcript':
        this.emit('transcript', {
          role: msg.role as 'user' | 'assistant',
          text: String(msg.text ?? ''),
        });
        break;
      case 'token':
        this.emit('token', { text: String(msg.text ?? '') });
        break;
      case 'usage':
        this.emit('usage', (msg.usage as VoiceEvents['usage']) ?? {});
        break;
      case 'turn_done':
        // Belt-and-suspenders: status:idle should have already cleared
        // these, but turn_done is the spec-level "definitely no more
        // events for this turn" signal, so clear here too.
        this.turnInProgress = false;
        this.discardIncomingAudio = false;
        // Any gesture with no following audio (a trailing tag) will never be
        // claimed by an audio item — fire it now so it isn't lost.
        for (const g of this.pendingGestures) this.emit('clicky_gesture', g);
        this.pendingGestures = [];
        this.emit('turn_done', undefined);
        break;
      case 'error':
        this.emit('error', { message: String(msg.message ?? 'Unknown error') });
        break;
      case 'whiteboard_pending':
        this.emit('whiteboard_pending', {
          panelId: String(msg.panel_id ?? ''),
          intent: msg.intent as string | undefined,
        });
        break;
      case 'whiteboard_panel':
        this.emit('whiteboard_panel', {
          panelId: String(msg.panel_id ?? ''),
          html: String(msg.html ?? ''),
          caption: msg.caption as string | undefined,
          intent: msg.intent as string | undefined,
          anchors: Array.isArray(msg.anchors) ? (msg.anchors as string[]) : undefined,
          model: msg.model as string | undefined,
        });
        break;
      case 'whiteboard_error':
        this.emit('whiteboard_error', {
          panelId: String(msg.panel_id ?? ''),
          message: String(msg.message ?? 'render failed'),
          intent: msg.intent as string | undefined,
        });
        break;
      case 'clicky_gesture': {
        // Do NOT emit on receipt — the gesture arrives ahead of its audio.
        // Buffer it; it fires when the next audio item starts playing. If no
        // audio ever follows (e.g. a trailing gesture), turn_done flushes it.
        const g: ClickyGestureEvent = {
          gestureId: String(msg.gesture_id ?? Math.random().toString(36).slice(2)),
          anchor: String(msg.anchor ?? ''),
          gesture: msg.gesture as ClickyGestureEvent['gesture'],
          note: msg.note as string | undefined,
        };
        this.pendingGestures.push(g);
        break;
      }
      // Unknown types are ignored — reserved for protocol extensions.
    }
  }

  private setupPlayback(): void {
    // Advance the queue when the current file finishes (or errors — a
    // decode failure on one sentence must not stall the rest).
    if (!this.audioEl) return;
    const advance = () => {
      this.releaseCurrentUrl();
      this.playing = false;
      this.drainPlayback();
      // Queue drained and nothing restarted — narration has stopped.
      if (!this.playing) this.emit('narrating', { active: false });
    };
    this.audioEl.addEventListener('ended', advance);
    this.audioEl.addEventListener('error', advance);
  }

  private drainPlayback(): void {
    if (this.playing || !this.audioEl) return;
    const next = this.audioQueue.shift();
    if (!next) return;
    this.playing = true;
    // Each queued item is a COMPLETE audio file; a Blob URL lets the
    // element decode it natively (WAV today, any container tomorrow).
    this.audioObjectUrl = URL.createObjectURL(new Blob([next.buf]));
    this.audioEl.src = this.audioObjectUrl;
    this.audioEl.playbackRate = this.playbackRate;
    // This sentence STARTS playing now: fire the gestures that rode ahead of
    // it (so the pointer lands in sync with the heard voice) and mark
    // narration active for the cursor's hold-in-place.
    for (const g of next.gestures) this.emit('clicky_gesture', g);
    this.emit('narrating', { active: true });
    this.audioEl.play().catch(() => {
      // Autoplay-blocked or load raced a teardown — free the slot so the
      // next file (or a later turn) isn't stuck behind a stale `playing`.
      this.playing = false;
    });
  }

  /** Halt playback and drop everything queued. Shared by interrupt() and
   *  disconnect(): pause the element, clear its source, empty the queue. */
  private stopPlayback(): void {
    try {
      this.audioEl?.pause();
      this.audioEl?.removeAttribute('src');
      this.audioEl?.load();
    } catch {
      /* element may already be torn down */
    }
    this.audioQueue = [];
    this.pendingGestures = [];
    this.playing = false;
    this.releaseCurrentUrl();
    // Cancelled/torn-down audio: the pointer should stop holding position.
    this.emit('narrating', { active: false });
  }

  private releaseCurrentUrl(): void {
    if (this.audioObjectUrl) {
      try {
        URL.revokeObjectURL(this.audioObjectUrl);
      } catch {
        /* already revoked */
      }
      this.audioObjectUrl = null;
    }
  }
}
