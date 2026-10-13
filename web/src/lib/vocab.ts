/* Flect's domain vocabulary: what each state is called and which tone it carries. */
import type { Action, Core } from "./api";
import { sentence } from "./format";
import type { ViewId } from "./route";

export type Tone = "ok" | "warn" | "high" | "crit" | "iris" | "mute";

export const SEVERITY_TONE: Record<string, Tone> = { critical: "crit", high: "high", medium: "warn", low: "mute", info: "mute" };
export const severityTone = (s: string | null | undefined): Tone => SEVERITY_TONE[s ?? ""] ?? "mute";

const STATE_TONE: Record<string, Tone> = {
  open: "crit",
  mitigating: "warn",
  mitigated: "iris",
  needs_human: "warn",
  resolved: "ok",
  passed: "ok",
  merged: "iris",
  approved: "ok",
  blocked: "crit",
  scanning: "mute",
  testing: "mute",
  error: "crit",
  healthy: "ok",
  lkg: "ok",
  failed: "crit",
  deploying: "mute",
  verifying: "mute",
  rolled_back: "warn",
  ok: "ok",
  failing: "crit",
  expired: "crit",
  "T-1d": "crit",
  "T-3d": "warn",
  "T-7d": "warn",
  "T-30d": "warn",
};
export const stateTone = (s: string | null | undefined): Tone => STATE_TONE[s ?? ""] ?? "mute";

const STATE_LABEL: Record<string, string> = {
  needs_human: "Needs a human",
  lkg: "Last known good",
  rolled_back: "Rolled back",
  "T-1d": "Expires in a day",
  "T-3d": "Expires in 3 days",
  "T-7d": "Expires in a week",
  "T-30d": "Expires in a month",
  ok: "Healthy",
};
export const stateLabel = (s: string | null | undefined) => STATE_LABEL[s ?? ""] ?? sentence(s);

export const INCIDENT_KIND: Record<string, string> = {
  expiry: "Keys and services",
  crash: "Production crash",
  dos: "Abusive traffic",
  anomaly: "Log anomaly",
  poison_pr: "PR guard",
  vapt: "VAPT",
  deploy_fail: "Deployment",
};
export const incidentKind = (k: string) => INCIDENT_KIND[k] ?? sentence(k);

const DECISION: Record<string, string> = {
  block_ip: "Blocked an IP",
  unblock_ip: "Unblocked an IP",
  merge_to_uat: "Merged into UAT",
  merge_hotfix: "Merged a hotfix",
  comment_pr: "Commented on a PR",
  close_pr: "Closed a PR",
  label_pr: "Labelled a PR",
  restart_prod: "Restarted production",
  open_hotfix_pr: "Opened a hotfix PR",
  push_hotfix_branch: "Pushed a hotfix branch",
  set_mode: "Changed a guard's mode",
  hotfix_attempt: "Started a fix-forward",
  flood_mode_on: "Turned flood mode on",
  flood_mode_off: "Turned flood mode off",
  resolve_false_positives: "Closed false positives",
  comment_vapt: "Posted a VAPT report",
  open_backmerge_pr: "Opened a back-merge PR",
};
export function decisionText(a: Pick<Action, "decision">): string {
  const d = a.decision || "";
  if (d.startsWith("deploy_prod:")) return `Deployed to production (${d.split(":")[1].replace(/_/g, " ")})`;
  if (d.startsWith("status:")) return `Set the ${d.slice(7)} check`;
  return DECISION[d] ?? sentence(d);
}

/** done / would-do (observe mode) / failed / still running */
export function actionOutcome(a: Pick<Action, "mode" | "ok">): { tone: Tone; label: string } {
  if (a.mode === "observe") return { tone: "warn", label: "Would do" };
  if (a.ok === 0) return { tone: "crit", label: "Failed" };
  if (a.ok == null) return { tone: "mute", label: "Started" };
  return { tone: "iris", label: "Done" };
}

export const TRIGGER: Record<string, string> = {
  bootstrap: "First seen by Flect",
  manual: "Changed outside Flect",
  human_merge: "Release merged by a human",
  hotfix: "Crash hotfix",
  rollback: "Automatic rollback",
  restart: "Restart",
  uat_merge: "Merged into UAT",
};

export const KEY_KIND: Record<string, string> = {
  github_pat: "GitHub token",
  tls_cert: "TLS certificate",
  jwt: "JWT",
  service: "Service",
  api_key: "API key",
};

export const REPORT_KIND: Record<string, { label: string; tone: Tone }> = {
  vapt: { label: "VAPT", tone: "iris" },
  prguard: { label: "PR guard", tone: "mute" },
  incident: { label: "Incident", tone: "mute" },
};

/* ── guards (capabilities) ──────────────────────────────────────────── */
export type Dep = "sandbox" | "llm" | "nft" | "uat" | "github_poll" | "github";

export const DEP_LABEL: Record<Dep, string> = {
  sandbox: "Sandbox",
  llm: "DeepSeek",
  nft: "Firewall",
  uat: "UAT",
  github_poll: "GitHub",
  github: "GitHub token",
};

export interface Guard {
  id: string;
  name: string;
  does: string;
  view: ViewId;
  deps: Dep[];
}

export const GUARDS: Guard[] = [
  { id: "prguard", name: "PR guard", does: "Reviews every pull request in a sandbox", view: "prs", deps: ["sandbox", "llm"] },
  { id: "dos", name: "Traffic shield", does: "Blocks abusive IPs at the firewall", view: "traffic", deps: ["nft"] },
  { id: "crash", name: "Crash recovery", does: "Rolls back, then fixes forward", view: "deploys", deps: ["sandbox", "llm"] },
  { id: "vapt", name: "Release VAPT", does: "Attacks UAT before a release ships", view: "reports", deps: ["uat", "llm"] },
  { id: "cicd", name: "CI/CD", does: "Merges green PRs and tracks deploys", view: "deploys", deps: ["github_poll"] },
  { id: "keys", name: "Keys and services", does: "Watches expiry dates and dependencies", view: "keys", deps: ["github"] },
];

export function depOk(core: Core, dep: Dep): boolean {
  if (dep === "github") return !core.status?.writes_paused;
  const v = core.status?.capabilities?.[dep];
  return v === "ok" || v === "configured";
}

export const modeTone = (m: string | undefined): Tone => (m === "enforce" ? "ok" : m === "observe" ? "warn" : "mute");
export const modeLabel = (m: string | undefined) => (m === "enforce" ? "Enforcing" : m === "observe" ? "Observing" : "Off");
