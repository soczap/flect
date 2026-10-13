/*
 * VIGIL's heartbeat: one point per health check (every 5 s) over the last hour, drawn like a patient
 * monitor. Failed checks are flare-red bars; gaps in sampling break the line instead of bridging it.
 */
import { useLayoutEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { cn } from "@/lib/utils";
import { clock, dur, num } from "@/lib/format";
import type { History } from "@/lib/api";
import { toneClass } from "./bits";
import type { Tone } from "@/lib/vocab";

const WINDOW_S = 3600;
const GAP_S = 20;

export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth);
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function niceStep(raw: number) {
  const p = 10 ** Math.floor(Math.log10(raw));
  const f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}

type Sample = History["health"][number];

export function Heartbeat({ hist, tone, height = 176 }: { hist: Sample[]; tone: Tone; height?: number }) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<Sample | null>(null);
  // The trace sweeps in once, the first time there is something to draw; live updates never re-animate.
  const [revealed, setRevealed] = useState(false);

  const H = height;
  const PAD_T = 34;
  const PAD_B = 12;
  const PAD_R = 14;

  const geo = useMemo(() => {
    if (!W || !hist.length) return null;
    const anchor = hist[hist.length - 1][0];
    const x0 = anchor - WINDOW_S;
    const pts = hist.filter((h) => h[0] >= x0);
    const lat = pts.filter((h) => h[1] && h[2] != null).map((h) => h[2] as number);
    const peak = lat.length ? Math.max(...lat) : 40;
    const step = niceStep(Math.max(peak * 1.35, 40) / 3);
    const yMax = step * 3;
    const X = (t: number) => ((t - x0) / WINDOW_S) * (W - PAD_R);
    const Y = (v: number) => H - PAD_B - (v / yMax) * (H - PAD_T - PAD_B);

    let d = "";
    let prev: Sample | null = null;
    for (const p of pts) {
      if (!p[1] || p[2] == null) {
        prev = null;
        continue;
      }
      const cmd = prev && p[0] - prev[0] <= GAP_S ? "L" : "M";
      d += `${cmd}${X(p[0]).toFixed(1)},${Y(p[2]).toFixed(1)}`;
      prev = p;
    }
    const fails = pts.filter((p) => !p[1]).map((p) => X(p[0]));
    const lastOk = [...pts].reverse().find((p) => p[1] && p[2] != null);
    const last = pts[pts.length - 1];
    const ticks = [step, step * 2];
    // Flect keeps an hour of samples in memory, so after a restart the left of the window is blank.
    const firstX = pts.length ? X(pts[0][0]) : 0;
    const blankSince = firstX > 300 ? { x: firstX, s: anchor - pts[0][0] } : null;
    return { d, fails, X, Y, x0, pts, ticks, blankSince, head: last && last[1] && lastOk === last ? { x: X(last[0]), y: Y(last[2] as number) } : null };
  }, [hist, W, H]);

  const onMove = (e: MouseEvent<HTMLDivElement>) => {
    if (!geo) return;
    const r = e.currentTarget.getBoundingClientRect();
    const t = geo.x0 + ((e.clientX - r.left) / r.width) * WINDOW_S;
    let best: Sample | null = null;
    for (const p of geo.pts) if (!best || Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p;
    setHover(best);
  };

  return (
    <div
      ref={ref}
      className={cn("relative w-full select-none", toneClass(tone))}
      style={{ height: H }}
      onMouseMove={onMove}
      onMouseLeave={() => setHover(null)}
      role="img"
      aria-label={`Response time of each health check over the last hour${hist.length ? `, ${hist.filter((h) => !h[1]).length} failed` : ""}`}
    >
      {!geo ? (
        <div className="absolute inset-0 flex items-center px-6">
          <div className="absolute inset-x-0 top-1/2 border-t border-dashed border-line-strong" />
          <p className="relative mx-auto bg-sunken px-3 text-center text-[13px] text-muted-foreground">
            Waiting for the first health checks. The trace fills in every 5 seconds.
          </p>
        </div>
      ) : (
        <svg
          width={W}
          height={H}
          viewBox={`0 0 ${W} ${H}`}
          className={cn("absolute inset-0 overflow-visible", !revealed && "trace-reveal")}
          onAnimationEnd={() => setRevealed(true)}
        >
          <defs>
            <filter id="hb-glow" x="-5%" y="-30%" width="110%" height="160%">
              <feGaussianBlur stdDeviation="3" />
            </filter>
          </defs>
          <text x={14} y={18} className="fill-muted-foreground text-[12px]">
            Response time of each health check
          </text>
          {geo.blankSince && (
            <text x={geo.blankSince.x / 2} y={(H + PAD_T) / 2 + 4} textAnchor="middle" className="fill-faint text-[11.5px]">
              Flect started {dur(geo.blankSince.s)} ago; earlier samples are not kept
            </text>
          )}
          {geo.ticks.map((v) => (
            <g key={v}>
              <line x1={0} x2={W} y1={geo.Y(v)} y2={geo.Y(v)} stroke="var(--line-strong)" strokeDasharray="2 4" strokeWidth={1} />
              <text x={14} y={geo.Y(v) - 5} className="fill-faint text-[10.5px] num">
                {num(v)} ms
              </text>
            </g>
          ))}
          {geo.fails.map((x, i) => (
            <g key={i} className="tone-crit">
              <rect x={x - 1.5} y={PAD_T - 8} width={3} height={H - PAD_T + 8 - PAD_B} fill="var(--tone)" opacity={0.28} />
              <circle cx={x} cy={H - PAD_B} r={2.5} fill="var(--tone)" />
            </g>
          ))}
          <path d={geo.d} fill="none" stroke="var(--tone)" strokeWidth={4} opacity="var(--glow)" filter="url(#hb-glow)" />
          <path d={geo.d} fill="none" stroke="var(--tone)" strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" />
          {geo.head && (
            <g>
              <circle cx={geo.head.x} cy={geo.head.y} r={3.5} fill="var(--tone)" className="trace-halo" />
              <circle cx={geo.head.x} cy={geo.head.y} r={3.5} fill="var(--tone)" stroke="var(--sunken)" strokeWidth={1.5} />
            </g>
          )}
          {hover && (
            <line x1={geo.X(hover[0])} x2={geo.X(hover[0])} y1={8} y2={H - PAD_B} stroke="var(--foreground)" strokeOpacity={0.35} strokeWidth={1} />
          )}
        </svg>
      )}
      {geo && hover && (
        <div
          className="pointer-events-none absolute top-1 z-10 -translate-x-1/2 rounded-md border bg-popover px-2.5 py-1.5 text-[12px] whitespace-nowrap shadow-sm"
          style={{ left: Math.min(Math.max(geo.X(hover[0]), 70), W - 70) }}
        >
          <span className="text-muted-foreground num">{clock(hover[0], true)}</span>
          <span className="ml-2 font-[600] num">
            {hover[1] ? `${num(hover[2], 0)} ms` : <span className="text-crit">no response</span>}
          </span>
        </div>
      )}
    </div>
  );
}

/** One cell per minute of the last hour; flare when any check in that minute failed. */
export function AvailabilityStrip({ hist }: { hist: Sample[] }) {
  const cells = useMemo(() => {
    const anchor = hist.length ? hist[hist.length - 1][0] : Date.now() / 1000;
    const x0 = anchor - WINDOW_S;
    const out = Array.from({ length: 60 }, (_, i) => ({ t: x0 + i * 60, n: 0, bad: 0 }));
    for (const [t, ok] of hist) {
      const i = Math.floor((t - x0) / 60);
      if (i < 0 || i > 59) continue;
      out[i].n++;
      if (!ok) out[i].bad++;
    }
    return out;
  }, [hist]);

  return (
    <div className="flex h-[7px] gap-[2px]" aria-hidden>
      {cells.map((c, i) => (
        <span
          key={i}
          title={c.n ? `${clock(c.t)}: ${c.n - c.bad} of ${c.n} checks answered` : `${clock(c.t)}: no samples`}
          className={cn(
            "h-full flex-1 rounded-[1.5px]",
            !c.n ? "bg-border" : c.bad ? "bg-crit" : "bg-ok/70",
          )}
        />
      ))}
    </div>
  );
}
