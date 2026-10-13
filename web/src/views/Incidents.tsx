import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCore, usePoll, type Incident } from "@/lib/api";
import { num, plural } from "@/lib/format";
import { Empty, Panel } from "@/components/flect/bits";
import { IncidentRow } from "@/components/flect/feeds";

type Filter = "open" | "resolved" | "all";

export function IncidentsView() {
  const { overview } = useCore();
  const { data } = usePoll<Incident[]>("/api/incidents?limit=300");
  const [tab, setTab] = useState<Filter>("open");
  const rows = data ?? [];
  const open = rows.filter((i) => i.state !== "resolved");
  const shown = tab === "open" ? open : tab === "resolved" ? rows.filter((i) => i.state === "resolved") : rows;

  return (
    <div className="space-y-5">
      <p className="max-w-[72ch] text-[14.5px] text-muted-foreground">
        Every problem Flect has seen in production, its dependencies or incoming traffic. Open one for the evidence, DeepSeek's read and each action Flect took.
        {overview ? ` ${plural(overview.resolved_24h, "incident")} resolved in the last 24 hours.` : ""}
      </p>
      <Panel
        title={
          <Tabs value={tab} onValueChange={(v) => setTab(v as Filter)}>
            <TabsList variant="line" className="h-auto gap-4 p-0">
              <TabsTrigger value="open" className="px-0 text-[14px]">
                Open <span className="ml-1 text-muted-foreground num">{num(open.length)}</span>
              </TabsTrigger>
              <TabsTrigger value="resolved" className="px-0 text-[14px]">
                Resolved <span className="ml-1 text-muted-foreground num">{num(rows.length - open.length)}</span>
              </TabsTrigger>
              <TabsTrigger value="all" className="px-0 text-[14px]">
                All
              </TabsTrigger>
            </TabsList>
          </Tabs>
        }
      >
        {data === undefined ? (
          <div className="h-40" />
        ) : shown.length ? (
          <div className="divide-y">
            {shown.map((i) => (
              <IncidentRow key={i.id} i={i} showId showSummary />
            ))}
          </div>
        ) : (
          <Empty icon={<ShieldCheck />} title={tab === "open" ? "Nothing needs you" : "No incidents yet"}>
            {tab === "open" ? "Open incidents appear here the moment a guard raises one." : "Flect has not recorded an incident."}
          </Empty>
        )}
      </Panel>
    </div>
  );
}
