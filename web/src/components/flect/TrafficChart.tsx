/* Requests per second against Flect's learned baseline. Traffic is not a state, so it is drawn in ink;
   only flood windows get colour. */
import { useMemo } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceArea, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart";
import type { History } from "@/lib/api";
import { clock, num } from "@/lib/format";
import { Empty } from "./bits";
import { Activity } from "lucide-react";

const config = {
  rps: { label: "Requests/s", color: "var(--foreground)" },
  baseline: { label: "Baseline", color: "var(--faint)" },
} satisfies ChartConfig;

export function TrafficChart({ traffic, height = 220 }: { traffic: History["traffic"]; height?: number }) {
  const data = useMemo(() => traffic.map(([t, rps, baseline, flood]) => ({ t, rps, baseline, flood })), [traffic]);
  const floods = useMemo(() => {
    const out: [number, number][] = [];
    let start: number | null = null;
    for (let i = 0; i < data.length; i++) {
      if (data[i].flood && start == null) start = data[i].t;
      if ((!data[i].flood || i === data.length - 1) && start != null) {
        out.push([start, data[i].t]);
        start = null;
      }
    }
    return out;
  }, [data]);

  if (!data.length)
    return (
      <Empty icon={<Activity />} title="No traffic samples yet" className="py-12">
        Flect samples VIGIL's request rate every 5 seconds and keeps the last hour.
      </Empty>
    );

  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height }}>
      <ComposedChart data={data} margin={{ top: 12, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="rps-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="var(--color-rps)" stopOpacity={0.16} />
            <stop offset="1" stopColor="var(--color-rps)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} strokeDasharray="2 4" stroke="var(--line-strong)" />
        {floods.map(([a, b]) => (
          <ReferenceArea key={a} x1={a} x2={b} fill="var(--crit)" fillOpacity={0.12} stroke="none" />
        ))}
        <XAxis
          dataKey="t"
          type="number"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(t: number) => clock(t)}
          tickLine={false}
          axisLine={false}
          minTickGap={48}
          tickMargin={8}
        />
        <YAxis width={36} tickLine={false} axisLine={false} tickFormatter={(v: number) => num(v, v < 10 ? 1 : 0)} />
        <ChartTooltip
          cursor={{ stroke: "var(--foreground)", strokeOpacity: 0.3 }}
          content={({ active, payload }) => {
            const p = active && payload?.[0]?.payload;
            if (!p) return null;
            return (
              <div className="rounded-md border bg-popover px-2.5 py-1.5 text-[12px] shadow-sm">
                <div className="text-muted-foreground num">{clock(p.t, true)}</div>
                <div className="mt-0.5 num">
                  <b className="font-[620]">{num(p.rps, 2)}</b> requests/s
                </div>
                <div className="text-muted-foreground num">baseline {num(p.baseline, 2)}</div>
                {p.flood && <div className="mt-0.5 font-[600] text-crit">Flood mode on</div>}
              </div>
            );
          }}
        />
        <Area dataKey="rps" type="monotone" stroke="var(--color-rps)" strokeWidth={1.6} fill="url(#rps-fill)" isAnimationActive={false} dot={false} />
        <Line dataKey="baseline" type="monotone" stroke="var(--color-baseline)" strokeDasharray="5 4" strokeWidth={1.3} dot={false} isAnimationActive={false} />
      </ComposedChart>
    </ChartContainer>
  );
}

export function ChartKey() {
  return (
    <span className="flex items-center gap-4 text-[12.5px]">
      <span className="flex items-center gap-1.5">
        <span className="h-[2px] w-4 rounded bg-foreground" />
        Requests/s
      </span>
      <span className="flex items-center gap-1.5">
        <span className="w-4 border-t-[1.5px] border-dashed border-faint" />
        Baseline
      </span>
    </span>
  );
}
