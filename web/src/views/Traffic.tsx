import { ShieldCheck } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCore, usePoll, type Block } from "@/lib/api";
import { dur, num, plural, toMs } from "@/lib/format";
import { Code, CopyCommand, Empty, Led, Panel, Rack, RackCell, Readout, Tag, Time, tableClass } from "@/components/flect/bits";
import { ChartKey, TrafficChart } from "@/components/flect/TrafficChart";

function blockState(b: Block, now: number) {
  const live = b.active && (toMs(b.expires_ts) ?? 0) > now;
  if (live) return <Tag tone="crit" lamp>Blocked, {dur(((toMs(b.expires_ts) ?? now) - now) / 1000)} left</Tag>;
  if (b.mode === "observe") return <Tag tone="warn">Would block</Tag>;
  return <Tag tone="mute">{b.unblocked_by ? `Unblocked by ${b.unblocked_by}` : "Expired"}</Tag>;
}

export function TrafficView() {
  const { status, meta, history } = useCore();
  const { data: blocks } = usePoll<Block[]>("/api/blocks");
  const d = status?.dos;
  const now = Date.now();
  const active = (blocks ?? []).filter((b) => b.active && (toMs(b.expires_ts) ?? 0) > now);

  return (
    <div className="space-y-6">
      <Rack className="sm:grid-cols-3">
        <RackCell>
          <Readout value={num(d?.global_rps, 2)} unit="req/s" label={`Right now, against a baseline of ${num(d?.baseline_rps, 2)}`} />
        </RackCell>
        <RackCell>
          <div className="flex items-center gap-2.5">
            <Led tone={d?.flooding ? "crit" : "ok"} pulse={d?.flooding} className="scale-125" />
            <span className={d?.flooding ? "readout text-[34px] text-crit" : "readout text-[34px]"}>{d?.flooding ? "Flood mode" : "Normal"}</span>
          </div>
          <div className="mt-1.5 text-[13px] text-muted-foreground">
            {d?.flooding ? "Per-IP limits are four times stricter until the flood passes" : "Per-IP limits drop fourfold during a distributed flood"}
          </div>
        </RackCell>
        <RackCell>
          <Readout value={num(active.length)} label={`IPs blocked now, ${plural(blocks?.length ?? 0, "block")} in history`} tone={active.length ? "crit" : undefined} />
        </RackCell>
      </Rack>

      <Panel title="Requests per second this hour" aside={<ChartKey />}>
        <div className="px-3 pt-4 pb-2">
          <TrafficChart traffic={history?.traffic ?? []} height={280} />
        </div>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Busiest sources, last 60 seconds">
          {d?.top_talkers_60s?.length ? (
            <Table className={tableClass}>
              <TableHeader>
                <TableRow>
                  <TableHead>IP</TableHead>
                  <TableHead className="text-right">Requests</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.top_talkers_60s.map(([ip, n]) => (
                  <TableRow key={ip}>
                    <TableCell>
                      <Code>{ip}</Code>
                    </TableCell>
                    <TableCell className="text-right num">{num(n)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <Empty title="No outside traffic in the last minute">
              {d?.allowlisted_requests ? `${num(d.allowlisted_requests)} requests came from allowlisted sources, which are never listed or blocked.` : "Allowlisted sources are never listed or blocked."}
            </Empty>
          )}
        </Panel>
        <Panel title="Never blocked">
          <div className="flex flex-wrap gap-2 p-5">
            {(meta?.allowlist ?? []).map((c) => (
              <span key={c} className="rounded-md border bg-sunken px-2 py-1">
                <Code>{c}</Code>
              </span>
            ))}
          </div>
          <p className="border-t px-5 py-3 text-[13px] text-muted-foreground">Enforced twice: by Flect, and again by the root-owned firewall helper, so a bug in one cannot lock you out.</p>
        </Panel>
      </div>

      <Panel title="Blocks">
        {blocks === undefined ? (
          <div className="h-32" />
        ) : !blocks.length ? (
          <Empty icon={<ShieldCheck />} title="No IP has ever been blocked">
            Traffic shield blocks an IP at the firewall when it breaks a rule, starting at 15 minutes and growing for repeat offenders.
          </Empty>
        ) : (
          <Table className={tableClass}>
            <TableHeader>
              <TableRow>
                <TableHead>IP</TableHead>
                <TableHead>Rule</TableHead>
                <TableHead className="hidden md:table-cell">Why</TableHead>
                <TableHead className="hidden sm:table-cell">For</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {blocks.map((b) => (
                <TableRow key={b.id}>
                  <TableCell>
                    <Code>{b.ip}</Code>
                  </TableCell>
                  <TableCell>
                    <Code className="text-muted-foreground">{b.rule_id}</Code>
                  </TableCell>
                  <TableCell className="hidden max-w-[320px] whitespace-normal text-muted-foreground md:table-cell">{b.reason}</TableCell>
                  <TableCell className="hidden sm:table-cell num">{b.ttl}</TableCell>
                  <TableCell>{blockState(b, now)}</TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    <Time v={b.created_ts} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <div className="border-t p-4">
          <CopyCommand cmd="flect unblock <ip>" note="Run on the Spark" />
        </div>
      </Panel>
    </div>
  );
}
