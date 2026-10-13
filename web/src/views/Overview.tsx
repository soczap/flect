import type { ReactNode } from "react";
import {
  Cpu,
  GitBranch,
  GitPullRequest,
  KeyRound,
  LifeBuoy,
  Pause,
  ScanSearch,
  ShieldCheck,
  ShieldHalf,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useCore, usePoll, type Action, type Core, type Incident } from "@/lib/api";
import { dur, num, plural, since } from "@/lib/format";
import { href } from "@/lib/route";
import { DEP_LABEL, GUARDS, depOk, modeLabel, modeTone, type Guard, type Tone } from "@/lib/vocab";
import { Empty, Facts, GitHubLink, Led, Panel, Readout, Sha, Time, stretchedLink, toneClass } from "@/components/flect/bits";
import { AvailabilityStrip, Heartbeat } from "@/components/flect/Heartbeat";
import { ActionTimeline, IncidentRow } from "@/components/flect/feeds";
import { ChartKey, TrafficChart } from "@/components/flect/TrafficChart";

/* ── posture ─────────────────────────────────────────────────────────── */
function posture(core: Core, open: Incident[]): { tone: Tone; headline: string; context: ReactNode } {
  const { status, overview: o, meta } = core;
  const h = status?.health;
  const target = (meta?.target ?? "vigil").toUpperCase();
  if (!status || !o) return { tone: "mute", headline: "Checking production…", context: "Reading Flect's latest state." };

  const modes = Object.values(status.modes ?? {});
  const enforcing = modes.filter((m) => m === "enforce").length;
  const observing = modes.filter((m) => m === "observe").length;
  const guards =
    enforcing === modes.length
      ? `All ${modes.length === 6 ? "six" : modes.length} guards are enforcing.`
      : `${enforcing} of ${modes.length} guards are enforcing${observing ? `, ${observing} only observing` : ""}.`;

  if (!h?.http_ok) {
    return {
      tone: "crit",
      headline: "Production is not responding.",
      context: (
        <>
          {target}'s health check fails with <span className="font-[600] text-foreground">{h?.error || `HTTP ${h?.http_status ?? "error"}`}</span>. Crash
          recovery is {modeLabel(status.modes.crash).toLowerCase()}.
        </>
      ),
    };
  }

  if (open.length) {
    const top = [...open].sort((a, b) => (a.severity === "critical" ? -1 : 0) - (b.severity === "critical" ? -1 : 0))[0];
    const age = since(top.opened_ts);
    return {
      tone: "warn",
      headline: `Production is up. ${open.length === 1 ? "One thing needs" : `${num(open.length)} things need`} you.`,
      context: (
        <>
          <a href={href("incidents", top.id)} className="font-[600] text-foreground underline decoration-line-strong underline-offset-4 hover:decoration-foreground">
            {top.title}
          </a>{" "}
          has been open for {dur(age)}
          {top.github_issue ? (
            <>
              {" "}
              and is tracked in issue <GitHubLink kind="issues" n={top.github_issue} />
            </>
          ) : null}
          .{open.length > 1 ? ` ${plural(open.length - 1, "other incident is", "other incidents are")} open too.` : ""} {guards}
        </>
      ),
    };
  }

  const healthy = o.had_failure_1h && o.healthy_since ? `has been healthy for ${dur(o.now - o.healthy_since)} since its last failed check` : h.uptime_s != null ? `has answered every health check for ${dur(h.uptime_s)}` : "is answering health checks";
  return { tone: "ok", headline: "Production is protected.", context: `${target} ${healthy}. ${guards}` };
}

function VitalSigns({ open }: { open: Incident[] }) {
  const core = useCore();
  const { status, overview: o, history } = core;
  const p = posture(core, open);
  const h = status?.health;
  const hist = history?.health ?? [];
  const traceTone: Tone = !status ? "mute" : h?.http_ok ? "ok" : "crit";

  return (
    <section className="overflow-hidden rounded-2xl border bg-card" aria-labelledby="posture">
      <div className="px-5 pt-6 pb-6 sm:px-7 lg:px-8 lg:pt-8">
        <div className="flex items-start gap-4">
          <Led tone={p.tone} className="mt-[0.62em] scale-150 sm:mt-[0.75em]" />
          <div className="min-w-0">
            <h2 id="posture" className="display max-w-[22ch] text-[clamp(32px,4.4vw,54px)]">
              {p.headline}
            </h2>
            <p className="mt-3 max-w-[72ch] text-[15px] leading-relaxed text-muted-foreground">{p.context}</p>
          </div>
        </div>
      </div>
      <div className="grid border-t lg:grid-cols-[minmax(0,1fr)_minmax(300px,30%)]">
        <div className="ecg-paper min-w-0 pb-4">
          <Heartbeat hist={hist} tone={traceTone} height={204} />
          <div className="mt-2 pr-[14px] pl-4">
            <AvailabilityStrip hist={hist} />
            <div className="mt-2 flex justify-between text-[11.5px] text-faint">
              <span>1 hour ago</span>
              <span className="hidden sm:inline">30 minutes ago</span>
              <span>Now</span>
            </div>
          </div>
        </div>
        <dl className="grid grid-cols-2 border-t lg:border-t-0 lg:border-l [&>div]:flex [&>div]:flex-col [&>div]:justify-center [&>div]:p-5 [&>div:nth-child(-n+2)]:border-b [&>div:nth-child(odd)]:border-r">
          <div>
            <Readout
              tone={traceTone}
              value={h?.http_ok ? num(h.latency_ms, 0) : "—"}
              unit={h?.http_ok ? "ms" : undefined}
              label={h?.http_ok ? "Responding now" : "No response"}
            />
          </div>
          <div>
            <Readout value={num(o?.latency_ms_avg, 0)} unit="ms" label="Average this hour" />
          </div>
          <div>
            <Readout
              value={o?.availability_1h != null ? num(o.availability_1h, o.availability_1h === 100 ? 0 : 2) : "—"}
              unit="%"
              label="Available this hour"
              tone={o?.availability_1h != null && o.availability_1h < 99 ? "warn" : undefined}
            />
          </div>
          <div>
            <Readout value={h?.uptime_s != null ? dur(h.uptime_s) : "—"} label={h?.n_restarts ? `Up, ${plural(h.n_restarts, "restart")}` : "Up since last start"} />
          </div>
        </dl>
      </div>
    </section>
  );
}

/* ── guards rack ─────────────────────────────────────────────────────── */
const GUARD_ICON: Record<string, LucideIcon> = {
  prguard: GitPullRequest,
  dos: ShieldHalf,
  crash: LifeBuoy,
  vapt: ScanSearch,
  cicd: GitBranch,
  keys: KeyRound,
};

function guardMetric(id: string, core: Core): { value: ReactNode; unit?: string; label: ReactNode; sub?: ReactNode; tone?: Tone } {
  const o = core.overview;
  const st = core.status;
  const prs = o?.prs ?? {};
  switch (id) {
    case "prguard": {
      const total = Object.values(prs).reduce((a, b) => a + b, 0);
      const waiting = prs.needs_human ?? 0;
      return {
        value: num(total),
        label: "pull requests reviewed",
        sub: total ? `${num(prs.blocked ?? 0)} blocked, ${num(waiting)} waiting for a human` : "Reviews start when a PR targets UAT",
        tone: waiting ? "warn" : undefined,
      };
    }
    case "dos": {
      const d = st?.dos;
      return {
        value: num(d?.global_rps, 1),
        unit: "req/s",
        label: d ? `baseline ${num(d.baseline_rps, 1)}` : "request rate",
        sub: d?.flooding ? <span className="font-[600] text-crit">Flood mode is on</span> : o?.active_blocks ? `${plural(o.active_blocks, "IP")} blocked now` : "No IPs blocked right now",
        tone: d?.flooding ? "crit" : undefined,
      };
    }
    case "crash":
      return {
        value: num(o?.rollbacks_24h ?? 0),
        label: "rollbacks in 24 hours",
        sub: st?.lkg ? (
          <span className="flex items-center gap-1.5">
            Rolls back to <Sha sha={st.lkg.sha} />
          </span>
        ) : (
          "Rollback target after 10 healthy minutes"
        ),
      };
    case "vapt":
      return { value: num(o?.reports_by_kind?.vapt ?? 0), label: "VAPT reports", sub: "UAT starts only for a scan" };
    case "cicd": {
      const l = o?.last_deploy;
      return {
        value: num(o?.deploys_24h ?? 0),
        label: "deploys in 24 hours",
        sub: l ? (
          <span className="flex items-center gap-1.5">
            Last <Sha sha={l.sha} /> <Time v={l.started_ts} />
          </span>
        ) : (
          "No deployments recorded yet"
        ),
      };
    }
    case "keys": {
      const k = o?.keys ?? {};
      const total = Object.values(k).reduce((a, b) => a + b, 0);
      const bad = (k.failing ?? 0) + (k.expired ?? 0);
      return {
        value: total ? `${num(total - bad)}/${num(total)}` : "—",
        label: "checks passing",
        sub: o?.next_expiry ? `Next expiry in ${dur(o.next_expiry.days_left * 86400)}` : "No expiry dates found",
        tone: bad ? "crit" : undefined,
      };
    }
  }
  return { value: "—", label: "" };
}

function GuardCell({ g, core }: { g: Guard; core: Core }) {
  const Icon = GUARD_ICON[g.id];
  const mode = core.status?.modes?.[g.id];
  const m = guardMetric(g.id, core);
  return (
    <div className="group relative flex min-h-[188px] flex-col bg-card p-5 transition-colors hover:bg-accent/45">
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 size-[18px] shrink-0 text-faint transition-colors group-hover:text-foreground" strokeWidth={1.8} />
        <div className="min-w-0">
          <a href={href(g.view)} className={cn("block font-[620] no-underline", stretchedLink)}>
            {g.name}
          </a>
          <div className="text-[12.5px] text-muted-foreground">{g.does}</div>
        </div>
        <span className="ml-auto flex shrink-0 items-center gap-1.5 pt-0.5 text-[12px] text-muted-foreground">
          <Led tone={modeTone(mode)} />
          {modeLabel(mode)}
        </span>
      </div>
      <div className="mt-auto pt-5">
        <div className={cn("flex items-baseline gap-2", m.tone && toneClass(m.tone))}>
          <span className={cn("readout text-[34px]", m.tone && "text-[var(--tone)]")}>{m.value}</span>
          {m.unit && <span className="text-[13px] font-[520] text-muted-foreground">{m.unit}</span>}
          <span className="text-[13px] text-muted-foreground">{m.label}</span>
        </div>
        {m.sub && <div className="mt-1.5 text-[12.5px] text-muted-foreground">{m.sub}</div>}
      </div>
      <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 border-t border-dashed pt-3 text-[12px]">
        {g.deps.map((d) => {
          const ok = depOk(core, d);
          return (
            <span key={d} className={cn("flex items-center gap-1.5", ok ? "text-muted-foreground" : "font-[600] text-crit")}>
              <Led tone={ok ? "ok" : "crit"} className="scale-75" />
              {DEP_LABEL[d]}
              {!ok && " down"}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function GuardsRack() {
  const core = useCore();
  const modes = Object.values(core.status?.modes ?? {});
  const enforcing = modes.filter((m) => m === "enforce").length;
  return (
    <Panel
      title="Guards"
      aside={
        modes.length > 0 && (
          <span className="flex items-center gap-2">
            <Led tone={enforcing === modes.length ? "ok" : "warn"} />
            {enforcing === modes.length ? "All enforcing" : `${enforcing} of ${modes.length} enforcing`}
          </span>
        )
      }
      className="overflow-hidden"
    >
      <div className="grid gap-px bg-border sm:grid-cols-2 xl:grid-cols-3">
        {GUARDS.map((g) => (
          <GuardCell key={g.id} g={g} core={core} />
        ))}
      </div>
    </Panel>
  );
}

/* ── side panels ─────────────────────────────────────────────────────── */
function DeepSeekPanel() {
  const { status, overview } = useCore();
  const c = status?.capabilities ?? {};
  const q = c.llm_queue ?? { queued: 0, in_flight: 0 };
  const l = overview?.llm_24h;
  const online = c.llm === "ok";
  return (
    <Panel
      title={
        <span className="flex items-center gap-2">
          <Cpu className="size-4 text-faint" />
          DeepSeek
          <span className="font-[450] text-muted-foreground">on this Spark</span>
        </span>
      }
      aside={
        <span className="flex items-center gap-2">
          <Led tone={online ? "ok" : "crit"} pulse={online && q.in_flight > 0} />
          {online ? (q.in_flight ? "Thinking" : "Online") : "Offline"}
        </span>
      }
    >
      <Facts
        className="px-5 py-2"
        rows={[
          ["Queue", q.queued || q.in_flight ? `${num(q.in_flight)} running, ${num(q.queued)} waiting` : "Idle"],
          ["Calls in 24 hours", l?.calls ? `${num(l.calls)} (${num(l.ok ?? 0)} succeeded)` : "None"],
          ["Average call", l?.avg_s ? `${num(l.avg_s, 1)} s` : "—"],
          ["Tokens written", num(l?.out_tokens ?? 0)],
        ]}
      />
    </Panel>
  );
}

export function OverviewView() {
  const core = useCore();
  const { data: incidents } = usePoll<Incident[]>("/api/incidents?limit=100");
  const { data: actions } = usePoll<Action[]>("/api/actions?limit=12");
  const open = (incidents ?? []).filter((i) => i.state !== "resolved");
  const resolved = (incidents ?? []).filter((i) => i.state === "resolved").slice(0, 4);
  const paused = core.status?.writes_paused;

  return (
    <div className="space-y-6">
      {paused && (
        <div className="flex items-center gap-3 rounded-xl border border-[color-mix(in_oklab,var(--warn)_45%,var(--border))] bg-[color-mix(in_oklab,var(--warn)_9%,var(--card))] px-4 py-3 text-[13.5px]">
          <Pause className="size-4 shrink-0 text-warn" />
          <span>
            <b className="font-[620]">GitHub actions are paused:</b> {paused}. Detection and IP blocking carry on. Resume with <code className="font-mono text-[12.5px]">flect resume</code>.
          </span>
        </div>
      )}
      <VitalSigns open={open} />
      <GuardsRack />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-6">
          <Panel
            title="Needs you"
            aside={
              <a href={href("incidents")} className="underline decoration-line-strong underline-offset-4 hover:text-foreground">
                All incidents
              </a>
            }
          >
            {incidents === undefined ? (
              <div className="h-24" />
            ) : open.length ? (
              <div className="divide-y">{open.map((i) => <IncidentRow key={i.id} i={i} />)}</div>
            ) : (
              <Empty icon={<ShieldCheck />} title="Nothing needs you">
                {core.overview?.resolved_24h ? `Flect closed ${plural(core.overview.resolved_24h, "incident")} in the last 24 hours.` : "Flect will raise anything that needs a decision here."}
              </Empty>
            )}
            {resolved.length > 0 && (
              <>
                <div className="border-t bg-sunken/60 px-5 py-2 text-[12.5px] text-muted-foreground">Resolved recently</div>
                <div className="divide-y border-t">{resolved.map((i) => <IncidentRow key={i.id} i={i} />)}</div>
              </>
            )}
          </Panel>
          <Panel title="Traffic this hour" aside={<ChartKey />}>
            <div className="px-3 pt-3 pb-2">
              <TrafficChart traffic={core.history?.traffic ?? []} height={210} />
            </div>
          </Panel>
        </div>
        <div className="min-w-0 space-y-6">
          <Panel
            title="What Flect did"
            aside={
              <a href={href("audit")} className="underline decoration-line-strong underline-offset-4 hover:text-foreground">
                Audit log
              </a>
            }
          >
            {actions === undefined ? (
              <div className="h-24" />
            ) : actions.length ? (
              <div className="px-5 py-5">
                <ActionTimeline actions={actions.slice(0, 7)} dense />
              </div>
            ) : (
              <Empty title="No actions yet">Flect acts when a guard in enforce mode sees something. Observing guards log what they would have done.</Empty>
            )}
          </Panel>
          <DeepSeekPanel />
        </div>
      </div>
    </div>
  );
}
