"use client";

import {
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { label } from "@/lib/types";

interface QualityRadarChartProps {
  metrics: string[];
  configs: Record<string, Record<string, number>>;
  className?: string;
}

export function QualityRadarChart({
  metrics,
  configs,
  className = "h-[320px] w-full",
}: QualityRadarChartProps) {
  const configNames = Object.keys(configs);

  if (configNames.length === 0) {
    return (
      <div className="flex h-[300px] items-center justify-center text-sm text-muted-foreground">
        No comparative config runs recorded yet.
      </div>
    );
  }

  // Format data for Recharts Radar: [{ metric: "MRR", hybrid_rrf: 0.85, vector_only: 0.78, ... }]
  const data = metrics.map((m) => {
    const point: Record<string, unknown> = {
      metric: label(m),
      fullMetric: m,
    };
    for (const name of configNames) {
      point[name] = Number((configs[name]?.[m] ?? 0).toFixed(3));
    }
    return point;
  });

  const palette = [
    { stroke: "oklch(0.72 0.13 168)", fill: "oklch(0.72 0.13 168)", fillOpacity: 0.3 },
    { stroke: "oklch(0.68 0.14 233)", fill: "oklch(0.68 0.14 233)", fillOpacity: 0.25 },
    { stroke: "oklch(0.75 0.15 85)", fill: "oklch(0.75 0.15 85)", fillOpacity: 0.2 },
    { stroke: "oklch(0.65 0.18 310)", fill: "oklch(0.65 0.18 310)", fillOpacity: 0.2 },
  ];

  return (
    <div className={className}>
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart cx="50%" cy="50%" outerRadius="75%" data={data}>
          <PolarGrid stroke="oklch(1 0 0 / 12%)" strokeDasharray="3 3" />
          <PolarAngleAxis
            dataKey="metric"
            tick={{ fill: "oklch(0.8 0 0)", fontSize: 11, fontFamily: "var(--font-mono)" }}
          />
          <PolarRadiusAxis
            angle={30}
            domain={[0, 1]}
            tick={{ fill: "oklch(0.6 0 0)", fontSize: 10, fontFamily: "var(--font-mono)" }}
            stroke="oklch(1 0 0 / 10%)"
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            wrapperStyle={{
              fontSize: "11px",
              fontFamily: "var(--font-mono)",
              paddingTop: "8px",
            }}
          />
          {configNames.map((name, i) => {
            const style = palette[i % palette.length];
            return (
              <Radar
                key={name}
                name={name}
                dataKey={name}
                stroke={style.stroke}
                fill={style.fill}
                fillOpacity={style.fillOpacity}
                strokeWidth={2}
              />
            );
          })}
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}

function CustomTooltip({ active, payload, label: currentLabel }: any) {
  if (!active || !payload || !payload.length) return null;

  return (
    <div className="rounded-lg border border-border/80 bg-popover/95 p-3 shadow-xl backdrop-blur-md">
      <p className="mb-2 font-mono text-xs font-semibold text-foreground">
        {currentLabel}
      </p>
      <div className="space-y-1">
        {payload.map((entry: any, index: number) => (
          <div
            key={`item-${index}`}
            className="flex items-center justify-between gap-4 font-mono text-xs"
          >
            <span className="flex items-center gap-1.5">
              <span
                className="size-2 rounded-full"
                style={{ backgroundColor: entry.stroke || entry.color }}
              />
              <span className="text-muted-foreground">{entry.name}:</span>
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
