import { KeyRound } from "lucide-react";
import { cn } from "@/lib/utils";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePoll, type KeyRow } from "@/lib/api";
import { dur, num, when } from "@/lib/format";
import { KEY_KIND, stateTone } from "@/lib/vocab";
import { Code, Empty, Led, Panel, StateTag, Time, tableClass, toneClass } from "@/components/flect/bits";

/** Time left on a one-year scale; the bar turns sodium inside 30 days and flare inside 3. */
function TimeLeft({ days }: { days: number }) {
  const tone = days <= 3 ? "crit" : days <= 30 ? "warn" : "ok";
  const pct = Math.max(2, Math.min(100, (days / 365) * 100));
  return (
    <div className={cn("flex items-center gap-3", toneClass(tone))} title={`${num(days, 1)} days left`}>
      <div className="h-1.5 w-full max-w-40 overflow-hidden rounded-full bg-border">
        <div className="h-full rounded-full bg-[var(--tone)]" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[13px] whitespace-nowrap num">{dur(days * 86400)}</span>
    </div>
  );
}

export function KeysView() {
  const { data: rows } = usePoll<KeyRow[]>("/api/keys");
  const expiring = (rows ?? []).filter((r) => r.days_left != null);
  const services = (rows ?? []).filter((r) => r.days_left == null);

  return (
    <div className="space-y-6">
      <Panel title="Expiring credentials and certificates" aside={<span className="hidden sm:inline">Alerts 7, 3 and 1 days out; 30 for certificates</span>}>
        {rows === undefined ? (
          <div className="h-28" />
        ) : !expiring.length ? (
          <Empty icon={<KeyRound />} title="Nothing with an expiry date found">
            Flect reads expiry from GitHub tokens, TLS certificates and JWTs it can see.
          </Empty>
        ) : (
          <Table className={tableClass}>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead className="hidden md:table-cell">Kind</TableHead>
                <TableHead className="hidden sm:table-cell">Expires</TableHead>
                <TableHead className="w-[30%]">Time left</TableHead>
                <TableHead className="text-right">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {expiring.map((r) => (
                <TableRow key={r.name}>
                  <TableCell className="max-w-[340px] whitespace-normal">
                    <div className="font-[580]">{r.name}</div>
                    <Code className="mt-0.5 block truncate text-[12px] text-muted-foreground">{r.location}</Code>
                  </TableCell>
                  <TableCell className="hidden md:table-cell">{KEY_KIND[r.kind] ?? r.kind}</TableCell>
                  <TableCell className="hidden sm:table-cell num">{when(r.expires_ts)}</TableCell>
                  <TableCell>
                    <TimeLeft days={r.days_left!} />
                  </TableCell>
                  <TableCell className="text-right">
                    <StateTag state={r.alert_level} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Panel>

      <Panel title="Tokens and services VIGIL depends on" aside={<span className="hidden sm:inline">Checked hourly; failures rechecked after 2 minutes</span>}>
        {rows === undefined ? (
          <div className="h-28" />
        ) : !services.length ? (
          <Empty title="No checks have run yet">The first round runs a minute after Flect starts.</Empty>
        ) : (
          <ul className="divide-y">
            {services.map((r) => {
              const tone = stateTone(r.alert_level);
              return (
                <li key={r.name} className="flex items-start gap-4 px-5 py-3.5">
                  <Led tone={tone} pulse={tone === "crit"} className="mt-1.5" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-x-3">
                      <span className="font-[580]">{r.name}</span>
                      <span className="text-[12.5px] text-muted-foreground">{KEY_KIND[r.kind] ?? r.kind}</span>
                    </div>
                    <div className={cn("mt-0.5 text-[12.5px] break-words", tone === "crit" ? "text-foreground" : "text-muted-foreground")}>
                      {r.details || <Code className="text-muted-foreground">{r.location}</Code>}
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <StateTag state={r.alert_level} />
                    <span className="text-[12px] text-faint">
                      checked <Time v={r.last_probe_ts} />
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>
    </div>
  );
}
