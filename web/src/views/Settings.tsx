import { GitBranch, GitPullRequest, KeyRound, LifeBuoy, ScanSearch, ShieldHalf, type LucideIcon } from "lucide-react";
import { useCore } from "@/lib/api";
import { dur, num } from "@/lib/format";
import { DEP_LABEL, GUARDS, depOk, modeLabel, modeTone, type Dep } from "@/lib/vocab";
import { Code, CopyCommand, Facts, Led, Panel } from "@/components/flect/bits";

const ICON: Record<string, LucideIcon> = { prguard: GitPullRequest, dos: ShieldHalf, crash: LifeBuoy, vapt: ScanSearch, cicd: GitBranch, keys: KeyRound };

export function SettingsView() {
  const core = useCore();
  const { status: st, meta: m } = core;
  const c = st?.capabilities ?? {};
  const dep = (d: Dep, text: string) => (
    <span className="flex items-center gap-2">
      <Led tone={depOk(core, d) ? "ok" : "crit"} />
      {text}
    </span>
  );

  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <div className="space-y-6">
        <Panel title="Guards">
          <ul className="divide-y">
            {GUARDS.map((g) => {
              const Icon = ICON[g.id];
              const mode = st?.modes?.[g.id];
              return (
                <li key={g.id} className="flex items-center gap-4 px-5 py-3.5">
                  <Icon className="size-[18px] shrink-0 text-faint" strokeWidth={1.8} />
                  <div className="min-w-0 flex-1">
                    <div className="font-[580]">{g.name}</div>
                    <div className="text-[12.5px] text-muted-foreground">{g.does}</div>
                  </div>
                  <span className="flex items-center gap-2 text-[13px]">
                    <Led tone={modeTone(mode)} />
                    {modeLabel(mode)}
                  </span>
                </li>
              );
            })}
          </ul>
        </Panel>
        <Panel title="Change Flect from the Spark">
          <div className="space-y-2 p-5">
            <p className="mb-3 text-[13.5px] text-muted-foreground">
              This dashboard only reads. Modes, pauses and unblocks go through the <Code>flect</Code> command, so every change is deliberate and lands in the audit log.
            </p>
            <CopyCommand cmd="flect mode crash observe" note="Watch without acting" />
            <CopyCommand cmd="flect mode crash enforce" note="Act again" />
            <CopyCommand cmd='flect pause "maintenance"' note="Stop GitHub writes" />
            <CopyCommand cmd="flect resume" />
            <CopyCommand cmd="flect status" />
          </div>
        </Panel>
      </div>
      <Panel title="Environment">
        <Facts
          className="px-5 py-2"
          rows={[
            [
              "Protecting",
              m && (
                <span>
                  <b className="font-[620]">{m.target.toUpperCase()}</b> from{" "}
                  <a href={m.repo_url} target="_blank" rel="noopener" className="underline decoration-line-strong underline-offset-[3px]">
                    {m.repo}
                  </a>
                </span>
              ),
            ],
            ["Production", m && <Code>{m.prod_url}</Code>],
            [
              "UAT",
              m && (
                <span>
                  <Code>{m.uat_url}</Code> <span className="text-muted-foreground">({c.uat === "configured" ? "starts on demand" : c.uat})</span>
                </span>
              ),
            ],
            [
              "Branches",
              m && (
                <span>
                  features into <Code>{m.feature_base}</Code>, releases into <Code>{m.prod_branch}</Code>
                </span>
              ),
            ],
            ["Sandbox", dep("sandbox", c.sandbox ?? "unknown")],
            ["Firewall", dep("nft", c.nft ?? "unknown")],
            [DEP_LABEL.llm, dep("llm", c.llm === "ok" ? "online" : c.llm ?? "unknown")],
            ["GitHub", dep("github", st?.writes_paused ? `paused: ${st.writes_paused}` : "writes enabled")],
            ["Log lines read", `${num(c.log_lines)}${c.stale_lines_skipped ? `, ${num(c.stale_lines_skipped)} stale lines skipped` : ""}`],
            ["Dashboard", m && <Code>{`${m.dashboard.host}:${m.dashboard.port}`}</Code>],
            ["Flect", m && `${m.version}, up ${m.started ? dur(Date.now() / 1000 - m.started) : "—"}`],
          ]}
        />
      </Panel>
    </div>
  );
}
