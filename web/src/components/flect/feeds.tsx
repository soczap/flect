/* Lists that recur across views: incidents and the record of what Flect did. */
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Action, Incident } from "@/lib/api";
import { go, href } from "@/lib/route";
import { actionOutcome, decisionText, incidentKind, severityTone } from "@/lib/vocab";
import { Code, GitHubLink, StateTag, Tag, Time, stretchedLink, toneClass } from "./bits";

/** Severity is the coloured rail on the left edge; the rest of the row stays quiet. */
export function IncidentRow({ i, showId = false, showSummary = false }: { i: Incident; showId?: boolean; showSummary?: boolean }) {
  const resolved = i.state === "resolved";
  return (
    <div className={cn("group relative flex items-center gap-4 py-3 pr-4 pl-5 hover:bg-accent/60 sm:pr-5", toneClass(severityTone(i.severity)))}>
      <span
        className={cn("absolute top-2.5 bottom-2.5 left-0 w-[3px] rounded-r-full", resolved ? "bg-border" : "bg-[var(--tone)]")}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <a href={href("incidents", i.id)} className={cn("block truncate font-[580] no-underline", resolved && "font-[500] text-muted-foreground", stretchedLink)}>
          {i.title}
        </a>
        <div className="mt-0.5 flex flex-wrap gap-x-4 gap-y-0.5 text-[12.5px] text-muted-foreground">
          {showId && <span className="num">#{i.id}</span>}
          <span>{incidentKind(i.kind)}</span>
          <span>
            {resolved && i.closed_ts ? "Resolved " : "Opened "}
            <Time v={resolved && i.closed_ts ? i.closed_ts : i.opened_ts} />
          </span>
          {i.github_issue && (
            <span>
              Issue <GitHubLink kind="issues" n={i.github_issue} />
            </span>
          )}
        </div>
        {showSummary && i.summary && <p className="mt-1.5 max-w-[80ch] text-[13px] text-muted-foreground">{i.summary}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {!resolved && <StateTag state={i.state} />}
        <ChevronRight className="size-4 text-faint transition-transform group-hover:translate-x-0.5" aria-hidden />
      </div>
    </div>
  );
}

/** A real sequence, so it is drawn as one: newest first, a lamp per action on a shared spine. */
export function ActionTimeline({ actions, dense = false }: { actions: Action[]; dense?: boolean }) {
  return (
    <ol className="relative">
      {actions.map((a, idx) => {
        const o = actionOutcome(a);
        return (
          <li key={a.id ?? idx} className={cn("relative grid grid-cols-[18px_1fr] gap-x-3", dense ? "pb-3.5" : "pb-5", "last:pb-0")}>
            {idx < actions.length - 1 && <span className="absolute top-3.5 bottom-0 left-[8.5px] w-px bg-border" aria-hidden />}
            <span className={cn("relative mt-[5px] flex size-[18px] items-start justify-center", toneClass(o.tone))} aria-hidden>
              <span
                className={cn(
                  "size-2.5 rounded-full border-2",
                  o.tone === "mute" ? "border-faint bg-card" : "border-[var(--tone)] bg-[color-mix(in_oklab,var(--tone)_35%,var(--card))]",
                )}
              />
            </span>
            <div className="min-w-0">
              <div className="flex items-baseline gap-2">
                <span className="truncate font-[580]">{decisionText(a)}</span>
                {o.label !== "Done" && <Tag tone={o.tone}>{o.label}</Tag>}
                <Time v={a.ts} className="ml-auto shrink-0 text-[12px] text-faint" />
              </div>
              <div className="mt-0.5 flex min-w-0 flex-wrap items-baseline gap-x-2 text-[12.5px] text-muted-foreground">
                <Code className="max-w-full truncate text-muted-foreground">{a.target}</Code>
                {a.result && a.result !== "ok" && <span className="min-w-0 truncate">{String(a.result).slice(0, 140)}</span>}
                {a.incident_id ? (
                  <button type="button" className="relative z-10 underline decoration-line-strong underline-offset-[3px] hover:text-foreground" onClick={() => go("incidents", a.incident_id!)}>
                    incident #{a.incident_id}
                  </button>
                ) : null}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
