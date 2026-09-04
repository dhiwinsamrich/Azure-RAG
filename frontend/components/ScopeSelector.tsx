"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { IndexedDocument } from "@/lib/types";

/**
 * Which documents a question may be answered from.
 *
 * Empty selection means every indexed document — the same default the API
 * uses. Scope is never inferred from the question text: narrowing what a user
 * can be answered from is a decision they should make explicitly.
 */
export function ScopeSelector({
  documents,
  selected,
  onChange,
  loading,
}: {
  documents: IndexedDocument[];
  selected: string[];
  onChange: (next: string[]) => void;
  loading?: boolean;
}) {
  if (loading) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <Skeleton className="h-5 w-28" />
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-7 w-40 rounded-full" />
        ))}
      </div>
    );
  }

  if (documents.length === 0) return null;

  const all = selected.length === 0;

  function toggle(id: string) {
    onChange(
      selected.includes(id)
        ? selected.filter((d) => d !== id)
        : [...selected, id],
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        Search in
      </span>

      <button
        onClick={() => onChange([])}
        className={`rounded-full border px-3 py-1 text-xs transition-colors ${
          all
            ? "border-primary/50 bg-primary/15 text-primary"
            : "border-border/60 text-muted-foreground hover:text-foreground"
        }`}
      >
        All documents
        <span className="ml-1.5 opacity-60">{documents.length}</span>
      </button>

      {documents.map((d) => {
        const on = selected.includes(d.doc_id);
        return (
          <button
            key={d.doc_id}
            onClick={() => toggle(d.doc_id)}
            title={`${d.chunk_count} chunks${d.has_vectors ? "" : " · not embedded, keyword search only"}`}
            className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors ${
              on
                ? "border-primary/50 bg-primary/15 text-primary"
                : "border-border/60 text-muted-foreground hover:border-border hover:text-foreground"
            }`}
          >
            <span className="max-w-[220px] truncate font-mono">{d.doc_id}</span>
            {!d.has_vectors && (
              <span
                className="size-1.5 shrink-0 rounded-full bg-chart-3"
                title="no embeddings — keyword search only"
              />
            )}
            <span className="shrink-0 opacity-60">{d.chunk_count}</span>
          </button>
        );
      })}

      {!all && (
        <Badge variant="secondary" className="font-mono text-[11px] font-normal">
          {selected.length} of {documents.length} selected
        </Badge>
      )}
    </div>
  );
}
