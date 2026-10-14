/* Client for the Flect AI console (flect/server.py /api/ai/*): streamed turns, approvals, the session token. */
import { api } from "./api";

export type AiActionState = "proposed" | "refused" | "approved" | "running" | "done" | "failed" | "dismissed" | "expired";

export interface AiAction {
  id: number;
  message_id: number;
  action: string;
  args: Record<string, unknown>;
  title: string;
  why: string | null;
  risk: "low" | "medium" | "high";
  state: AiActionState;
  created_ts: string;
  decided_ts: string | null;
  finished_ts: string | null;
  result: string | null;
}

export interface AiMessage {
  id: number;
  ts: string;
  role: "operator" | "flect" | "event";
  kind: string | null;
  text: string;
  meta: { speak?: boolean; ok?: boolean; ephemeral?: boolean; fallback?: boolean; action_id?: number };
  actions: AiAction[];
}

export interface AiCounts {
  pending: number;
  running: number;
  busy: boolean;
}

export type AiEvent =
  | { type: "operator"; message: AiMessage }
  | { type: "delta"; text: string }
  | { type: "reset" }
  | { type: "break" }
  | { type: "lookup"; what: string }
  | { type: "message"; message: AiMessage }
  | { type: "error"; error: string }
  | ({ type: "done" } & AiCounts);

export class AiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

let token: string | null = null;

async function sessionToken(fresh = false): Promise<string> {
  if (!token || fresh) token = (await api<{ token: string }>("/api/ai/session")).token;
  return token;
}

/** POST with the session token. A 403 usually means Flect restarted (new token): fetch it once and retry. */
async function post(path: string, body?: unknown, retry = true): Promise<Response> {
  const r = await fetch(path, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json", "X-Flect-Token": await sessionToken() },
    body: JSON.stringify(body ?? {}),
  });
  if (r.status === 403 && retry) {
    await sessionToken(true);
    return post(path, body, false);
  }
  return r;
}

async function failure(r: Response): Promise<AiError> {
  let msg = `Flect answered HTTP ${r.status}`;
  try {
    const text = await r.text();
    try {
      msg = (JSON.parse(text) as { detail?: string }).detail || msg;
    } catch {
      msg = text || msg;
    }
  } catch {
    /* keep the status line */
  }
  return new AiError(msg, r.status);
}

/** Run a turn and hand every streamed event to `onEvent` as it arrives. */
export async function streamTurn(path: "/api/ai/chat" | "/api/ai/brief", body: object, onEvent: (e: AiEvent) => void) {
  const r = await post(path, body);
  if (!r.ok || !r.body) throw await failure(r);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) onEvent(JSON.parse(line) as AiEvent);
    }
  }
  if (buf.trim()) onEvent(JSON.parse(buf) as AiEvent);
}

export const fetchMessages = () => api<{ messages: AiMessage[] } & AiCounts>("/api/ai/messages");

export async function approveAction(id: number): Promise<{ ok: boolean; message: AiMessage }> {
  const r = await post(`/api/ai/actions/${id}/approve`);
  if (!r.ok) throw await failure(r);
  return r.json();
}

export async function dismissAction(id: number): Promise<AiAction> {
  const r = await post(`/api/ai/actions/${id}/dismiss`);
  if (!r.ok) throw await failure(r);
  return r.json();
}

/** The operator's clock, so Flect can greet them for the time of day and speak times in their zone. */
export const localContext = () => ({
  local_time: new Date().toLocaleString("en-GB", { weekday: "long", hour: "numeric", minute: "2-digit" }),
  tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
});
