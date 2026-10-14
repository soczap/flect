import { useState } from "react";
import { ShieldCheck, ShieldX } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { usePoll, type Action } from "@/lib/api";
import { fullTime, num } from "@/lib/format";
import { actionOutcome, decisionText } from "@/lib/vocab";
import { Code, Empty, Panel, Tag, Time, tableClass } from "@/components/flect/bits";

type Filter = "all" | "done" | "observe" | "failed";
const FILTERS: [Filter, string][] = [
  ["all", "All"],
  ["done", "Done"],
  ["observe", "Would do"],
  ["failed", "Failed"],
];
const match: Record<Filter, (a: Action) => boolean> = {
  all: () => true,
  done: (a) => (a.mode === "enforce" || a.mode === "operator") && a.ok !== 0,
  observe: (a) => a.mode === "observe",
  failed: (a) => a.ok === 0,
};

export function AuditView() {
  const { data: rows } = usePoll<Action[]>("/api/actions?limit=500");
  const { data: chain } = usePoll<{ chain_ok: boolean }>("/api/audit/verify", 30000);
  const [f, setF] = useState<Filter>("all");
  const shown = (rows ?? []).filter(match[f]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <p className="max-w-[64ch] text-[14.5px] text-muted-foreground">
          Every action Flect took or, in observe mode, would have taken. Each entry is hash-chained to the one before it, so an edited or deleted row breaks the chain.
        </p>
        {chain && (
          <span className={`ml-auto flex items-center gap-2 text-[13.5px] font-[580] ${chain.chain_ok ? "text-ok" : "text-crit"}`}>
            {chain.chain_ok ? <ShieldCheck className="size-[18px]" /> : <ShieldX className="size-[18px]" />}
            {chain.chain_ok ? "Chain intact, no tampering" : "Chain broken: the log was altered"}
          </span>
        )}
      </div>
      <Panel
        title={
          <ToggleGroup type="single" value={f} onValueChange={(v) => v && setF(v as Filter)} variant="outline" size="sm">
            {FILTERS.map(([k, l]) => (
              <ToggleGroupItem key={k} value={k} className="px-3 text-[13px]">
                {l}
                <span className="ml-1.5 text-muted-foreground num">{num((rows ?? []).filter(match[k]).length)}</span>
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        }
      >
        {rows === undefined ? (
          <div className="h-40" />
        ) : !shown.length ? (
          <Empty title="Nothing in this view">{f === "failed" ? "No action has failed." : "No actions match this filter yet."}</Empty>
        ) : (
          <Table className={tableClass}>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Outcome</TableHead>
                <TableHead className="hidden lg:table-cell">Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((a) => {
                const o = actionOutcome(a);
                return (
                  <TableRow key={a.id}>
                    <TableCell className="text-muted-foreground" title={fullTime(a.ts)}>
                      <Time v={a.ts} />
                    </TableCell>
                    <TableCell className="font-[580]">{decisionText(a)}</TableCell>
                    <TableCell className="max-w-[260px]">
                      <Code className="block truncate">{a.target}</Code>
                    </TableCell>
                    <TableCell>
                      <Tag tone={o.tone}>{o.label}</Tag>
                    </TableCell>
                    <TableCell className="hidden max-w-[420px] whitespace-normal text-muted-foreground lg:table-cell">{a.result}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Panel>
    </div>
  );
}
