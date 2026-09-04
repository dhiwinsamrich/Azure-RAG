"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { ChunkView } from "@/lib/types";

/**
 * Master-detail rather than a stack of cards.
 *
 * A vertical list of every chunk stays scannable at a glance, and exactly one
 * body is rendered at a time — so the page has a single scrollbar instead of
 * one per chunk nested inside the page's own.
 */
export function ChunkExplorer({ chunks }: { chunks: ChunkView[] }) {
  const [selected, setSelected] = useState(0);
  const chunk = chunks[selected];
  const maxTokens = Math.max(...chunks.map((c) => c.token_count), 1);

  if (chunks.length === 0) {
    return (
      <p className="rounded-lg border border-border/60 p-6 text-sm text-muted-foreground">
        No chunks were produced from this document.
      </p>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
      <div className="max-h-[640px] overflow-y-auto rounded-lg border border-border/60 custom-scrollbar">
        {chunks.map((c, i) => {
          const active = i === selected;
          return (
            <button
              key={c.id}
              onClick={() => setSelected(i)}
              className={`flex w-full flex-col gap-1.5 border-b border-border/60 px-3 py-2.5 text-left transition-colors last:border-b-0 ${
                active ? "bg-primary/10" : "hover:bg-accent/50"
              }`}
            >
              <div className="flex items-center gap-2">
                <span
                  className={`font-mono text-xs font-semibold ${
                    active ? "text-primary" : "text-muted-foreground"
                  }`}
                >
                  #{c.chunk_index}
                </span>
                <span className="truncate text-xs">
                  {c.section_path.split(" > ").pop() || "—"}
                </span>
                <span className="grow" />
                {c.contains_table && (
                  <span
                    className="size-1.5 shrink-0 rounded-full bg-chart-3"
                    title="contains a table"
                  />
                )}
                <span className="tabular shrink-0 font-mono text-[10px] text-muted-foreground">
                  {c.token_count}
                </span>
              </div>
              {/* Relative token size, so outliers are obvious without reading. */}
              <span className="block h-1 w-full rounded-full bg-secondary">
                <span
                  className={`block h-full rounded-full ${
                    active ? "bg-primary" : "bg-muted-foreground/40"
                  }`}
                  style={{ width: `${(c.token_count / maxTokens) * 100}%` }}
                />
              </span>
            </button>
          );
        })}
      </div>

      <ChunkDetail chunk={chunk} />
    </div>
  );
}

function ChunkDetail({ chunk }: { chunk: ChunkView }) {
  const [showVector, setShowVector] = useState(false);
  const e = chunk.embedding;

  return (
    <Card className="border-border/60">
      <CardContent className="space-y-4 pt-5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-semibold text-primary">
            #{chunk.chunk_index}
          </span>
          <span className="font-mono text-[11px] break-all text-muted-foreground">
            {chunk.id}
          </span>
          <span className="grow" />
          {chunk.contains_table && (
            <Badge variant="outline" className="border-chart-3/40 text-chart-3">
              table kept whole
            </Badge>
          )}
          <Badge variant="secondary" className="font-mono text-[11px] font-normal">
            {chunk.token_count} tok
          </Badge>
          <Badge variant="secondary" className="font-mono text-[11px] font-normal">
            {chunk.page_start === chunk.page_end
              ? `p.${chunk.page_start}`
              : `pp.${chunk.page_start}–${chunk.page_end}`}
          </Badge>
        </div>

        {chunk.section_path && (
          <p className="text-xs text-muted-foreground">
            {chunk.section_path.split(" > ").map((part, i, all) => (
              <span key={i}>
                <span className={i === all.length - 1 ? "text-foreground" : ""}>
                  {part}
                </span>
                {i < all.length - 1 && <span className="px-1.5 opacity-40">›</span>}
              </span>
            ))}
          </p>
        )}

        {chunk.context_header && (
          <div className="rounded-md border border-primary/20 bg-primary/5 px-3 py-2">
            <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              Prepended by the chunker so the text stands alone
            </p>
            <p className="mt-1 font-mono text-xs text-primary">{chunk.context_header}</p>
          </div>
        )}

        {/* The page scrolls, not this block: no scrollbar inside a scrollbar. */}
        <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-secondary/40 p-3 font-mono text-xs leading-relaxed text-foreground/90">
          {chunk.body}
        </pre>

        {e && (
          <div className="space-y-2 border-t border-border/60 pt-3">
            <div className="flex flex-wrap items-center gap-4">
              <Stat label="dims" value={String(e.dims)} />
              <Stat label="‖vector‖" value={e.norm.toFixed(3)} />
              <button
                onClick={() => setShowVector((v) => !v)}
                className="ml-auto font-mono text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
              >
                {showVector ? "hide values" : "show values"}
              </button>
            </div>
            <Sparkline values={e.preview} />
            {showVector && (
              <pre className="max-h-32 overflow-auto rounded-md bg-secondary/40 p-2 font-mono text-[10px] text-muted-foreground">
                [{e.preview.join(", ")} … {e.dims - e.preview.length} more]
              </pre>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span className="tabular font-mono text-xs font-semibold">{value}</span>
    </span>
  );
}

/** First slice of the vector, drawn as diverging bars around zero. */
function Sparkline({ values }: { values: number[] }) {
  const max = Math.max(...values.map(Math.abs), 1e-6);
  return (
    <div className="flex h-10 items-center gap-px" title="first 48 dimensions">
      {values.map((v, i) => {
        const h = Math.max(2, (Math.abs(v) / max) * 18);
        return (
          <span key={i} className="flex h-full flex-1 flex-col justify-center">
            <span
              className={`w-full rounded-[1px] ${v >= 0 ? "bg-primary/70" : "bg-chart-2/70"}`}
              style={{
                height: `${h}px`,
                marginTop: v >= 0 ? `${18 - h}px` : 0,
                marginBottom: v < 0 ? `${18 - h}px` : 0,
              }}
            />
          </span>
        );
      })}
    </div>
  );
}

export function ChunkExplorerSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
      <div className="space-y-px rounded-lg border border-border/60 p-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="space-y-1.5 px-1 py-2">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-1 w-full rounded-full" />
          </div>
        ))}
      </div>
      <Card className="border-border/60">
        <CardContent className="space-y-4 pt-5">
          <Skeleton className="h-4 w-64" />
          <Skeleton className="h-12 w-full rounded-md" />
          <Skeleton className="h-40 w-full rounded-md" />
        </CardContent>
      </Card>
    </div>
  );
}
