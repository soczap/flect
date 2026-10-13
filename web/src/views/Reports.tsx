import { useState } from "react";
import { FileText } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePoll, type Report } from "@/lib/api";
import { num } from "@/lib/format";
import { go } from "@/lib/route";
import { REPORT_KIND } from "@/lib/vocab";
import { Empty, Panel, SeverityTag, Sha, Tag, Time, tableClass } from "@/components/flect/bits";

const KINDS: [string, string][] = [
  ["all", "All"],
  ["vapt", "VAPT"],
  ["prguard", "PR guard"],
  ["incident", "Incidents"],
];

export function ReportsView() {
  const { data: rows } = usePoll<Report[]>("/api/reports");
  const [kind, setKind] = useState("all");
  const all = rows ?? [];
  const shown = all.filter((r) => kind === "all" || r.kind === kind);
  const count = (k: string) => (k === "all" ? all.length : all.filter((r) => r.kind === k).length);

  return (
    <Panel
      title={
        <Tabs value={kind} onValueChange={setKind}>
          <TabsList variant="line" className="h-auto flex-wrap gap-4 p-0">
            {KINDS.map(([k, l]) => (
              <TabsTrigger key={k} value={k} className="px-0 text-[14px]">
                {l} <span className="ml-1 text-muted-foreground num">{num(count(k))}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      }
    >
      {rows === undefined ? (
        <div className="h-40" />
      ) : !shown.length ? (
        <Empty icon={<FileText />} title="No reports of this kind yet">
          Flect writes a report for every VAPT scan, every reviewed pull request and every incident.
        </Empty>
      ) : (
        <Table className={tableClass}>
          <TableHeader>
            <TableRow>
              <TableHead>Report</TableHead>
              <TableHead className="hidden md:table-cell">About</TableHead>
              <TableHead className="hidden sm:table-cell">Worst finding</TableHead>
              <TableHead className="text-right">Written</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((r) => {
              const k = REPORT_KIND[r.kind];
              return (
                <TableRow
                  key={r.id}
                  className="cursor-pointer"
                  tabIndex={0}
                  onClick={() => go("reports", r.id)}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), go("reports", r.id))}
                >
                  <TableCell className="max-w-[520px] whitespace-normal">
                    <div className="flex items-center gap-2.5">
                      <Tag tone={k?.tone ?? "mute"}>{k?.label ?? r.kind}</Tag>
                      <span className="min-w-0 font-[560]">{r.title || `Report #${r.id}`}</span>
                    </div>
                  </TableCell>
                  <TableCell className="hidden text-muted-foreground md:table-cell">
                    <span className="flex items-center gap-2">
                      {r.pr_number && <span className="num">PR #{r.pr_number}</span>}
                      {r.ref_sha && <Sha sha={r.ref_sha} />}
                      {!r.pr_number && !r.ref_sha && <span className="text-faint">—</span>}
                    </span>
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">{r.max_severity ? <SeverityTag severity={r.max_severity} /> : <span className="text-faint">—</span>}</TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    <Time v={r.created_ts} />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </Panel>
  );
}
