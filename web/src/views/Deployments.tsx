import { GitCommitHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCore, usePoll, type Deployment } from "@/lib/api";
import { num, sentence, when } from "@/lib/format";
import { TRIGGER, stateTone } from "@/lib/vocab";
import { Empty, Panel, Rack, RackCell, Sha, StateTag, Tag, Time, toneClass } from "@/components/flect/bits";

export function DeploymentsView() {
  const { overview } = useCore();
  const { data: rows } = usePoll<Deployment[]>("/api/deployments");
  const prod = rows?.find((r) => r.env === "prod");
  const lkg = rows?.find((r) => r.env === "prod" && r.state === "lkg");

  return (
    <div className="space-y-6">
      <Rack className="md:grid-cols-3">
        <RackCell>
          <div className="text-[13px] text-muted-foreground">Running in production</div>
          <div className="mt-3 flex items-center gap-2">{prod ? <Sha sha={prod.sha} className="px-2 py-1 text-[15px]" /> : <span className="text-faint">Unknown</span>}</div>
          {prod && <div className="mt-2 text-[12.5px] text-muted-foreground">{TRIGGER[prod.trigger] ?? sentence(prod.trigger)}</div>}
        </RackCell>
        <RackCell>
          <div className="text-[13px] text-muted-foreground">Rollback target</div>
          <div className="mt-3 flex items-center gap-2">{lkg ? <Sha sha={lkg.sha} className="px-2 py-1 text-[15px]" /> : <span className="text-muted-foreground">Not set yet</span>}</div>
          <div className="mt-2 text-[12.5px] text-muted-foreground">{lkg ? `Last known good since ${when(lkg.healthy_since ?? lkg.started_ts)}` : "A build becomes the target after 10 healthy minutes"}</div>
        </RackCell>
        <RackCell>
          <div className="text-[13px] text-muted-foreground">Deploys in the last 24 hours</div>
          <div className="readout mt-3 text-[34px]">{num(overview?.deploys_24h ?? 0)}</div>
          <div className="mt-2 text-[12.5px] text-muted-foreground">
            {overview?.rollbacks_24h ? `${num(overview.rollbacks_24h)} of them automatic rollbacks` : "None of them were rollbacks"}
          </div>
        </RackCell>
      </Rack>

      <Panel title="History">
        {rows === undefined ? (
          <div className="h-32" />
        ) : !rows.length ? (
          <Empty icon={<GitCommitHorizontal />} title="No deployments recorded yet">
            Flect records production's commit when it starts and every change after that, whoever made it.
          </Empty>
        ) : (
          <ol className="px-5 py-5">
            {rows.map((r, idx) => (
              <li key={r.id} className="relative grid grid-cols-[18px_1fr] gap-x-4 pb-6 last:pb-0">
                {idx < rows.length - 1 && <span className="absolute top-4 bottom-0 left-[8.5px] w-px bg-border" aria-hidden />}
                <span className={cn("mt-1 flex size-[18px] items-center justify-center", toneClass(stateTone(r.state)))} aria-hidden>
                  <span className="size-3 rounded-full border-2 border-[var(--tone)] bg-card" />
                </span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    <Tag tone={r.env === "prod" ? "iris" : "mute"}>{r.env === "prod" ? "Production" : r.env.toUpperCase()}</Tag>
                    <span className="font-[600]">{TRIGGER[r.trigger] ?? sentence(r.trigger)}</span>
                    <StateTag state={r.state} />
                    <Time v={r.started_ts} className="ml-auto text-[12.5px] text-muted-foreground" />
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
                    <Sha sha={r.sha} />
                    {r.previous_sha && (
                      <>
                        replaced <Sha sha={r.previous_sha} className="opacity-75" />
                      </>
                    )}
                    {r.notes && r.notes.toLowerCase() !== (TRIGGER[r.trigger] ?? "").toLowerCase() && <span className="min-w-0">{r.notes}</span>}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
      </Panel>
    </div>
  );
}
