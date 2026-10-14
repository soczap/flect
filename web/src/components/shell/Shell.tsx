/* App chrome: navigation rail, top bar, live indicator, command menu. */
import { useEffect, useState, type ReactNode } from "react";
import {
  Activity,
  AudioLines,
  FileText,
  GitCommitHorizontal,
  GitPullRequest,
  KeyRound,
  LayoutGrid,
  Menu,
  Moon,
  ScrollText,
  Search,
  SlidersHorizontal,
  Sun,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useCore } from "@/lib/api";
import { dur } from "@/lib/format";
import { href, useRoute, type ViewId } from "@/lib/route";
import { useTheme } from "@/lib/theme";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Kbd } from "@/components/ui/kbd";
import { Led } from "@/components/flect/bits";
import type { Tone } from "@/lib/vocab";

export interface NavItem {
  id: ViewId;
  label: string;
  icon: LucideIcon;
  blurb: string;
}

export const NAV: { group: string | null; items: NavItem[] }[] = [
  {
    group: null,
    items: [
      { id: "overview", label: "Overview", icon: LayoutGrid, blurb: "Is production safe right now" },
      { id: "ai", label: "Flect AI", icon: AudioLines, blurb: "Talk to Flect about production and approve fixes" },
    ],
  },
  {
    group: "Watching",
    items: [
      { id: "incidents", label: "Incidents", icon: TriangleAlert, blurb: "What went wrong and what Flect did about it" },
      { id: "traffic", label: "Traffic and blocks", icon: Activity, blurb: "Request rate, flood mode and blocked IPs" },
      { id: "keys", label: "Keys and services", icon: KeyRound, blurb: "Expiring credentials and dependent services" },
    ],
  },
  {
    group: "Shipping",
    items: [
      { id: "prs", label: "Pull requests", icon: GitPullRequest, blurb: "Every PR Flect reviewed and its verdict" },
      { id: "deploys", label: "Deployments", icon: GitCommitHorizontal, blurb: "What runs in production and how it got there" },
    ],
  },
  {
    group: "Records",
    items: [
      { id: "reports", label: "Reports", icon: FileText, blurb: "VAPT, PR guard and incident write-ups" },
      { id: "audit", label: "Audit log", icon: ScrollText, blurb: "Every action, hash-chained against tampering" },
    ],
  },
];
export const SETTINGS: NavItem = { id: "settings", label: "Settings", icon: SlidersHorizontal, blurb: "Guard modes and environment" };
export const ALL_NAV = [...NAV.flatMap((g) => g.items), SETTINGS];

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

/** Flect's mark: a ray meeting a surface and leaving at the same angle. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn("size-8", className)} aria-hidden>
      <rect width="24" height="24" rx="7" className="fill-foreground" />
      <path d="M6 6.5 12 15l6-8.5" fill="none" stroke="var(--iris)" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5.5 18.5h13" stroke="var(--background)" strokeWidth="2.1" strokeLinecap="round" />
    </svg>
  );
}

function counts(core: ReturnType<typeof useCore>): Partial<Record<ViewId, [number, Tone]>> {
  const o = core.overview;
  if (!o) return {};
  const keysBad = (o.keys.failing ?? 0) + (o.keys.expired ?? 0);
  return {
    ai: [o.ai_pending ?? 0, "iris"],
    incidents: [o.open_incident_total, o.open_incidents.critical ? "crit" : "warn"],
    traffic: [o.active_blocks, "iris"],
    keys: [keysBad, "crit"],
  };
}

function NavLink({ item, active, count }: { item: NavItem; active: boolean; count?: [number, Tone] }) {
  const Icon = item.icon;
  return (
    <a
      href={href(item.id)}
      aria-current={active ? "page" : undefined}
      className={cn(
        "relative flex h-9 items-center gap-3 rounded-lg px-3 text-[13.5px] no-underline transition-colors",
        active ? "bg-card font-[600] text-foreground shadow-[inset_0_0_0_1px_var(--border)]" : "text-muted-foreground hover:bg-accent/70 hover:text-foreground",
      )}
    >
      {active && <span className="absolute top-2 bottom-2 -left-3 w-[3px] rounded-r-full bg-iris" aria-hidden />}
      <Icon className={cn("size-[17px] shrink-0", active ? "text-foreground" : "text-faint")} strokeWidth={1.8} />
      <span className="truncate">{item.label}</span>
      {count && count[0] > 0 && (
        <span
          className={cn(
            "ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-md px-1.5 text-[11.5px] font-[650] num",
            `tone-${count[1]}`,
            "bg-[color-mix(in_oklab,var(--tone)_16%,transparent)] text-[var(--tone)]",
          )}
        >
          {count[0]}
        </span>
      )}
    </a>
  );
}

function NavBody() {
  const core = useCore();
  const { view } = useRoute();
  const c = counts(core);
  const m = core.meta;
  const now = useNow(30000);
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 px-6 pt-6 pb-7">
        <BrandMark />
        <div className="leading-tight">
          <div className="text-[17px] font-[680] tracking-[-0.01em] [font-stretch:92%]">Flect</div>
          <div className="text-[12.5px] text-muted-foreground">Guarding {m ? m.target.toUpperCase() : "production"}</div>
        </div>
      </div>
      <nav className="flex-1 space-y-5 overflow-y-auto px-3 pl-6" aria-label="Main">
        {NAV.map((g, gi) => (
          <div key={gi}>
            {g.group && <div className="mb-1.5 px-3 text-[12px] text-faint">{g.group}</div>}
            <div className="space-y-0.5">
              {g.items.map((it) => (
                <NavLink key={it.id} item={it} active={view === it.id} count={c[it.id]} />
              ))}
            </div>
          </div>
        ))}
      </nav>
      <div className="space-y-3 px-3 pt-3 pb-5 pl-6">
        <NavLink item={SETTINGS} active={view === "settings"} />
        {m && (
          <div className="border-t px-3 pt-4 text-[12px] leading-relaxed text-faint">
            <a href={m.repo_url} target="_blank" rel="noopener" className="block truncate text-muted-foreground no-underline hover:text-foreground">
              {m.repo}
            </a>
            <div className="num">
              Flect {m.version}
              {m.started ? `, up ${dur(now / 1000 - m.started)}` : ""}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function LiveIndicator() {
  const { lastOk } = useCore();
  const now = useNow(1000);
  const age = (now - lastOk) / 1000;
  const state: [Tone, string, boolean] = !lastOk ? ["mute", "Connecting", false] : age > 20 ? ["crit", `Offline for ${dur(age)}`, false] : ["ok", "Live", true];
  return (
    <span className="flex items-center gap-2 text-[12.5px] text-muted-foreground" role="status" aria-live="polite">
      <Led tone={state[0]} pulse={state[2]} />
      <span className={cn(state[0] === "crit" && "font-[600] text-crit")}>{state[1]}</span>
    </span>
  );
}

export function Shell({ children, onSearch }: { children: ReactNode; onSearch: () => void }) {
  const { view } = useRoute();
  const [theme, toggle] = useTheme();
  const [menu, setMenu] = useState(false);
  const item = ALL_NAV.find((n) => n.id === view)!;

  useEffect(() => {
    setMenu(false);
  }, [view]);
  useEffect(() => {
    document.title = view === "overview" ? "Flect" : `${item.label} · Flect`;
  }, [view, item.label]);

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[256px_1fr]">
      <aside className="sticky top-0 hidden h-dvh border-r lg:block">
        <NavBody />
      </aside>
      <Sheet open={menu} onOpenChange={setMenu}>
        <SheetContent side="left" className="w-[280px] bg-background p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SheetDescription className="sr-only">Flect sections</SheetDescription>
          <NavBody />
        </SheetContent>
      </Sheet>
      <div className="min-w-0">
        <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur-md">
          <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-3 px-4 sm:px-6 lg:px-10">
            <button
              type="button"
              className="-ml-1 inline-flex size-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground lg:hidden"
              onClick={() => setMenu(true)}
              aria-label="Open navigation"
            >
              <Menu className="size-5" />
            </button>
            <h1 className="truncate text-[19px] font-[650] tracking-[-0.01em] [font-stretch:90%]">{item.label}</h1>
            <div className="ml-auto flex items-center gap-1.5 sm:gap-3">
              <LiveIndicator />
              <button
                type="button"
                onClick={onSearch}
                className="ml-2 inline-flex h-9 items-center gap-2 rounded-lg border bg-card px-2.5 text-[13px] text-muted-foreground hover:border-line-strong hover:text-foreground sm:w-56"
                aria-label="Search Flect"
              >
                <Search className="size-4" />
                <span className="hidden sm:inline">Jump to</span>
                <Kbd className="ml-auto hidden sm:inline-flex">{isMac ? "⌘K" : "Ctrl K"}</Kbd>
              </button>
              <button
                type="button"
                onClick={toggle}
                className="inline-flex size-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"
                aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
                title={theme === "dark" ? "Light theme" : "Dark theme"}
              >
                {theme === "dark" ? <Sun className="size-[18px]" /> : <Moon className="size-[18px]" />}
              </button>
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-[1400px] px-4 pt-6 pb-16 sm:px-6 lg:px-10 lg:pt-8">{children}</main>
      </div>
    </div>
  );
}
