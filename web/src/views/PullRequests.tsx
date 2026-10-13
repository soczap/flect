import { ArrowRight, GitPullRequest } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCore, usePoll, type PullRequest, type Report } from "@/lib/api";
import { parseJSON, sentence } from "@/lib/format";
import { href } from "@/lib/route";
import { Code, Empty, GitHubLink, Panel, SeverityTag, Sha, StateTag, Tag, Time, tableClass } from "@/components/flect/bits";

function Flow() {
  const m = useCore().meta;
  const step = (title: string, body: string) => (
    <div className="min-w-0 flex-1 rounded-lg border bg-sunken px-4 py-3">
      <div className="font-[600]">{title}</div>
      <div className="mt-0.5 text-[12.5px] text-muted-foreground">{body}</div>
    </div>
  );
  const arrow = <ArrowRight className="hidden size-4 shrink-0 text-faint md:block" aria-hidden />;
  return (
    <Panel title="How a change reaches production">
      <div className="flex flex-col gap-3 p-5 md:flex-row md:items-center">
        {step("Feature PR", "Flect tests it in a sandbox and asks DeepSeek to review the diff")}
        {arrow}
        {step(`Into ${m?.feature_base ?? "uat"}`, "Merged automatically once every check is green")}
        {arrow}
        {step(`Release into ${m?.prod_branch ?? "main"}`, "VAPT runs against UAT; a human merges")}
      </div>
      <p className="border-t px-5 py-3 text-[13px] text-muted-foreground">
        A <span className="font-[600] text-foreground">needs a human</span> verdict can be overridden by commenting <Code>/flect approve</Code> on the pull request.
      </p>
    </Panel>
  );
}

export function PullRequestsView() {
  const { data: prs } = usePoll<PullRequest[]>("/api/prs");
  const { data: reports } = usePoll<Report[]>("/api/reports");
  const rep: Record<string, Report> = {};
  for (const r of reports ?? []) if (r.pr_number && !rep[`${r.pr_number}${r.kind}`]) rep[`${r.pr_number}${r.kind}`] = r;

  return (
    <div className="space-y-6">
      <Flow />
      <Panel title="Reviewed pull requests">
        {prs === undefined ? (
          <div className="h-32" />
        ) : !prs.length ? (
          <Empty icon={<GitPullRequest />} title="No pull requests reviewed yet">
            Flect checks GitHub every 30 seconds. Open a pull request into the UAT branch and it shows up here with a verdict.
          </Empty>
        ) : (
          <Table className={tableClass}>
            <TableHeader>
              <TableRow>
                <TableHead>Pull request</TableHead>
                <TableHead className="hidden md:table-cell">Kind</TableHead>
                <TableHead>Verdict</TableHead>
                <TableHead>Risk</TableHead>
                <TableHead className="hidden lg:table-cell">Tests</TableHead>
                <TableHead className="hidden md:table-cell">Reports</TableHead>
                <TableHead className="text-right">Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {prs.map((p) => {
                const s = parseJSON<Record<string, string>>(p.statuses, {});
                const g = rep[`${p.number}prguard`];
                const v = rep[`${p.number}vapt`];
                return (
                  <TableRow key={p.number}>
                    <TableCell className="max-w-[420px] whitespace-normal">
                      <div className="flex items-baseline gap-2">
                        <GitHubLink kind="pull" n={p.number} />
                        <span className="font-[560]">{p.title || "Untitled"}</span>
                      </div>
                      <div className="mt-1 flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
                        <Sha sha={p.head_sha} /> into <Code className="text-muted-foreground">{p.base}</Code>
                      </div>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">{sentence(p.kind)}</TableCell>
                    <TableCell>
                      <StateTag state={p.state} />
                    </TableCell>
                    <TableCell>{p.risk ? <SeverityTag severity={p.risk} /> : <span className="text-faint">—</span>}</TableCell>
                    <TableCell className="hidden lg:table-cell">
                      {s.tests ? <Tag tone={s.tests === "passed" ? "ok" : s.tests === "failed" ? "crit" : "mute"}>{sentence(s.tests)}</Tag> : <span className="text-faint">—</span>}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <span className="flex gap-3">
                        {g && <a href={href("reports", g.id)} className="underline decoration-line-strong underline-offset-[3px]">Guard</a>}
                        {v && <a href={href("reports", v.id)} className="underline decoration-line-strong underline-offset-[3px]">VAPT</a>}
                        {!g && !v && <span className="text-faint">—</span>}
                      </span>
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground">
                      <Time v={p.updated_ts} />
                    </TableCell>
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
