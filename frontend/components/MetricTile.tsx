import { HelpCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { METRIC_DESCRIPTIONS, METRIC_SHORT_EXPLANATIONS } from "@/lib/types";

/**
 * A score is never shown without the bar it has to clear: the notch on the
 * meter is the gate threshold, so "0.81" reads as pass or fail at a glance.
 */
export function MetricTile({
  label,
  metricKey,
  value,
  previous,
  threshold,
}: {
  label: string;
  metricKey?: string;
  value?: number;
  previous?: number;
  threshold?: number;
}) {
  const subtitle = metricKey ? METRIC_SHORT_EXPLANATIONS[metricKey] : undefined;
  const description = metricKey ? METRIC_DESCRIPTIONS[metricKey] : undefined;

  if (value === undefined) {
    return (
      <Card className="border-border/60">
        <CardContent className="space-y-2 pt-5 pb-4">
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
          <p className="text-2xl font-bold text-muted-foreground">—</p>
        </CardContent>
      </Card>
    );
  }

  const pass = threshold === undefined || value >= threshold;
  const delta = previous === undefined ? undefined : value - previous;

  return (
    <Card className="border-border/60 transition-all hover:border-primary/40 hover:shadow-md group">
      <CardContent className="space-y-2.5 pt-5 pb-4">
        <div className="flex items-start justify-between gap-1">
          <p className="text-xs font-semibold leading-tight text-foreground/90 group-hover:text-primary transition-colors">
            {label}
          </p>
          {description && (
            <span title={description} className="text-muted-foreground hover:text-primary cursor-help transition-colors">
              <HelpCircle className="size-3.5" />
            </span>
          )}
        </div>

        {subtitle && (
          <p className="text-[10px] leading-none text-muted-foreground truncate" title={subtitle}>
            {subtitle}
          </p>
        )}

        <div className="flex items-baseline justify-between pt-0.5">
          <p className="tabular font-mono text-2xl font-bold leading-none tracking-tight">
            {value.toFixed(2)}
          </p>
          {threshold !== undefined && (
            <span className={`text-[10px] font-mono font-medium ${pass ? "text-primary" : "text-destructive"}`}>
              {pass ? "PASS" : "FAIL"}
            </span>
          )}
        </div>

        <div className="relative h-1.5 overflow-visible rounded-full bg-secondary">
          <div
            className={`absolute inset-y-0 left-0 rounded-full transition-[width] duration-700 ease-out ${
              pass ? "bg-primary" : "bg-destructive"
            }`}
            style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }}
          />
          {threshold !== undefined && (
            <div
              className="absolute -top-1 -bottom-1 w-0.5 rounded bg-muted-foreground"
              style={{ left: `${threshold * 100}%` }}
              title={`Gate threshold: ${threshold}`}
            />
          )}
        </div>

        <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground pt-0.5">
          <span>
            {delta !== undefined && (
              <span className={delta >= 0 ? "text-primary" : "text-destructive"}>
                {delta >= 0 ? "+" : "−"}
                {Math.abs(delta).toFixed(2)}{" "}
              </span>
            )}
          </span>
          {threshold !== undefined && <span>gate {threshold.toFixed(2)}</span>}
        </div>
      </CardContent>
    </Card>
  );
}

export function MetricTileSkeleton() {
  return (
    <Card className="border-border/60">
      <CardContent className="space-y-3 pt-6">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-7 w-16" />
        <Skeleton className="h-1.5 w-full rounded-full" />
        <Skeleton className="h-3 w-20" />
      </CardContent>
    </Card>
  );
}
