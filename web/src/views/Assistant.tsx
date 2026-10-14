/* Flect AI: talk to Flect about production, hear what happened, and approve the fixes it suggests.
 *
 * Opening the page asks for a briefing. Flect's words stream in and are spoken sentence by sentence; the logo
 * hops on every word and the caption follows along. Suggested actions wait in the approval tray: approve them
 * there, or just say "yes". Their results arrive as events, which Flect also reads out.
 */
import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { ArrowUp, Check, LoaderCircle, Mic, RotateCcw, Settings2, Square, Volume2, VolumeX, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCore } from "@/lib/api";
import {
  approveAction,
  dismissAction,
  fetchMessages,
  fetchSession,
  transcribe,
  localContext,
  streamTurn,
  type AiAction,
  type AiCounts,
  type AiError,
  type AiEvent,
  type AiMessage,
} from "@/lib/ai";
import { Recorder, Speaker, canListen, englishVoices, listen, loadPrefs, onVoicesChanged, savePrefs, type VoicePrefs } from "@/lib/voice";
import type { Tone } from "@/lib/vocab";
import { FlectOrb, type OrbHandle, type OrbState } from "@/components/flect/FlectOrb";
import { Led, Panel, Tag, Time } from "@/components/flect/bits";
import { useNow } from "@/components/shell/Shell";

type Item = AiMessage & { sk: number; temp?: string };

const BRIEF_AGAIN_MS = 3 * 60_000;
let lastBriefAt = 0; // survives switching views, so hopping between pages does not re-brief every time

const PROMPTS = ["What needs my attention?", "What happened today?", "Fix the open issues", "Anything unusual in the logs?"];
const LISTEN_LANGS: [string, string][] = [
  ["en-IN", "English (India)"],
  ["en-GB", "English (UK)"],
  ["en-US", "English (US)"],
];

const bySk = (a: Item, b: Item) => a.sk - b.sk;
const maxSk = (items: Item[]) => items.reduce((m, i) => Math.max(m, i.sk), 0);

/** Collects streamed text and releases whole sentences, each with its offset in the caption. */
class Sentences {
  private buf = "";
  private at = 0;
  push(text: string, at: number): { text: string; at: number }[] {
    if (!this.buf) this.at = at;
    this.buf += text;
    const out: { text: string; at: number }[] = [];
    const re = /[.!?]+["')\]]*\s+/g;
    let last = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(this.buf))) {
      const end = m.index + m[0].length;
      out.push({ text: this.buf.slice(last, end), at: this.at + last });
      last = end;
    }
    if (last) {
      this.buf = this.buf.slice(last);
      this.at += last;
    }
    return out;
  }
  flush() {
    const out = this.buf.trim() ? [{ text: this.buf, at: this.at }] : [];
    this.buf = "";
    return out;
  }
  clear() {
    this.buf = "";
  }
}

/* ── small pieces ────────────────────────────────────────────────────── */
const RISK: Record<string, [Tone, string]> = { low: ["mute", "Low risk"], medium: ["warn", "Medium risk"], high: ["high", "High risk"] };

const ACTION_STATE: Record<string, [Tone, string]> = {
  proposed: ["iris", "Waiting for you"],
  approved: ["mute", "Starting"],
  running: ["mute", "Running"],
  done: ["ok", "Done"],
  failed: ["crit", "Failed"],
  refused: ["warn", "Can't run"],
  dismissed: ["mute", "Dismissed"],
  expired: ["mute", "Expired"],
};

function IconButton({ label, onClick, children, pressed, className }: { label: string; onClick: () => void; children: ReactNode; pressed?: boolean; className?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      className={cn("inline-flex size-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground [&_svg]:size-[18px]", className)}
    >
      {children}
    </button>
  );
}

function Avatar() {
  const [ok, setOk] = useState(true);
  return (
    <span className="mt-0.5 inline-flex size-6 shrink-0 overflow-hidden rounded-full border bg-card" aria-hidden>
      {ok ? <img src="/static/flect-logo.png" alt="" className="size-full object-cover" onError={() => setOk(false)} /> : <span className="size-full bg-foreground" />}
    </span>
  );
}

/** A suggestion inside the transcript: what it was and what became of it. */
function ActionLine({ a }: { a: AiAction }) {
  const [tone, label] = ACTION_STATE[a.state] ?? ["mute", a.state];
  return (
    <div className="rounded-lg border bg-sunken px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-[13px] font-[600]">{a.title}</span>
        <Tag tone={tone} className="ml-auto">
          {(a.state === "running" || a.state === "approved") && <LoaderCircle className="size-3 animate-spin" />}
          {label}
        </Tag>
      </div>
      {a.result && a.state !== "proposed" && <p className="mt-1 text-[12.5px] text-muted-foreground">{a.result}</p>}
    </div>
  );
}

function MessageItem({ m }: { m: Item }) {
  if (m.role === "operator") {
    return (
      <li className="flex flex-col items-end gap-1">
        <div className="max-w-[88%] rounded-2xl rounded-br-md border bg-accent px-3.5 py-2 text-[14px] break-words">{m.text}</div>
        <span className="pr-1 text-[11.5px] text-faint">
          You · <Time v={m.ts} />
        </span>
      </li>
    );
  }
  if (m.role === "event") {
    const tone: Tone = m.meta.ok === false ? "crit" : "ok";
    return (
      <li className="flex items-start gap-2.5 rounded-lg px-1 text-[13px] text-muted-foreground">
        <Led tone={tone} className="mt-[0.45em]" />
        <span className="min-w-0 flex-1">{m.text}</span>
        <span className="shrink-0 text-[11.5px] text-faint">
          <Time v={m.ts} />
        </span>
      </li>
    );
  }
  const label = m.kind === "briefing" ? (m.meta.fallback ? "Offline briefing" : "Briefing") : null;
  return (
    <li className="flex gap-2.5">
      <Avatar />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="text-[11.5px] text-faint">
          Flect{label ? ` · ${label}` : ""} · <Time v={m.ts} />
        </div>
        <p className="text-[14px] leading-relaxed break-words">{m.text}</p>
        {m.actions.length > 0 && (
          <div className="space-y-1.5">
            {m.actions.map((a) => (
              <ActionLine key={a.id} a={a} />
            ))}
          </div>
        )}
      </div>
    </li>
  );
}

function Caption({ text, pos, word, listening, interim }: { text: string; pos: number; word: [number, number]; listening: boolean; interim: string }) {
  if (listening) {
    return <p className="text-[clamp(19px,2.1vw,24px)] leading-snug font-[460] text-foreground">{interim || <span className="text-muted-foreground">Listening…</span>}</p>;
  }
  if (!text) return <p className="text-[clamp(17px,1.8vw,20px)] leading-snug text-muted-foreground">Tap the logo and talk, or type below.</p>;
  const [ws, we] = word[1] > word[0] ? word : [pos, pos];
  return (
    <p className="text-[clamp(19px,2.1vw,24px)] leading-snug font-[460] [font-stretch:96%]">
      <span>{text.slice(0, ws)}</span>
      <span className="text-iris">{text.slice(ws, we)}</span>
      <span className="text-faint">{text.slice(we)}</span>
    </p>
  );
}

/* ── the view ────────────────────────────────────────────────────────── */
export function AssistantView() {
  const core = useCore();
  const [prefs, setPrefs] = useState<VoicePrefs>(loadPrefs);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>(englishVoices);
  const [items, setItems] = useState<Item[]>([]);
  const [counts, setCounts] = useState<AiCounts>({ pending: 0, running: 0, busy: false });
  const [loaded, setLoaded] = useState(false);
  const [turning, setTurning] = useState(false);
  const [thinkingSince, setThinkingSince] = useState<number | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [listening, setListening] = useState(false);
  const [level, setLevel] = useState(0);
  const [transcribing, setTranscribing] = useState(false);
  const [ears, setEars] = useState<string | null>(null); // "local" when the Spark can transcribe, else why not
  const [interim, setInterim] = useState("");
  const [caption, setCaption] = useState<{ text: string; pos: number; word: [number, number] }>({ text: "", pos: 0, word: [0, 0] });
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [settings, setSettings] = useState(false);
  const [actionBusy, setActionBusy] = useState<number | null>(null);

  const orb = useRef<OrbHandle>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const logRef = useRef<HTMLOListElement>(null);
  const settingsRef = useRef<HTMLDivElement>(null);
  const cap = useRef({ text: "" });
  const lastSpoke = useRef(0);
  const seen = useRef(new Set<number>());
  const floorId = useRef<number | null>(null);
  const turningRef = useRef(false);
  const stopListen = useRef<(() => void) | null>(null);
  const recorder = useRef<Recorder | null>(null);

  const speakerRef = useRef<Speaker | null>(null);
  if (!speakerRef.current) {
    speakerRef.current = new Speaker({
      onWord: (start, len) => {
        setCaption((c) => ({ ...c, pos: Math.max(c.pos, start + len), word: [start, start + len] }));
        if (len) orb.current?.bounce(len / 6);
      },
      onSpeaking: (on) => {
        setSpeaking(on);
        if (!on) lastSpoke.current = Date.now();
      },
      onBlocked: () => setBlocked(true),
    });
  }
  const speaker = speakerRef.current;

  /* voice preferences */
  useEffect(() => onVoicesChanged(() => setVoices(englishVoices())), []);
  useEffect(() => {
    savePrefs(prefs);
    speaker.muted = prefs.muted;
    speaker.broken = false; // a new voice or setting gets a fresh try
    speaker.rate = prefs.rate;
    speaker.voice = voices.find((v) => v.voiceURI === prefs.voice) ?? voices[0] ?? null;
  }, [prefs, voices, speaker]);

  /* caption: what Flect is saying now */
  const begin = () => {
    if (!speaker.speaking && Date.now() - lastSpoke.current > 1500) {
      cap.current.text = "";
      setCaption({ text: "", pos: 0, word: [0, 0] });
    } else if (cap.current.text && !/\s$/.test(cap.current.text)) cap.current.text += " ";
    return cap.current.text.length;
  };
  const append = (t: string) => {
    const at = cap.current.text.length;
    cap.current.text += t;
    const text = cap.current.text;
    setCaption((c) => ({ ...c, text }));
    return at;
  };
  const utter = (text: string) => {
    if (!text.trim()) return;
    begin();
    speaker.say(text, append(text));
  };
  const replay = () => {
    const text = cap.current.text;
    setBlocked(false);
    speaker.stop();
    setCaption({ text, pos: 0, word: [0, 0] });
    speaker.say(text, 0);
  };

  /* conversation */
  const merge = (incoming: AiMessage[], replaceAll = false) =>
    setItems((prev) => {
      const map = new Map<string, Item>();
      for (const m of replaceAll ? prev.filter((p) => !p.id) : prev) map.set(m.id ? `m${m.id}` : m.temp!, m);
      for (const m of incoming) map.set(`m${m.id}`, { ...m, sk: m.id });
      return [...map.values()].sort(bySk);
    });

  const refresh = async () => {
    const r = await fetchMessages();
    setCounts({ pending: r.pending, running: r.running, busy: r.busy });
    merge(r.messages, true);
    setLoaded(true);
    if (floorId.current == null) {
      floorId.current = r.messages.reduce((m, x) => Math.max(m, x.id), 0);
      return;
    }
    for (const m of r.messages) {
      if (m.id > floorId.current && !seen.current.has(m.id)) {
        seen.current.add(m.id);
        if (m.role === "event" && m.meta.speak) utter(m.text);
      }
    }
  };

  const turn = async (kind: "brief" | "chat", text?: string, force = false) => {
    if (turningRef.current) {
      setError("Flect is still answering. One moment.");
      if (text) setInput(text);
      return;
    }
    turningRef.current = true;
    setTurning(true);
    setThinkingSince(Date.now());
    setStatus(null);
    setError(null);
    setBlocked(false);
    let temp: string | undefined;
    if (text) {
      temp = `op-${Date.now()}`;
      const t = temp;
      setItems((p) => [...p, { id: 0, temp: t, sk: maxSk(p) + 0.5, ts: new Date().toISOString(), role: "operator", kind: null, text, meta: {}, actions: [] }]);
    }
    const sentences = new Sentences();
    let streamed = false;
    let start = -1;
    const onEvent = (ev: AiEvent) => {
      switch (ev.type) {
        case "operator":
          seen.current.add(ev.message.id);
          setItems((p) => [...p.filter((m) => m.temp !== temp), { ...ev.message, sk: ev.message.id }].sort(bySk));
          break;
        case "delta": {
          if (start < 0) start = begin();
          streamed = true;
          setStatus(null);
          const at = append(ev.text);
          for (const s of sentences.push(ev.text, at)) speaker.say(s.text, s.at);
          break;
        }
        case "break":
          if (start >= 0) sentences.push(" ", append(" "));
          break;
        case "reset":
          speaker.stop();
          sentences.clear();
          streamed = false;
          if (start >= 0) {
            const keep = start;
            cap.current.text = cap.current.text.slice(0, keep);
            const t = cap.current.text;
            setCaption((c) => ({ text: t, pos: Math.min(c.pos, keep), word: [0, 0] }));
            start = -1;
          }
          break;
        case "lookup":
          setStatus(`Looking up ${ev.what}`);
          break;
        case "message": {
          const m = ev.message;
          if (streamed) for (const s of sentences.flush()) speaker.say(s.text, s.at);
          else utter(m.text);
          if (m.id) {
            seen.current.add(m.id);
            merge([m]);
          } else setItems((p) => [...p, { ...m, temp: `eph-${Date.now()}`, sk: maxSk(p) + 0.5 }]);
          break;
        }
        case "error":
          setError(ev.error);
          break;
        case "done":
          setCounts({ pending: ev.pending, running: ev.running, busy: ev.busy });
          break;
      }
    };
    try {
      await streamTurn(
        kind === "brief" ? "/api/ai/brief" : "/api/ai/chat",
        kind === "brief" ? { ...localContext(), force } : { ...localContext(), text },
        onEvent,
      );
    } catch (e) {
      const err = e as AiError;
      setError(err.status === 409 ? "Flect is still answering. One moment." : err.message || "Flect could not be reached.");
      if (temp) {
        setItems((p) => p.filter((m) => m.temp !== temp));
        if (text) setInput(text);
      }
    } finally {
      turningRef.current = false;
      setTurning(false);
      setThinkingSince(null);
      setStatus(null);
      refreshRef.current().catch(() => {});
    }
  };

  /* Callbacks created once (poll loop, recognition) must reach the latest closures. */
  const refreshRef = useRef(refresh);
  const turnRef = useRef(turn);
  refreshRef.current = refresh;
  turnRef.current = turn;
  const fast = useRef(false);
  fast.current = turning || counts.running > 0;

  /* first load: history, then a briefing (unless one was just given); then keep polling */
  useEffect(() => {
    let alive = true;
    let timer = 0;
    const loop = async (first: boolean) => {
      try {
        await refreshRef.current();
      } catch (e) {
        if (first) setError(`Flect AI is not answering: ${(e as Error).message}`);
      }
      if (first && alive && Date.now() - lastBriefAt > BRIEF_AGAIN_MS) {
        lastBriefAt = Date.now();
        void turnRef.current("brief");
      }
      if (alive) timer = window.setTimeout(() => void loop(false), fast.current ? 1500 : 5000);
    };
    void loop(true);
    fetchSession()
      .then((s) => alive && setEars(s.ears ?? null))
      .catch(() => {});
    return () => {
      alive = false;
      clearTimeout(timer);
      speaker.stop();
      recorder.current?.cancel();
      stopListen.current?.();
    };
  }, [speaker]);

  /* keep the newest message in view */
  useLayoutEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items.length, turning]);

  /* Escape stops Flect talking or listening; clicks outside close the voice settings */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      speaker.stop();
      recorder.current?.cancel();
      stopListen.current?.();
      setSettings(false);
    };
    const onDown = (e: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) setSettings(false);
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [speaker]);

  /* listening: on this machine (Whisper on the Spark) by default, or the browser's online service */
  const localEars = prefs.ears === "local" && ears === "local";

  const listenHere = async () => {
    speaker.stop();
    setError(null);
    setInterim("");
    setListening(true);
    const rec = (recorder.current = new Recorder());
    stopListen.current = () => rec.stop();
    let audio: Blob | null = null;
    try {
      audio = await rec.start(setLevel);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      recorder.current = null;
      stopListen.current = null;
      setListening(false);
      setLevel(0);
    }
    if (!audio) return;
    setTranscribing(true);
    try {
      const text = (await transcribe(audio)).trim();
      if (text) void turnRef.current("chat", text);
      else setError("I didn't catch that. Try again, a little closer to the microphone.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setTranscribing(false);
    }
  };

  const toggleListen = () => {
    if (stopListen.current) {
      stopListen.current();
      return;
    }
    if (transcribing) return;
    if (localEars) {
      void listenHere();
      return;
    }
    if (!canListen()) {
      setError(ears && ears !== "local" ? `Voice input is unavailable here: ${ears}. Type below.` : "This browser can't listen. Type below.");
      inputRef.current?.focus();
      return;
    }
    speaker.stop();
    setError(null);
    setInterim("");
    setListening(true);
    stopListen.current = listen(prefs.listenLang, {
      interim: setInterim,
      final: (t) => void turnRef.current("chat", t),
      end: () => {
        setListening(false);
        setInterim("");
        stopListen.current = null;
      },
      error: (code) => {
        if (code === "no-speech" || code === "aborted") return;
        setError(
          code === "not-allowed" || code === "service-not-allowed"
            ? "The microphone is blocked for this page. Allow it from the address bar, or type instead."
            : code === "network"
              ? ears === "local"
                ? "Your browser's online speech service is unreachable from this network. In voice settings, set speech recognition to “On this machine”."
                : "Your browser's online speech service is unreachable from this network. Type instead."
              : `Listening stopped (${code}).`,
        );
      },
    });
  };

  const onOrb = () => {
    if (speaking) speaker.stop();
    else toggleListen();
  };

  const send = (e?: FormEvent) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput("");
    void turn("chat", text);
  };

  const onApprove = async (a: AiAction) => {
    setActionBusy(a.id);
    setError(null);
    setBlocked(false);
    try {
      const r = await approveAction(a.id);
      seen.current.add(r.message.id);
      merge([r.message]);
      utter(r.message.text);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setActionBusy(null);
      refresh().catch(() => {});
    }
  };

  const onDismiss = async (a: AiAction) => {
    setActionBusy(a.id);
    try {
      await dismissAction(a.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setActionBusy(null);
      refresh().catch(() => {});
    }
  };

  const toggleMute = () => {
    speaker.stop();
    setPrefs((p) => ({ ...p, muted: !p.muted }));
  };

  /* derived */
  const now = useNow(1000);
  const actions = items.flatMap((m) => m.actions);
  const pending = actions.filter((a) => a.state === "proposed");
  const running = actions.filter((a) => a.state === "approved" || a.state === "running");
  const llmOk = core.status?.capabilities?.llm === "ok";
  const orbState: OrbState = listening ? "listening" : speaking ? "speaking" : turning || transcribing ? "thinking" : "idle";
  const secs = thinkingSince ? Math.max(0, Math.round((now - thinkingSince) / 1000)) : 0;
  const [lamp, line]: [Tone, string] =
    orbState === "listening"
      ? ["ok", localEars ? "Listening. Just pause when you're done." : "Listening. Tap the logo when you're done."]
      : orbState === "speaking"
        ? ["iris", prefs.muted ? "Speaking (muted)" : "Speaking. Tap the logo to stop."]
        : orbState === "thinking"
          ? ["iris", transcribing && !turning ? "Writing down what you said…" : `${status ?? (secs < 4 ? "Thinking" : "Reading production")}… ${secs}s`]
          : llmOk || !core.status
            ? ["ok", "Ready. Tap the logo to talk."]
            : ["warn", "Language model offline. Flect can still run what you approve."];
  const orbLabel = listening ? "Stop listening" : speaking ? "Stop speaking" : "Talk to Flect";
  const live = items.filter((m) => m.role !== "operator").length;

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(320px,400px)] lg:items-start">
      <section className="min-w-0 overflow-hidden rounded-2xl border bg-card" aria-label="Talk to Flect">
        <div className="ecg-paper relative flex flex-col items-center px-4 pt-14 pb-8 text-center sm:px-8">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_55%_at_50%_34%,var(--card),transparent)]" aria-hidden />
          <div className="absolute top-3 left-4 flex items-center gap-2 text-[12.5px] text-muted-foreground">
            <Led tone={llmOk ? "ok" : core.status ? "warn" : "mute"} />
            <span>{llmOk ? "DeepSeek, on this machine" : core.status ? "Model offline" : "Connecting"}</span>
          </div>
          <div ref={settingsRef} className="absolute top-2.5 right-3 z-20 flex items-center gap-0.5">
            <IconButton label={prefs.muted ? "Unmute Flect" : "Mute Flect"} onClick={toggleMute} pressed={prefs.muted}>
              {prefs.muted ? <VolumeX /> : <Volume2 />}
            </IconButton>
            <IconButton label="Voice settings" onClick={() => setSettings((o) => !o)} pressed={settings}>
              <Settings2 />
            </IconButton>
            {settings && (
              <VoiceSettings
                prefs={prefs}
                voices={voices}
                ears={ears}
                onChange={(p) => setPrefs((x) => ({ ...x, ...p }))}
                onTest={() => {
                  speaker.stop();
                  lastSpoke.current = 0;
                  utter("Flect online. I'm watching production for you.");
                }}
              />
            )}
          </div>

          <FlectOrb ref={orb} state={orbState} level={level} onClick={onOrb} label={orbLabel} className="relative" />

          <div className="relative mt-3 flex min-h-6 items-center gap-2 text-[13px] text-muted-foreground" role="status" aria-live="polite">
            <Led tone={lamp} pulse={orbState !== "idle"} />
            <span className="num">{line}</span>
          </div>

          <div className="relative mt-6 w-full max-w-[58ch]">
            <Caption text={caption.text} pos={caption.pos} word={caption.word} listening={listening} interim={interim} />
            {blocked && (
              <button
                type="button"
                onClick={replay}
                className="mt-4 inline-flex h-8 items-center gap-2 rounded-lg border bg-card px-3 text-[13px] font-[560] hover:border-line-strong"
              >
                <Volume2 className="size-4" /> Your browser held Flect's voice back. Play it
              </button>
            )}
          </div>

          {(pending.length > 0 || running.length > 0) && (
            <div className="relative mt-8 w-full max-w-[680px] overflow-hidden rounded-xl border bg-card text-left shadow-[0_10px_30px_-18px_rgb(0_0_0/0.35)]">
              {pending.length > 0 && (
                <>
                  <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-2.5">
                    <Led tone="iris" pulse />
                    <h2 className="text-[13.5px] font-[620]">Waiting for your approval</h2>
                    <span className="text-[12.5px] text-muted-foreground">Say “yes”, or approve each one. Nothing runs until you do.</span>
                    {pending.length > 1 && (
                      <button
                        type="button"
                        disabled={turning}
                        onClick={() => void turn("chat", "Yes, go ahead.")}
                        className="ml-auto inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-[600] text-iris hover:bg-accent disabled:opacity-40"
                      >
                        <Check className="size-3.5" /> Approve all {pending.length}
                      </button>
                    )}
                  </header>
                  <ul>
                    {pending.map((a) => (
                      <li key={a.id} className="flex flex-wrap items-start gap-x-4 gap-y-2 border-b px-4 py-3 last:border-b-0">
                        <div className="min-w-[14ch] flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-[620]">{a.title}</span>
                            <Tag tone={RISK[a.risk]?.[0] ?? "mute"}>{RISK[a.risk]?.[1] ?? a.risk}</Tag>
                          </div>
                          {a.why && <p className="mt-1 text-[13px] text-muted-foreground">{a.why}</p>}
                        </div>
                        <div className="flex shrink-0 items-center gap-1.5">
                          <button
                            type="button"
                            disabled={actionBusy === a.id}
                            onClick={() => void onDismiss(a)}
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
                          >
                            <X className="size-4" /> Dismiss
                          </button>
                          <button
                            type="button"
                            disabled={actionBusy === a.id}
                            onClick={() => void onApprove(a)}
                            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-foreground px-3 text-[13px] font-[600] text-background hover:opacity-90 disabled:opacity-40"
                          >
                            {actionBusy === a.id ? <LoaderCircle className="size-4 animate-spin" /> : <Check className="size-4" />} Approve
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {running.length > 0 && (
                <ul className={cn(pending.length > 0 && "border-t")}>
                  {running.map((a) => (
                    <li key={a.id} className="flex items-center gap-3 px-4 py-3 text-[13.5px]">
                      <LoaderCircle className="size-4 shrink-0 animate-spin text-iris" />
                      <span className="font-[580]">{a.title}</span>
                      <span className="ml-auto text-[12.5px] text-muted-foreground">Running</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <div className="border-t px-4 pt-4 pb-4 sm:px-6">
          <form onSubmit={send} className="flex items-center gap-1.5 rounded-xl border bg-background p-1.5 pl-3.5 focus-within:border-line-strong">
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              maxLength={2000}
              placeholder={listening ? "Listening…" : "Ask Flect anything, or tell it what to fix"}
              aria-label="Message Flect"
              className="h-9 min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-faint"
            />
            <IconButton
              label={listening ? "Stop listening" : "Talk to Flect"}
              onClick={toggleListen}
              pressed={listening}
              className={cn(listening && "tone-ok bg-[color-mix(in_oklab,var(--tone)_16%,transparent)] text-[var(--tone)] hover:bg-[color-mix(in_oklab,var(--tone)_22%,transparent)] hover:text-[var(--tone)]")}
            >
              {listening ? <Square /> : <Mic />}
            </IconButton>
            <button
              type="submit"
              disabled={!input.trim() || turning}
              aria-label="Send"
              title="Send"
              className="inline-flex size-9 items-center justify-center rounded-lg bg-foreground text-background disabled:opacity-30"
            >
              <ArrowUp className="size-[18px]" />
            </button>
          </form>
          <div className="mt-3 flex flex-wrap gap-2">
            {PROMPTS.map((p) => (
              <button
                key={p}
                type="button"
                disabled={turning}
                onClick={() => void turn("chat", p)}
                className="inline-flex h-8 items-center rounded-full border bg-card px-3 text-[13px] text-muted-foreground hover:border-line-strong hover:text-foreground disabled:opacity-40"
              >
                {p}
              </button>
            ))}
            <button
              type="button"
              disabled={turning}
              onClick={() => void turn("brief", undefined, true)}
              className="inline-flex h-8 items-center gap-1.5 rounded-full border bg-card px-3 text-[13px] text-muted-foreground hover:border-line-strong hover:text-foreground disabled:opacity-40"
            >
              <RotateCcw className="size-3.5" /> Brief me again
            </button>
          </div>
          {error && (
            <p role="alert" className="mt-3 flex items-start gap-2 text-[13px] text-crit">
              <span className="min-w-0 flex-1">{error}</span>
              <button type="button" onClick={() => setError(null)} aria-label="Dismiss message" className="text-muted-foreground hover:text-foreground">
                <X className="size-4" />
              </button>
            </p>
          )}
        </div>
      </section>

      <Panel title="Conversation" aside={live ? <span className="num">{live} from Flect</span> : null}>
        <ol ref={logRef} role="log" aria-label="Conversation with Flect" className="max-h-[min(72dvh,820px)] space-y-5 overflow-y-auto px-4 py-5 sm:px-5">
          {!loaded ? (
            <li className="h-24" />
          ) : !items.length && !turning ? (
            <li className="py-8 text-center text-[13.5px] text-muted-foreground">Flect's briefings, your questions and every fix you approve appear here.</li>
          ) : (
            items.map((m) => <MessageItem key={m.id ? m.id : m.temp} m={m} />)
          )}
          {turning && (
            <li className="flex items-center gap-2.5 text-[13px] text-muted-foreground">
              <Avatar />
              <span className="blink">{status ?? "Flect is answering"}…</span>
            </li>
          )}
        </ol>
        <p className="border-t px-4 py-3 text-[12px] leading-relaxed text-faint sm:px-5">
          Flect only suggests. Every change waits for your approval, is checked again against live state, and is recorded in the{" "}
          <a href="#/audit" className="underline decoration-line-strong underline-offset-2 hover:text-foreground">
            audit log
          </a>
          .
        </p>
      </Panel>
    </div>
  );
}

function VoiceSettings({
  prefs,
  voices,
  ears,
  onChange,
  onTest,
}: {
  prefs: VoicePrefs;
  voices: SpeechSynthesisVoice[];
  ears: string | null;
  onChange: (p: Partial<VoicePrefs>) => void;
  onTest: () => void;
}) {
  const field = "mt-1.5 h-9 w-full rounded-lg border bg-background px-2.5 text-[13px] font-[450] outline-none focus-visible:border-ring";
  const local = ears === "local";
  return (
    <div className="absolute top-11 right-0 w-[min(320px,calc(100vw-48px))] space-y-4 rounded-xl border bg-popover p-4 text-left shadow-[0_16px_40px_-16px_rgb(0_0_0/0.45)]">
      <label className="block text-[12.5px] font-[580]">
        Voice
        <select value={prefs.voice ?? voices[0]?.voiceURI ?? ""} onChange={(e) => onChange({ voice: e.target.value })} className={field}>
          {!voices.length && <option value="">No English voices in this browser</option>}
          {voices.map((v) => (
            <option key={v.voiceURI} value={v.voiceURI}>
              {v.name.replace(/^Microsoft |^Google /, "")} ({v.lang}){v.localService ? "" : ", online"}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-[12.5px] font-[580]">
        Speed <span className="font-[450] text-muted-foreground num">{prefs.rate.toFixed(2)}×</span>
        <input type="range" min={0.8} max={1.3} step={0.05} value={prefs.rate} onChange={(e) => onChange({ rate: Number(e.target.value) })} className="mt-2 block w-full accent-[var(--iris)]" />
      </label>
      <label className="block text-[12.5px] font-[580]">
        Speech recognition
        <select value={local ? prefs.ears : "browser"} onChange={(e) => onChange({ ears: e.target.value as VoicePrefs["ears"] })} className={field}>
          <option value="local" disabled={!local}>
            On this machine (private){local ? "" : ", unavailable"}
          </option>
          <option value="browser">Browser speech service (online)</option>
        </select>
        {!local && ears && <span className="mt-1 block text-[12px] font-[450] text-muted-foreground">{ears}</span>}
      </label>
      {(!local || prefs.ears === "browser") && (
        <label className="block text-[12.5px] font-[580]">
          I speak
          <select value={prefs.listenLang} onChange={(e) => onChange({ listenLang: e.target.value })} className={field}>
            {LISTEN_LANGS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
      )}
      <button type="button" onClick={onTest} className="inline-flex h-8 items-center gap-2 rounded-lg border px-3 text-[13px] font-[560] hover:border-line-strong">
        <Volume2 className="size-4" /> Test the voice
      </button>
      <p className="text-[12px] leading-relaxed text-muted-foreground">
        Voices without “online” speak on this computer. “On this machine” transcribes your voice on the Spark; the browser service sends it to Google or
        Microsoft.
      </p>
    </div>
  );
}
