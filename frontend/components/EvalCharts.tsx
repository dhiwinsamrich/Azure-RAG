"use client";

import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { EvilBarChart } from "@/components/evilcharts/charts/recharts-bar-chart";
import { EvilLineChart } from "@/components/evilcharts/charts/recharts-line-chart";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { label, type RunSummary } from "@/lib/types";

/** Ablation: one bar per retrieval config, grouped by metric. */
export function AblationChart({
  metrics,
  configs,
  isLoading = false,
}: {
  metrics: string[];
  configs: Record<string, Record<string, number>>;
  isLoading?: boolean;
}) {
  const names = Object.keys(configs);

  // Recharts wants one row per category; the categories are metrics and each
  // config becomes a series, so configs sit side by side per metric.
  const data = metrics.map((m) => {
    const row: Record<string, unknown> = { metric: label(m) };
    for (const n of names) row[n] = configs[n]?.[m] ?? 0;
    return row;
  });

  const palette = [
    "var(--chart-1)", "var(--chart-2)", "var(--chart-3)",
    "var(--chart-4)", "var(--chart-5)",
  ];
  const config = Object.fromEntries(
    names.map((n, i) => [
      n,
      { label: n, colors: { dark: [palette[i % palette.length]] } },
    ]),
  ) as Record<string, { label: string; colors: { dark: string[] } }>;

  if (!isLoading && names.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        No comparable runs yet. Evaluate two or more configs to populate this.
      </p>
    );
  }

  return (
    <EvilBarChart
      data={data}
      config={config}
      isLoading={isLoading}
      className="h-[300px] w-full"
      animationType="left-to-right"
      backgroundVariant="dots"
    >
      <EvilBarChart.Grid />
      <EvilBarChart.XAxis dataKey="metric" />
      <EvilBarChart.YAxis />
      <EvilBarChart.Tooltip />
      <EvilBarChart.Legend />
      {names.map((n) => (
        <EvilBarChart.Bar key={n} dataKey={n} variant="gradient" enableHoverHighlight />
      ))}
    </EvilBarChart>
  );
}

/** Metric trend across runs with metric switcher tabs. */
export function InteractiveTrendChart({
  runs,
  defaultMetric = "mrr",
}: {
  runs: RunSummary[];
  defaultMetric?: string;
}) {
  const availableMetrics = [
    "mrr",
    "context_hit_rate",
    "citation_validity",
    "refusal_correct",
    "numeric_exactness",
    "fiscal_period_correctness",
  ];

  const [selectedMetric, setSelectedMetric] = useState(defaultMetric);

  const data = [...runs]
    .reverse()
    .filter((r) => r.metrics[selectedMetric] !== undefined)
    .map((r) => ({
      run: r.id.replace(/^run-/, ""),
      fullId: r.id,
      config: r.config_id,
      docs: r.doc_ids?.join(", ") || "All docs",
      value: Number(r.metrics[selectedMetric]?.toFixed(3) ?? 0),
    }));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-3">
        <Tabs value={selectedMetric} onValueChange={setSelectedMetric}>
          <TabsList className="flex-wrap h-auto p-1">
            {availableMetrics.map((m) => (
              <TabsTrigger
                key={m}
                value={m}
                className="h-7 px-2.5 text-xs font-mono"
              >
                {label(m)}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      {data.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">
          No runs recorded for {label(selectedMetric)} yet.
        </p>
      ) : (
        <div className="h-[280px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={data}
              margin={{ top: 10, right: 15, left: -20, bottom: 5 }}
            >
              <CartesianGrid stroke="oklch(1 0 0 / 8%)" vertical={false} />
              <XAxis
                dataKey="run"
                tick={{ fill: "oklch(0.8 0 0)", fontSize: 11, fontFamily: "var(--font-mono)" }}
                axisLine={{ stroke: "oklch(1 0 0 / 15%)" }}
                tickLine={false}
              />
              <YAxis
                domain={[0, 1]}
                tick={{ fill: "oklch(0.6 0 0)", fontSize: 10, fontFamily: "var(--font-mono)" }}
                axisLine={{ stroke: "oklch(1 0 0 / 15%)" }}
                tickLine={false}
              />
              <Tooltip content={<TrendTooltip metricName={label(selectedMetric)} />} />
              <Line
                type="monotone"
                dataKey="value"
                name={label(selectedMetric)}
                stroke="oklch(0.72 0.13 168)"
                strokeWidth={2.5}
                dot={{ fill: "oklch(0.72 0.13 168)", r: 4 }}
                activeDot={{ fill: "oklch(0.72 0.13 168)", r: 6, stroke: "oklch(1 0 0)", strokeWidth: 2 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function TrendTooltip({ active, payload, metricName }: any) {
  if (!active || !payload || !payload.length) return null;
  const point = payload[0].payload;

  return (
    <div className="rounded-lg border border-border/80 bg-popover/95 p-3 shadow-xl backdrop-blur-md">
      <div className="space-y-1 font-mono text-xs">
        <p className="font-bold text-foreground">Run: {point.fullId}</p>
        <p className="text-muted-foreground">Config: <span className="text-primary">{point.config}</span></p>
        <p className="text-muted-foreground">Documents: <span className="text-foreground">{point.docs}</span></p>
        <p className="pt-1 text-xs font-bold text-primary">
          {metricName}: {point.value}
        </p>
      </div>
    </div>
  );
}

/** Metric trend across runs, newest last. */
export function RunTrendChart({
  runs,
  metric,
  isLoading = false,
}: {
  runs: { id: string; metrics: Record<string, number> }[];
  metric: string;
  isLoading?: boolean;
}) {
  const data = [...runs]
    .reverse()
    .filter((r) => r.metrics[metric] !== undefined)
    .map((r) => ({ run: r.id.replace(/^run-/, ""), value: r.metrics[metric] }));

  if (!isLoading && data.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        No runs recorded for {label(metric)} yet.
      </p>
    );
  }

  return (
    <EvilLineChart
      data={data}
      config={{ value: { label: label(metric), colors: { dark: ["var(--chart-1)"] } } }}
      isLoading={isLoading}
      className="h-[300px] w-full"
    >
      <EvilLineChart.Grid />
      <EvilLineChart.XAxis dataKey="run" />
      <EvilLineChart.YAxis />
      <EvilLineChart.Tooltip />
      <EvilLineChart.Line dataKey="value" glowing>
        <EvilLineChart.Dot />
        <EvilLineChart.ActiveDot />
      </EvilLineChart.Line>
    </EvilLineChart>
  );
}
