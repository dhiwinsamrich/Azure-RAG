import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * A score is never shown without the bar it has to clear: the notch on the
 * meter is the gate threshold, so "0.81" reads as pass or fail at a glance.
 */
export function MetricTile({
  label,
  value,
  previous,
  threshold,
}: {
  label: string;
  value?: number;
  previous?: number;
  threshold?: number;
}) {
  if (value === undefined) {
    return (
      <Card className="border-border/60">
        <CardContent className="space-y-3 pt-6">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-2xl font-bold text-muted-foreground">—</p>
        </CardContent>
      </Card>
    );
  }

  const pass = threshold === undefined || value >= threshold;
  const delta = previous === undefined ? undefined : value - previous;

  return (
    <Card className="border-border/60 transition-colors hover:border-primary/30">
      <CardContent className="space-y-3 pt-6">
        <p className="text-xs leading-tight text-muted-foreground">{label}</p>

        <p className="tabular text-2xl font-bold leading-none tracking-tight">
          {value.toFixed(2)}
        </p>

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
              title={`gate ${threshold}`}
            />
          )}
        </div>

        <p className="tabular font-mono text-[11px] text-muted-foreground">
          {delta !== undefined && (
            <span className={delta >= 0 ? "text-primary" : "text-destructive"}>
              {delta >= 0 ? "+" : "−"}
              {Math.abs(delta).toFixed(2)}{" "}
            </span>
          )}
          {threshold !== undefined && `gate ${threshold.toFixed(2)}`}
        </p>
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
