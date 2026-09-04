import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Shown while the pipeline runs. The stage labels are not decoration: the
 * pipeline really does filter, retrieve, rank, generate and then validate, so
 * the placeholder mirrors the work rather than inventing a fake progress bar.
 */
export function AnswerSkeleton({ stage }: { stage: string }) {
  return (
    <Card className="border-border/60">
      <CardContent className="space-y-6 pt-6">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="flex gap-1">
            <span className="thinking-dot size-1.5 rounded-full bg-primary" />
            <span className="thinking-dot size-1.5 rounded-full bg-primary" />
            <span className="thinking-dot size-1.5 rounded-full bg-primary" />
          </span>
          <span className="font-mono uppercase tracking-wider">{stage}</span>
        </div>

        <div className="space-y-2.5">
          <Skeleton className="h-4 w-[92%]" />
          <Skeleton className="h-4 w-[84%]" />
          <Skeleton className="h-4 w-[64%]" />
        </div>

        <div className="space-y-3 border-t border-border/60 pt-4">
          {[0, 1].map((i) => (
            <div key={i} className="space-y-2">
              <Skeleton className="h-3 w-56" />
              <Skeleton className="h-3 w-[70%]" />
            </div>
          ))}
        </div>

        <div className="flex flex-wrap gap-6 border-t border-border/60 pt-4">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="space-y-1.5">
              <Skeleton className="h-2.5 w-20" />
              <Skeleton className="h-3.5 w-12" />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
