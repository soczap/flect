/* Small building blocks shared by every view. */
import { useState, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCore } from "@/lib/api";
import { ago, fullTime, short } from "@/lib/format";
import { severityTone, stateLabel, stateTone, type Tone } from "@/lib/vocab";

const TONE_CLASS: Record<Tone, string> = {
  ok: "tone-ok",
  warn: "tone-warn",
  high: "tone-high",
  crit: "tone-crit",
  iris: "tone-iris",
  mute: "tone-mute",
};
export const toneClass = (t: Tone) => TONE_CLASS[t];

/** A status lamp. Lit lamps glow; `pulse` is reserved for things that are live right now. */
export function Led({ tone, pulse = false, className }: { tone: Tone; pulse?: boolean; className?: string }) {
  const lit = tone !== "mute";
  return (
    <span className={cn("relative inline-flex size-2 shrink-0", toneClass(tone), className)} aria-hidden>
      {pulse && lit && <span className="absolute inset-0 rounded-full bg-[var(--tone)] opacity-60 motion-safe:animate-ping" />}
      <span
        className={cn(
          "relative inline-flex size-2 rounded-full",
          lit ? "bg-[var(--tone)] shadow-[0_0_0_3px_color-mix(in_oklab,var(--tone)_20%,transparent)]" : "border border-faint",
        )}
      />
    </span>
  );
}

/** Compact state label: tinted, never a solid block of colour. */
export function Tag({ tone, children, lamp = false, className }: { tone: Tone; children: ReactNode; lamp?: boolean; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-[22px] shrink-0 items-center gap-1.5 rounded-[6px] px-2 text-[12px] leading-none font-[560] whitespace-nowrap",
        "bg-[color-mix(in_oklab,var(--tone)_13%,transparent)] text-[color-mix(in_oklab,var(--tone)_88%,var(--foreground))]",
        toneClass(tone),
        className,
      )}
    >
      {lamp && <span className="size-1.5 rounded-full bg-[var(--tone)]" />}
      {children}
    </span>
  );
}

export const StateTag = ({ state, label }: { state: string; label?: string }) => (
  <Tag tone={stateTone(state)}>{label ?? stateLabel(state)}</Tag>
);

export const SeverityTag = ({ severity }: { severity: string }) => (
  <Tag tone={severityTone(severity)} lamp>
    {stateLabel(severity)}
  </Tag>
);

export function Time({ v, className }: { v: string | number | null | undefined; className?: string }) {
  if (v == null) return <span className={className}>—</span>;
  return (
    <time className={cn("num whitespace-nowrap", className)} title={fullTime(v)}>
      {ago(v)}
    </time>
  );
}

function useRepo() {
  return useCore().meta?.repo_url;
}

export function Sha({ sha, className }: { sha: string | null | undefined; className?: string }) {
  const repo = useRepo();
  if (!sha) return <span className="text-faint">—</span>;
  return (
    <a
      href={repo ? `${repo}/commit/${sha}` : undefined}
      target="_blank"
      rel="noopener"
      title={sha}
      className={cn(
        "relative z-10 rounded-[5px] border border-border bg-muted px-1.5 py-px font-mono text-[12px] text-foreground no-underline hover:border-line-strong",
        className,
      )}
    >
      {short(sha)}
    </a>
  );
}

export function GitHubLink({ kind, n }: { kind: "issues" | "pull"; n: number | null | undefined }) {
  const repo = useRepo();
  if (!n) return null;
  return (
    <a
      href={repo ? `${repo}/${kind}/${n}` : undefined}
      target="_blank"
      rel="noopener"
      className="relative z-10 num underline decoration-line-strong underline-offset-[3px] hover:decoration-foreground"
    >
      #{n}
    </a>
  );
}

export function Code({ children, className }: { children: ReactNode; className?: string }) {
  return <code className={cn("font-mono text-[12.5px] text-foreground", className)}>{children}</code>;
}

/** A titled section. Panels are the only boxes on the page; everything inside them is ruled, not boxed. */
export function Panel({
  title,
  aside,
  children,
  className,
  bodyClassName,
  id,
}: {
  title?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  id?: string;
}) {
  return (
    <section id={id} className={cn("min-w-0 rounded-xl border bg-card", className)}>
      {(title || aside) && (
        <header className="flex min-h-12 flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-2.5 sm:px-5">
          {title && <h2 className="text-[14.5px] font-[620]">{title}</h2>}
          {aside && <div className="ml-auto flex items-center gap-2 text-[13px] text-muted-foreground">{aside}</div>}
        </header>
      )}
      <div className={cn("min-w-0", bodyClassName)}>{children}</div>
    </section>
  );
}

export function Empty({ icon, title, children, className }: { icon?: ReactNode; title: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-1.5 px-6 py-10 text-center", className)}>
      {icon && <div className="mb-1 text-faint [&_svg]:size-6">{icon}</div>}
      <p className="font-[580]">{title}</p>
      {children && <p className="max-w-[46ch] text-[13px] text-muted-foreground">{children}</p>}
    </div>
  );
}

/** Label/value pairs in two ruled columns. */
export function Facts({ rows, className }: { rows: [ReactNode, ReactNode | null | undefined][]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-[minmax(110px,auto)_1fr] text-[13.5px]", className)}>
      {rows
        .filter(([, v]) => v != null && v !== "" && v !== false)
        .map(([k, v], i) => (
          <div key={i} className="col-span-2 grid grid-cols-subgrid border-b border-dashed py-2 last:border-b-0">
            <dt className="pr-4 text-muted-foreground">{k}</dt>
            <dd className="min-w-0 break-words">{v}</dd>
          </div>
        ))}
    </dl>
  );
}

export function CopyCommand({ cmd, note }: { cmd: string; note?: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(cmd);
      setDone(true);
      setTimeout(() => setDone(false), 1400);
    } catch {
      /* clipboard needs a secure context; the command stays selectable */
    }
  };
  return (
    <div className="group flex items-center gap-3 rounded-lg border bg-sunken py-1.5 pr-1.5 pl-3">
      <span className="text-faint select-none" aria-hidden>
        $
      </span>
      <code className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{cmd}</code>
      {note && <span className="hidden text-[12px] text-faint md:inline">{note}</span>}
      <button
        type="button"
        onClick={copy}
        aria-label={done ? "Copied" : `Copy ${cmd}`}
        className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        {done ? <Check className="size-3.5 text-ok" /> : <Copy className="size-3.5" />}
        {done ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

/** Big condensed number with a plain-language label underneath. */
export function Readout({ value, unit, label, tone, className }: { value: ReactNode; unit?: string; label: ReactNode; tone?: Tone; className?: string }) {
  return (
    <div className={cn("min-w-0", tone && toneClass(tone), className)}>
      <div className={cn("readout text-[34px]", tone && "text-[var(--tone)]")}>
        {value}
        {unit && <span className="ml-1 text-[15px] font-[520] text-muted-foreground [font-stretch:90%]">{unit}</span>}
      </div>
      <div className="mt-1.5 text-[13px] text-muted-foreground">{label}</div>
    </div>
  );
}

/** Cells separated by hairlines inside one panel, instead of a grid of floating cards. */
export function Rack({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("grid gap-px overflow-hidden rounded-xl border bg-border", className)}>{children}</div>;
}

export function RackCell({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("min-w-0 bg-card p-5", className)}>{children}</div>;
}

/** Shared table rhythm: quiet sentence-case headers, generous first/last gutters, rows that can wrap. */
/** "Stretched link": the anchor's ::after covers the nearest relative ancestor, so a whole row is clickable
    without nesting other links inside an <a>. Inner links sit above it with `relative z-10`. */
export const stretchedLink =
  "after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-ring focus-visible:after:outline-solid";

export const tableClass =
  "text-[13.5px] [&_th]:h-10 [&_th]:text-[12.5px] [&_th]:font-[560] [&_th]:text-muted-foreground [&_td]:py-3 [&_td]:align-top [&_th:first-child]:pl-5 [&_td:first-child]:pl-5 [&_th:last-child]:pr-5 [&_td:last-child]:pr-5 [&_th]:px-3 [&_td]:px-3";
