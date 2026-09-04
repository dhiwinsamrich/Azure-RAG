"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { label } from "@/lib/types";

interface QuestionTypeBreakdownChartProps {
  byType: Record<string, Record<string, number>>;
  className?: string;
}

export function QuestionTypeBreakdownChart({
  byType,
  className = "h-[300px] w-full",
}: QuestionTypeBreakdownChartProps) {
  const types = Object.keys(byType);

  if (types.length === 0) {
    return (
      <div className="flex h-[280px] items-center justify-center text-sm text-muted-foreground">
        No question segment breakdown available for this run.
      </div>
    );
  }

  // Find metrics present in any type
  const metricsSet = new Set<string>();
  for (const t of types) {
    for (const m of Object.keys(byType[t])) {
      metricsSet.add(m);
    }
  }

  const selectedMetrics = [
    "context_hit_rate",
    "mrr",
    "citation_validity",
    "refusal_correct",
    "numeric_exactness",
  ].filter((m) => metricsSet.has(m));

  const data = types.map((t) => {
    const row: Record<string, unknown> = {
      type: t.replace(/-/g, " "),
    };
    for (const m of selectedMetrics) {
      row[m] = Number((byType[t]?.[m] ?? 0).toFixed(3));
    }
    return row;
  });

  const colors = [
    "oklch(0.72 0.13 168)", // ledger green
    "oklch(0.68 0.14 233)", // cyan / blue
    "oklch(0.75 0.15 85)",  // amber
    "oklch(0.65 0.18 310)", // purple
    "oklch(0.68 0.17 25)",  // red / coral
  ];

  return (
    <div className={className}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          margin={{ top: 10, right: 10, left: -20, bottom: 20 }}
        >
          <CartesianGrid stroke="oklch(1 0 0 / 8%)" vertical={false} />
          <XAxis
            dataKey="type"
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
          <Tooltip content={<CustomBarTooltip />} />
          <Legend
            formatter={(value) => label(value)}
            wrapperStyle={{
              fontSize: "11px",
              fontFamily: "var(--font-mono)",
              paddingTop: "10px",
            }}
          />
          {selectedMetrics.map((m, i) => (
            <Bar
              key={m}
              dataKey={m}
              fill={colors[i % colors.length]}
              radius={[3, 3, 0, 0]}
              maxBarSize={36}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function CustomBarTooltip({ active, payload, label: currentType }: any) {
  if (!active || !payload || !payload.length) return null;

  return (
    <div className="rounded-lg border border-border/80 bg-popover/95 p-3 shadow-xl backdrop-blur-md">
      <p className="mb-2 font-mono text-xs font-semibold capitalize text-foreground">
        Segment: {currentType}
      </p>
      <div className="space-y-1">
        {payload.map((entry: any, index: number) => (
          <div
            key={`bar-${index}`}
            className="flex items-center justify-between gap-4 font-mono text-xs"
          >
            <span className="flex items-center gap-1.5">
              <span
                className="size-2 rounded-full"
                style={{ backgroundColor: entry.fill }}
              />
              <span className="text-muted-foreground">{label(entry.dataKey)}:</span>
            </span>
            <span className="font-bold text-foreground">
              {Number(entry.value).toFixed(3)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
