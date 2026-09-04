import { Badge } from "@/components/ui/badge";
import type { Relevance } from "@/lib/types";

/**
 * Why a document was accepted or refused.
 *
 * A heuristic that rejects without showing its reasoning is unusable, so the
 * matched and missing evidence categories are always visible.
 */
export function RelevanceVerdict({
  relevance,
  forced,
}: {
  relevance: Relevance;
  forced?: boolean;
}) {
  const ok = relevance.accepted;

  return (
    <div
      className={`space-y-2 rounded-md border px-3 py-2.5 ${
        ok
          ? "border-primary/25 bg-primary/5"
          : "border-chart-3/30 bg-chart-3/5"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant="outline"
          className={
            ok
              ? "border-primary/40 text-primary"
              : "border-chart-3/40 text-chart-3"
          }
        >
          {ok ? "Financial document" : "Not recognised as financial"}
        </Badge>
        {forced && (
          <Badge variant="outline" className="border-destructive/40 text-destructive">
            indexed by override
          </Badge>
        )}
        <span className="font-mono text-[11px] text-muted-foreground">
          {relevance.matched_categories.length} of{" "}
          {relevance.matched_categories.length + relevance.missing_categories.length}{" "}
          evidence categories
        </span>
      </div>

      <p className="text-xs leading-relaxed text-muted-foreground">
        {relevance.reason}
      </p>

      {relevance.matched_categories.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {relevance.matched_categories.map((c) => (
            <span
              key={c}
              className="rounded border border-primary/25 bg-primary/10 px-1.5 py-0.5 font-mono text-[10px] text-primary"
              title={(relevance.matched[c] ?? []).join(", ")}
            >
              {c}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
