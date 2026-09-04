import { MetricTileSkeleton } from "@/components/MetricTile";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Streamed by Next while the page's server-side fetches resolve. Its shape
 * matches the real page so the layout does not jump when data lands.
 */
export default function EvalLoading() {
  return (
    <div className="space-y-8">
      <div className="flex items-center gap-3">
        <div className="space-y-2">
          <Skeleton className="h-7 w-52" />
          <Skeleton className="h-3 w-64" />
        </div>
        <Skeleton className="ml-auto h-6 w-28 rounded-full" />
      </div>

      <section className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <MetricTileSkeleton key={i} />
        ))}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        {[0, 1].map((i) => (
          <Card key={i} className="border-border/60">
            <CardHeader>
              <Skeleton className="h-4 w-56" />
            </CardHeader>
            <CardContent>
              <ChartSkeleton />
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="border-border/60">
        <CardHeader>
          <Skeleton className="h-4 w-28" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

/** Bars of varying height read as a chart rather than a grey slab. */
function ChartSkeleton() {
  const heights = [45, 70, 35, 85, 55, 75, 40, 65];
  return (
    <div className="flex h-[300px] items-end gap-3 px-2 pb-6">
      {heights.map((h, i) => (
        <Skeleton key={i} className="flex-1 rounded-t-sm" style={{ height: `${h}%` }} />
      ))}
    </div>
  );
}
