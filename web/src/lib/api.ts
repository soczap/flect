/* Typed client for Flect's read-only dashboard API (flect/server.py). */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

export type Mode = "enforce" | "observe" | "off";

export interface Capabilities {
  sandbox?: string;
  nft?: string;
  uat?: string;
  llm?: string;
  github_poll?: string;
  log_lines?: number;
  stale_lines_skipped?: number;
  llm_queue?: { queued: number; in_flight: number };
  updated?: string;
}

export interface Health {
  ts: number;
  http_ok: boolean;
  http_status: number | null;
  latency_ms: number | null;
  error: string | null;
  active_state?: string;
  n_restarts?: number;
  main_pid?: number;
  uptime_s?: number | null;
}

export interface Dos {
  global_rps: number;
  baseline_rps: number;
  flooding: boolean;
  top_talkers_60s: [string, number][];
  allowlisted_requests?: number;
}

export interface Status {
  modes: Record<string, Mode>;
  writes_paused: string | null;
  capabilities: Capabilities | null;
  health: Health | null;
  dos: Dos | null;
  target: string;
  repo: string;
  lkg: { sha: string; started_ts: string } | null;
}

export interface Overview {
  open_incidents: Record<string, number>;
  open_incident_total: number;
  resolved_24h: number;
  active_blocks: number;
  blocks_24h: number;
  prs: Record<string, number>;
  deploys_24h: number;
  last_deploy: { env: string; sha: string; trigger: string; state: string; started_ts: string } | null;
  keys: Record<string, number>;
  next_expiry: { name: string; expires_ts: string; days_left: number } | null;
  llm_24h: { calls: number; ok: number | null; avg_s: number | null; out_tokens: number | null } | null;
  availability_1h: number | null;
  latency_ms_avg: number | null;
  healthy_since: number | null;
  actions_24h: number;
  reports: number;
  reports_by_kind: Record<string, number>;
  rollbacks_24h: number;
  had_failure_1h: boolean;
  ai_pending?: number;
  now: number;
}

export interface Meta {
  version: string;
  repo: string;
  repo_url: string;
  target: string;
  prod_url: string;
  uat_url: string;
  feature_base: string;
  prod_branch: string;
  started: number | null;
  allowlist: string[];
  dashboard: { host: string; port: number };
}

/** health: [ts, ok, latency_ms]; traffic: [ts, rps, baseline, flooding] */
export interface History {
  health: [number, boolean, number | null][];
  traffic: [number, number, number, boolean][];
}

export interface Incident {
  id: number;
  kind: string;
  severity: string;
  state: string;
  opened_ts: string;
  closed_ts: string | null;
  title: string;
  summary: string | null;
  github_issue: number | null;
  llm_summary: string | null;
}

export interface Action {
  id?: number;
  ts: string;
  decision: string;
  target: string;
  params?: string;
  mode: string;
  ok: number | null;
  result: string | null;
  incident_id?: number | null;
}

export interface IncidentDetail extends Incident {
  details: Record<string, unknown>;
  dedupe_key?: string;
  actions: Action[];
}

export interface Block {
  id: number;
  ip: string;
  rule_id: string;
  reason: string;
  offence: number;
  ttl: string;
  created_ts: string;
  expires_ts: string;
  active: number;
  mode: string;
  incident_id: number | null;
  unblocked_by: string | null;
}

export interface PullRequest {
  number: number;
  head_sha: string;
  base: string;
  kind: string;
  state: string;
  risk: string | null;
  title: string | null;
  statuses: string | null;
  updated_ts: string;
}

export interface Deployment {
  id: number;
  env: string;
  sha: string;
  previous_sha: string | null;
  trigger: string;
  state: string;
  started_ts: string;
  finished_ts: string | null;
  healthy_since: string | null;
  notes: string | null;
}

export interface KeyRow {
  name: string;
  kind: string;
  location: string;
  expires_ts: string | null;
  days_left: number | null;
  last_probe_ts: string | null;
  last_probe_ok: number | null;
  alert_level: string;
  details: string | null;
}

export interface Report {
  id: number;
  kind: string;
  ref_sha: string | null;
  pr_number: number | null;
  max_severity: string | null;
  created_ts: string;
  title: string;
}

export async function api<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(path, { cache: "no-store", signal });
  if (!r.ok) throw new Error(`${path} answered HTTP ${r.status}`);
  const type = r.headers.get("content-type") || "";
  return (type.includes("json") ? r.json() : r.text()) as Promise<T>;
}

/* Last good response per path, so switching views paints instantly and refreshes underneath. */
const cache = new Map<string, unknown>();

export const POLL_MS = 5000;

/** Fetch `path` now and every `interval` ms. Keeps the last good data when a refresh fails. */
export function usePoll<T>(path: string | null, interval = POLL_MS) {
  const [data, setData] = useState<T | undefined>(() => (path ? (cache.get(path) as T | undefined) : undefined));
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!path) return;
    setData(cache.get(path) as T | undefined);
    let alive = true;
    let ctrl = new AbortController();
    const load = async () => {
      ctrl.abort();
      ctrl = new AbortController();
      try {
        const d = await api<T>(path, ctrl.signal);
        if (!alive) return;
        cache.set(path, d);
        setData(d);
        setError(null);
      } catch (e) {
        if (alive && (e as Error).name !== "AbortError") setError(e as Error);
      }
    };
    load();
    const t = interval > 0 ? setInterval(load, interval) : undefined;
    return () => {
      alive = false;
      ctrl.abort();
      if (t) clearInterval(t);
    };
  }, [path, interval, tick]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, loading: data === undefined && !error, reload };
}

/* ── core state shared by the shell and every view ─────────────────────── */
export interface Core {
  meta?: Meta;
  status?: Status;
  overview?: Overview;
  history?: History;
  lastOk: number;
  error: Error | null;
}

export const CoreContext = createContext<Core>({ lastOk: 0, error: null });
export const useCore = () => useContext(CoreContext);

export function useCoreLoader(): Core {
  const [core, setCore] = useState<Core>({ lastOk: 0, error: null });
  const meta = useRef<Meta | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [status, overview, history] = await Promise.all([
          api<Status>("/api/status"),
          api<Overview>("/api/overview"),
          api<History>("/api/history"),
        ]);
        if (!meta.current) meta.current = await api<Meta>("/api/meta");
        if (alive) setCore({ meta: meta.current, status, overview, history, lastOk: Date.now(), error: null });
      } catch (e) {
        if (alive) setCore((c) => ({ ...c, error: e as Error }));
      }
    };
    load();
    const t = setInterval(load, POLL_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  return core;
}
