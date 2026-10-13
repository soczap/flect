/* Ctrl/⌘ K: jump to any page, open incident or recent report. */
import { useEffect } from "react";
import { FileText, Moon, TriangleAlert } from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { usePoll, type Incident, type Report } from "@/lib/api";
import { go } from "@/lib/route";
import { useTheme } from "@/lib/theme";
import { ALL_NAV } from "./Shell";

export function useCommandHotkey(setOpen: (fn: (o: boolean) => boolean) => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);
}

export function CommandMenu({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { data: incidents } = usePoll<Incident[]>(open ? "/api/incidents?limit=100" : null, 0);
  const { data: reports } = usePoll<Report[]>(open ? "/api/reports" : null, 0);
  const [theme, toggle] = useTheme();
  const run = (fn: () => void) => {
    onOpenChange(false);
    fn();
  };
  const openIncidents = (incidents ?? []).filter((i) => i.state !== "resolved");

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title="Jump to" description="Pages, open incidents and reports">
      <CommandInput placeholder="Jump to a page, incident or report" />
      <CommandList>
        <CommandEmpty>Nothing matches. Try a page name, an incident title or a report kind.</CommandEmpty>
        <CommandGroup heading="Pages">
          {ALL_NAV.map((n) => (
            <CommandItem key={n.id} value={`${n.label} ${n.blurb}`} onSelect={() => run(() => go(n.id))}>
              <n.icon />
              <span>{n.label}</span>
              <span className="ml-auto hidden truncate text-[12px] text-muted-foreground sm:inline">{n.blurb}</span>
            </CommandItem>
          ))}
        </CommandGroup>
        {openIncidents.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Open incidents">
              {openIncidents.map((i) => (
                <CommandItem key={i.id} value={`incident ${i.id} ${i.title}`} onSelect={() => run(() => go("incidents", i.id))}>
                  <TriangleAlert className="text-crit" />
                  <span className="truncate">{i.title}</span>
                  <span className="ml-auto text-[12px] text-muted-foreground num">#{i.id}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
        {!!reports?.length && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Recent reports">
              {reports.slice(0, 8).map((r) => (
                <CommandItem key={r.id} value={`report ${r.id} ${r.kind} ${r.title}`} onSelect={() => run(() => go("reports", r.id))}>
                  <FileText />
                  <span className="truncate">{r.title || `Report #${r.id}`}</span>
                  <span className="ml-auto text-[12px] text-muted-foreground num">#{r.id}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
        <CommandSeparator />
        <CommandGroup heading="Display">
          <CommandItem value="theme light dark toggle" onSelect={() => run(toggle)}>
            <Moon />
            Switch to {theme === "dark" ? "light" : "dark"} theme
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
