import { useEffect, useState, type ComponentType } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { CoreContext, useCoreLoader } from "@/lib/api";
import { interceptLinks, useRoute, type ViewId } from "@/lib/route";
import { useFollowOsTheme } from "@/lib/theme";
import { Shell } from "@/components/shell/Shell";
import { CommandMenu, useCommandHotkey } from "@/components/shell/CommandMenu";
import { IncidentDrawer, ReportDrawer } from "@/components/flect/Drawers";
import { OverviewView } from "@/views/Overview";
import { IncidentsView } from "@/views/Incidents";
import { PullRequestsView } from "@/views/PullRequests";
import { TrafficView } from "@/views/Traffic";
import { DeploymentsView } from "@/views/Deployments";
import { KeysView } from "@/views/Keys";
import { ReportsView } from "@/views/Reports";
import { AuditView } from "@/views/Audit";
import { SettingsView } from "@/views/Settings";

const VIEWS: Record<ViewId, ComponentType> = {
  overview: OverviewView,
  incidents: IncidentsView,
  prs: PullRequestsView,
  traffic: TrafficView,
  deploys: DeploymentsView,
  keys: KeysView,
  reports: ReportsView,
  audit: AuditView,
  settings: SettingsView,
};

export default function App() {
  const core = useCoreLoader();
  const { view } = useRoute();
  const [search, setSearch] = useState(false);
  useFollowOsTheme();
  useCommandHotkey(setSearch);

  useEffect(() => {
    document.addEventListener("click", interceptLinks);
    return () => document.removeEventListener("click", interceptLinks);
  }, []);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [view]);

  const View = VIEWS[view];
  return (
    <CoreContext.Provider value={core}>
      <TooltipProvider delayDuration={250}>
        <Shell onSearch={() => setSearch(true)}>
          <View />
        </Shell>
        <IncidentDrawer />
        <ReportDrawer />
        <CommandMenu open={search} onOpenChange={setSearch} />
      </TooltipProvider>
    </CoreContext.Provider>
  );
}
