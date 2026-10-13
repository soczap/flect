/* Detail drawers, driven by the URL: #/incidents/11 and #/reports/14 open them, closing steps back. */
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Cpu } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { usePoll, type IncidentDetail, type Report } from "@/lib/api";
import { fullTime, parseJSON } from "@/lib/format";
import { closeTo, useRoute } from "@/lib/route";
import { REPORT_KIND, SEVERITY_TONE, incidentKind } from "@/lib/vocab";
import { Code, Facts, GitHubLink, SeverityTag, Sha, StateTag, Tag, Time } from "./bits";
import { ActionTimeline } from "./feeds";

function Drawer({
  open,
  onClose,
  title,
  meta,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="right"
        className={`w-full gap-0 border-l bg-background p-0 outline-none ${wide ? "sm:max-w-[840px]" : "sm:max-w-[640px]"}`}
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          (e.currentTarget as HTMLElement).focus();
        }}
      >
        <SheetHeader className="gap-2 border-b bg-card px-5 pt-5 pb-4 sm:px-6">
          {meta && <div className="flex flex-wrap items-center gap-2 pr-8">{meta}</div>}
          <SheetTitle className="pr-8 text-[19px] leading-snug font-[640] [font-stretch:88%]">{title}</SheetTitle>
          <SheetDescription className="sr-only">Details</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">{children}</div>
      </SheetContent>
    </Sheet>
  );
}

function Loading() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-7 first:mt-0">
      <h3 className="mb-2.5 text-[13px] font-[600] text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

const SHOWN = ["traceback", "reason", "classification", "crashed_sha", "exception", "ip", "rule", "location", "expires", "details"];

export function IncidentDrawer() {
  const { view, arg } = useRoute();
  const open = view === "incidents" && !!arg;
  const { data: i, error } = usePoll<IncidentDetail>(open ? `/api/incidents/${arg}` : null);
  const d = (i?.details ?? {}) as Record<string, unknown>;
  const llm = parseJSON<{ summary?: string; likely_cause?: string; recommended_followups?: string[] } | null>(i?.llm_summary, null);
  const str = (k: string) => (d[k] == null || d[k] === "" ? null : String(d[k]));
  const rest = Object.fromEntries(Object.entries(d).filter(([k, v]) => !SHOWN.includes(k) && v != null && v !== ""));
  const ready = i && String(i.id) === arg;

  return (
    <Drawer
      open={open}
      onClose={() => closeTo("incidents")}
      title={ready ? i.title : `Incident #${arg}`}
      meta={
        ready && (
          <>
            <SeverityTag severity={i.severity} />
            <StateTag state={i.state} />
            <span className="text-[12.5px] text-muted-foreground num">#{i.id}</span>
          </>
        )
      }
    >
      {error && !ready ? (
        <p className="text-muted-foreground">Incident #{arg} could not be loaded: {error.message}</p>
      ) : !ready ? (
        <Loading />
      ) : (
        <>
          {i.summary && <p className="mb-6 max-w-[64ch] text-[14.5px]">{i.summary}</p>}
          {llm?.summary && (
            <section className="mb-6 rounded-xl border bg-card p-4 tone-iris">
              <div className="mb-2 flex items-center gap-2 text-[13px] font-[600] text-[var(--tone)]">
                <Cpu className="size-4" />
                DeepSeek's read
              </div>
              <p className="max-w-[64ch]">{llm.summary}</p>
              {llm.likely_cause && (
                <p className="mt-2 text-[13px] text-muted-foreground">
                  <span className="font-[600] text-foreground">Likely cause:</span> {llm.likely_cause}
                </p>
              )}
              {!!llm.recommended_followups?.length && (
                <ul className="mt-2 list-disc pl-5 text-[13px] text-muted-foreground marker:text-faint">
                  {llm.recommended_followups.map((f, n) => (
                    <li key={n}>{f}</li>
                  ))}
                </ul>
              )}
            </section>
          )}
          <Section title="Facts">
            <Facts
              rows={[
                ["Kind", incidentKind(i.kind)],
                ["Opened", <span title={fullTime(i.opened_ts)}>{fullTime(i.opened_ts)}</span>],
                ["Resolved", i.closed_ts ? fullTime(i.closed_ts) : null],
                ["GitHub issue", i.github_issue ? <GitHubLink kind="issues" n={i.github_issue} /> : null],
                ["Reason", str("reason")],
                ["Classification", str("classification")],
                ["Commit", str("crashed_sha") ? <Sha sha={str("crashed_sha")} /> : null],
                ["Exception", str("exception") ? <Code>{str("exception")}</Code> : null],
                ["IP", str("ip") ? <Code>{str("ip")}</Code> : null],
                ["Rule", str("rule") ? <Code>{str("rule")}</Code> : null],
                ["Location", str("location") ? <Code className="break-all">{str("location")}</Code> : null],
                ["Expires", str("expires") ? fullTime(str("expires")) : null],
                ["Details", str("details")],
              ]}
            />
          </Section>
          {str("traceback") && (
            <Section title="Traceback">
              <pre className="max-h-80 overflow-auto rounded-lg border bg-sunken p-3 font-mono text-[12px] leading-relaxed">{str("traceback")}</pre>
            </Section>
          )}
          {Object.keys(rest).length > 0 && (
            <Section title="Evidence">
              <pre className="max-h-72 overflow-auto rounded-lg border bg-sunken p-3 font-mono text-[12px] leading-relaxed">{JSON.stringify(rest, null, 2)}</pre>
            </Section>
          )}
          <Section title="What Flect did">
            {i.actions.length ? (
              <ActionTimeline actions={[...i.actions].reverse()} />
            ) : (
              <p className="text-[13px] text-muted-foreground">Nothing yet. This incident was recorded and reported without an automatic action.</p>
            )}
          </Section>
        </>
      )}
    </Drawer>
  );
}

export function ReportDrawer() {
  const { view, arg } = useRoute();
  const open = view === "reports" && !!arg;
  const { data: text, error } = usePoll<string>(open ? `/api/reports/${arg}` : null, 0);
  const { data: list } = usePoll<Report[]>(open ? "/api/reports" : null, 0);
  const r = list?.find((x) => String(x.id) === arg);
  const kind = r ? REPORT_KIND[r.kind] : undefined;

  return (
    <Drawer
      open={open}
      onClose={() => closeTo("reports")}
      wide
      title={r?.title || `Report #${arg}`}
      meta={
        r && (
          <>
            <Tag tone={kind?.tone ?? "mute"}>{kind?.label ?? r.kind}</Tag>
            {r.max_severity && <SeverityTag severity={r.max_severity} />}
            <span className="text-[12.5px] text-muted-foreground">
              Written <Time v={r.created_ts} />
            </span>
          </>
        )
      }
    >
      {error && text === undefined ? (
        <p className="text-muted-foreground">Report #{arg} could not be loaded: {error.message}</p>
      ) : text === undefined ? (
        <Loading />
      ) : (
        <article className="prose-report">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ node: _n, ...p }) => <a {...p} target="_blank" rel="noopener" />,
              td: ({ node: _n, children, ...p }) => (
                <td {...p}>{typeof children === "string" && SEVERITY_TONE[children.trim().toLowerCase()] ? <SeverityTag severity={children.trim().toLowerCase()} /> : children}</td>
              ),
            }}
          >
            {text}
          </ReactMarkdown>
        </article>
      )}
    </Drawer>
  );
}
