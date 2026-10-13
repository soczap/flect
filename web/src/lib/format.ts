/* Formatting helpers. Times from the API are ISO strings or unix seconds. */

export const toMs = (v: string | number | null | undefined): number | null => {
  if (v == null || v === "") return null;
  if (typeof v === "number") return v < 1e12 ? v * 1000 : v;
  const t = Date.parse(v);
  return Number.isNaN(t) ? null : t;
};

/** "2h 14m", "806d 21h", "45s" */
export function dur(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  let s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  s = h % 24;
  return `${d}d ${s}h`;
}

export function ago(v: string | number | null | undefined, now = Date.now()): string {
  const t = toMs(v);
  if (t == null) return "—";
  const s = Math.round((now - t) / 1000);
  if (s < 0) return `in ${dur(-s)}`;
  if (s < 45) return "just now";
  return `${dur(s)} ago`;
}

export const since = (v: string | number | null | undefined, now = Date.now()) => {
  const t = toMs(v);
  return t == null ? null : (now - t) / 1000;
};

export function when(v: string | number | null | undefined): string {
  const t = toMs(v);
  if (t == null) return "—";
  const d = new Date(t);
  const opt: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" };
  if (d.getFullYear() !== new Date().getFullYear()) opt.year = "numeric";
  return d.toLocaleString(undefined, opt);
}

export const fullTime = (v: string | number | null | undefined) => {
  const t = toMs(v);
  return t == null ? "" : new Date(t).toLocaleString();
};

export const clock = (unixSeconds: number, seconds = false) =>
  new Date(unixSeconds * 1000).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    ...(seconds ? { second: "2-digit" } : {}),
  });

export function num(v: number | null | undefined, digits = 0): string {
  if (v == null || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export const short = (sha: string | null | undefined) => (sha ? String(sha).slice(0, 7) : "");

export const sentence = (s: string | null | undefined) =>
  String(s ?? "")
    .replace(/_/g, " ")
    .replace(/^\w/, (c) => c.toUpperCase());

export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export function parseJSON<T>(s: string | null | undefined, fallback: T): T {
  if (!s) return fallback;
  try {
    return JSON.parse(s) as T;
  } catch {
    return fallback;
  }
}
