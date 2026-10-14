/* Flect's voice and ears, from the browser's own speech APIs.
 *
 * Speaker reads text aloud sentence by sentence and reports every word as it is spoken, which drives the logo's
 * bounce and the caption. Voices that report no word boundaries, and the muted mode, use a talking-pace clock
 * instead, so the logo still bounces in time. listen() wraps SpeechRecognition (Chrome, Edge, Safari).
 */

export interface VoicePrefs {
  muted: boolean;
  voice: string | null; // voiceURI
  rate: number;
  listenLang: string;
  /** Who turns speech into text: this machine (Whisper on the Spark) or the browser's online service. */
  ears: "local" | "browser";
}

const PREFS_KEY = "flect-voice";

function defaultListenLang() {
  const langs = typeof navigator !== "undefined" ? navigator.languages ?? [navigator.language] : [];
  return langs.find((l) => /^en-(IN|GB|US)$/i.test(l)) ?? "en-IN";
}

export function loadPrefs(): VoicePrefs {
  const base: VoicePrefs = { muted: false, voice: null, rate: 1, listenLang: defaultListenLang(), ears: "local" };
  try {
    return { ...base, ...(JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") as Partial<VoicePrefs>) };
  } catch {
    return base;
  }
}

export function savePrefs(p: VoicePrefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* private window: preferences last for this visit only */
  }
}

const synth = (): SpeechSynthesis | null => (typeof window !== "undefined" && "speechSynthesis" in window ? window.speechSynthesis : null);

/** Local voices first (what Flect says stays on this computer), then British, Indian and US English. */
function rank(v: SpeechSynthesisVoice): number {
  let s = v.localService ? 100 : 0;
  if (/^en[-_]GB/i.test(v.lang)) s += 30;
  else if (/^en[-_]IN/i.test(v.lang)) s += 26;
  else if (/^en[-_]US/i.test(v.lang)) s += 20;
  else if (/^en/i.test(v.lang)) s += 10;
  if (/george|ryan|daniel|thomas|arthur|oliver|ravi|prabhat|david|mark|guy|\bmale\b/i.test(v.name)) s += 6;
  if (/natural|neural/i.test(v.name)) s += 3;
  return s;
}

export function englishVoices(): SpeechSynthesisVoice[] {
  const s = synth();
  if (!s) return [];
  return s
    .getVoices()
    .filter((v) => /^en/i.test(v.lang))
    .sort((a, b) => rank(b) - rank(a) || a.name.localeCompare(b.name));
}

export function onVoicesChanged(cb: () => void): () => void {
  const s = synth();
  if (!s) return () => {};
  s.addEventListener("voiceschanged", cb);
  return () => s.removeEventListener("voiceschanged", cb);
}

/** Split text into sentence-sized pieces; long sentences break at commas so no utterance runs too long. */
export function chunks(text: string): { text: string; at: number }[] {
  const out: { text: string; at: number }[] = [];
  const re = /[^.!?]+(?:[.!?]+["')\]]*|$)\s*/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) && m[0]) {
    let piece = m[0];
    let at = m.index;
    while (piece.length > 220) {
      const cut = Math.max(piece.lastIndexOf(", ", 200), piece.lastIndexOf("; ", 200), piece.lastIndexOf(" ", 200));
      const n = cut > 40 ? cut + 1 : 200;
      out.push({ text: piece.slice(0, n), at });
      piece = piece.slice(n);
      at += n;
    }
    if (piece.trim()) out.push({ text: piece, at });
  }
  return out;
}

export interface SpeakerEvents {
  /** A word is being spoken: [start, start + length) in the caption. length 0 = finished up to `start`. */
  onWord: (start: number, length: number) => void;
  onSpeaking: (on: boolean) => void;
  /** The browser refused to speak (no click on the page yet). Text keeps flowing silently. */
  onBlocked: () => void;
}

export class Speaker {
  private queue: { text: string; at: number }[] = [];
  /** Held so Chrome does not garbage-collect the utterance (and drop its events) mid-sentence. */
  current: SpeechSynthesisUtterance | null = null;
  private timer: number | null = null;
  private gen = 0;
  private active = false;
  muted = false;
  rate = 1;
  voice: SpeechSynthesisVoice | null = null;
  /** Speech synthesis failed on this machine (no voices, no audio): keep going silently on the word clock. */
  broken = false;

  constructor(private ev: SpeakerEvents) {}

  get speaking() {
    return this.active;
  }

  /** Queue `text`, which starts at offset `at` in the caption. */
  say(text: string, at: number) {
    for (const c of chunks(text)) this.queue.push({ text: c.text, at: at + c.at });
    if (!this.active) this.next();
  }

  stop() {
    this.gen++;
    this.queue = [];
    this.clearTimer();
    this.current = null;
    synth()?.cancel();
    this.setActive(false);
  }

  private setActive(on: boolean) {
    if (on !== this.active) {
      this.active = on;
      this.ev.onSpeaking(on);
    }
  }

  private clearTimer() {
    if (this.timer != null) clearTimeout(this.timer);
    this.timer = null;
  }

  private next() {
    this.clearTimer();
    const item = this.queue.shift();
    if (!item) {
      this.setActive(false);
      return;
    }
    this.setActive(true);
    const s = synth();
    if (this.muted || this.broken || !s) {
      this.clock(item, this.gen, true);
      return;
    }
    const g = this.gen;
    let started = false;
    const u = new SpeechSynthesisUtterance(item.text);
    if (this.voice) u.voice = this.voice;
    u.lang = this.voice?.lang || "en-GB";
    u.rate = this.rate;
    let words = false;
    u.onboundary = (e) => {
      if (g !== this.gen || (e.name && e.name !== "word")) return;
      if (!words) this.clearTimer(); // real boundaries arrived: drop the estimate
      words = true;
      const len = e.charLength || (/^\S+/.exec(item.text.slice(e.charIndex))?.[0].length ?? 1);
      this.ev.onWord(item.at + e.charIndex, len);
    };
    u.onstart = () => {
      if (g !== this.gen) return;
      started = true;
      this.clearTimer();
      // Some voices (most online ones) never report word boundaries; estimate them after a short wait.
      this.timer = window.setTimeout(() => !words && g === this.gen && this.clock(item, g, false), 450);
    };
    u.onend = () => {
      if (g !== this.gen) return;
      this.ev.onWord(item.at + item.text.length, 0);
      this.current = null;
      this.next();
    };
    u.onerror = (e) => {
      if (g !== this.gen || e.error === "interrupted" || e.error === "canceled") return;
      this.current = null;
      this.clearTimer();
      if (e.error === "not-allowed") this.ev.onBlocked();
      else this.broken = true;
      this.clock(item, g, true);
    };
    this.current = u;
    s.speak(u);
    // Some systems accept speak() and then never start (no speech engine): carry on silently.
    this.timer = window.setTimeout(() => {
      if (g !== this.gen || started) return;
      this.broken = true;
      this.current = null;
      s.cancel();
      this.clock(item, g, true);
    }, 2500);
  }

  /** Walk the words at a talking pace. `advance`: move on to the next sentence when done (silent mode). */
  private clock(item: { text: string; at: number }, g: number, advance: boolean) {
    const words = [...item.text.matchAll(/\S+/g)];
    const base = 60000 / (172 * this.rate);
    let i = 0;
    const tick = () => {
      if (g !== this.gen) return;
      if (i >= words.length) {
        this.timer = null;
        if (advance) {
          this.ev.onWord(item.at + item.text.length, 0);
          this.next();
        }
        return;
      }
      const w = words[i++];
      this.ev.onWord(item.at + (w.index ?? 0), w[0].length);
      const pause = /[,;:]$/.test(w[0]) ? 1.5 : /[.!?]$/.test(w[0]) ? 2 : 1;
      this.timer = window.setTimeout(tick, base * Math.min(1.8, Math.max(0.7, w[0].length / 5)) * pause);
    };
    tick();
  }
}

/* ── listening ─────────────────────────────────────────────────────────── */
interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}
interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  onresult: ((e: { resultIndex: number; results: ArrayLike<RecognitionResult> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const canListen = () => recognitionCtor() !== null;

/** Listen for one utterance. Returns a function that stops listening (what was heard so far is still sent). */
export function listen(
  lang: string,
  on: { interim: (text: string) => void; final: (text: string) => void; end: () => void; error: (code: string) => void },
): () => void {
  const Ctor = recognitionCtor();
  if (!Ctor) {
    on.error("unsupported");
    on.end();
    return () => {};
  }
  const rec = new Ctor();
  rec.lang = lang;
  rec.interimResults = true;
  rec.continuous = false;
  rec.maxAlternatives = 1;
  let finalText = "";
  rec.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) finalText += r[0].transcript;
      else interim += r[0].transcript;
    }
    on.interim((finalText + " " + interim).trim());
  };
  rec.onerror = (e) => on.error(e.error);
  rec.onend = () => {
    if (finalText.trim()) on.final(finalText.trim());
    on.end();
  };
  rec.start();
  return () => rec.stop();
}

/* ── listening on this machine ─────────────────────────────────────────────
 * Records one utterance from the microphone and hands back the audio, for Flect to transcribe locally. A
 * simple voice-activity check calibrates to the room for a moment, waits for speech, and stops after a pause.
 */
export class MicError extends Error {}

const MIME = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];

export const canRecord = () =>
  typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";

export class Recorder {
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private rec: MediaRecorder | null = null;
  private timer = 0;
  private discard = false;

  /** Resolves with the recording when the speaker pauses (or stop() is called), or null if nothing was said. */
  async start(onLevel: (level: number) => void): Promise<Blob | null> {
    if (!canRecord()) throw new MicError("This page can't use the microphone. Open the dashboard as http://localhost or http://127.0.0.1.");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch (e) {
      const name = (e as DOMException).name;
      throw new MicError(
        name === "NotAllowedError" || name === "SecurityError"
          ? "The microphone is blocked for this page. Allow it from the address bar, then tap the logo again."
          : name === "NotFoundError"
            ? "No microphone found on this computer."
            : `The microphone could not start (${name}).`,
      );
    }
    const mimeType = MIME.find((m) => MediaRecorder.isTypeSupported(m));
    const rec = (this.rec = new MediaRecorder(this.stream, mimeType ? { mimeType } : undefined));
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);

    const ctx = (this.ctx = new AudioContext());
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    ctx.createMediaStreamSource(this.stream).connect(analyser);
    const buf = new Float32Array(analyser.fftSize);

    const started = performance.now();
    let noise = 0;
    let noiseN = 0;
    let voiceMs = 0;
    let quietMs = 0;
    let heard = false;
    const STEP = 50;

    const done = new Promise<Blob | null>((resolve) => {
      rec.onstop = () => {
        this.release();
        resolve(this.discard || !heard || !chunks.length ? null : new Blob(chunks, { type: rec.mimeType || "audio/webm" }));
      };
    });
    rec.start(250);

    this.timer = window.setInterval(() => {
      analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += v * v;
      const rms = Math.sqrt(sum / buf.length);
      const t = performance.now() - started;
      if (t < 300) {
        noise += rms; // the first moment is the room, not the speaker
        noiseN++;
        return;
      }
      const floor = noiseN ? noise / noiseN : 0;
      const threshold = Math.max(0.012, floor * 2.6);
      onLevel(Math.min(1, rms / (threshold * 4)));
      if (rms > threshold) {
        voiceMs += STEP;
        quietMs = 0;
        if (voiceMs >= 150) heard = true;
      } else {
        quietMs += STEP;
        if (!heard) voiceMs = 0;
      }
      const pausedAfterSpeech = heard && quietMs >= 1300;
      const nothingSaid = !heard && t > 8000;
      if (pausedAfterSpeech || nothingSaid || t > 25000) this.stop();
    }, STEP);
    return done;
  }

  /** Stop now and keep what was said so far. */
  stop() {
    clearInterval(this.timer);
    if (this.rec?.state === "recording") this.rec.stop();
    else this.release();
  }

  /** Stop and throw the recording away. */
  cancel() {
    this.discard = true;
    this.stop();
  }

  private release() {
    clearInterval(this.timer);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    void this.ctx?.close().catch(() => {});
    this.ctx = null;
  }
}
