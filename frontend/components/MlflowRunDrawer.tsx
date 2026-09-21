"use client";

import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, GitCommit, Layers, Workflow } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  label,
  METRIC_DESCRIPTIONS,
  THRESHOLDS,
  type MlflowRun,
  type MlflowRunDetail,
} from "@/lib/types";

const PARAM_LABELS: Record<string, string> = {
  chunk_size: "Chunk size",
  chunk_overlap: "Chunk overlap",
  top_k: "Top K",
  rerank_top_n: "Rerank top N",
  use_bm25: "BM25",
  use_vector: "Vector",
  use_semantic_ranker: "Semantic ranker",
  embed_model: "Embed model",
  judge_model: "Judge model",
  n_questions: "Questions",
};

interface MlflowRunDrawerProps {
  run: MlflowRun | null;
  isOpen: boolean;
  onClose: () => void;
}

export function MlflowRunDrawer({ run, isOpen, onClose }: MlflowRunDrawerProps) {
  const [detail, setDetail] = useState<MlflowRunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isOpen || !run) {
      setDetail(null);
      setError("");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    fetch(`/api/eval/mlflow/runs/${encodeURIComponent(run.run_id)}`)
      .then((res) => {
        if (!res.ok) throw new Error(`run detail unavailable (${res.status})`);
        return res.json();
      })
      .then((data) => {
        if (!cancelled) setDetail(data as MlflowRunDetail);
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, run]);

  if (!isOpen || !run) return null;

  // Fall back to the summary row's own fields while the detail fetch is in
  // flight, so the drawer never opens blank.
  const metrics = detail?.metrics ?? run.metrics;
  const params = detail?.params ?? run.params;
  const gate = detail?.gate_outcome;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex max-h-[85vh] max-w-3xl flex-col gap-0 overflow-hidden border-border/70 bg-card p-0 shadow-2xl">
        <DialogHeader className="shrink-0 border-b border-border/60 bg-muted/20 px-6 py-4 text-left">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="flex size-7 items-center justify-center rounded-lg bg-primary/15 text-primary">
              <Workflow className="size-4" />
            </span>
            <DialogTitle className="font-mono text-base font-semibold tracking-tight text-foreground">
              {run.run_name || run.run_id.slice(0, 8)}
            </DialogTitle>
            <Badge variant="outline" className="border-primary/40 bg-primary/10 font-mono text-[11px] text-primary">
              {run.config_id}
            </Badge>
            <Badge variant="secondary" className="font-mono text-[11px] font-normal uppercase">
              {run.trigger}
            </Badge>
            {run.git_sha && (
              <span className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground">
                <GitCommit className="size-3" />
                {run.git_sha}
              </span>
            )}
            <span className="font-mono text-xs text-muted-foreground" suppressHydrationWarning>
              {formatDateTime(run.start_time)}
            </span>
          </div>
          <DialogDescription className="pt-1 font-mono text-xs text-muted-foreground">
            {run.run_id}
          </DialogDescription>
        </DialogHeader>

        <div className="custom-scrollbar min-h-0 grow space-y-6 overflow-y-auto p-6">
          {loading && !detail ? (
            <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
              Loading run detail…
            </div>
          ) : error ? (
            <div className="p-8 text-center text-sm text-destructive">{error}</div>
          ) : (
            <>
              <section className="space-y-2">
                <h3 className="text-sm font-semibold text-foreground">Retrieval config</h3>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                  {Object.entries(params).map(([k, v]) => (
                    <div key={k} className="rounded-md border border-border/60 bg-secondary/20 px-2.5 py-1.5">
                      <p className="text-[10px] uppercase text-muted-foreground">{PARAM_LABELS[k] ?? k}</p>
                      <p className="font-mono text-xs font-semibold text-foreground">{v || "—"}</p>
                    </div>
                  ))}
                </div>
              </section>

              <section className="space-y-2">
                <h3 className="text-sm font-semibold text-foreground">Metrics</h3>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(metrics).map(([metric, val]) => {
                    const threshold = THRESHOLDS[metric];
                    const passes = threshold === undefined || val >= threshold;
                    const desc = METRIC_DESCRIPTIONS[metric] || "";
                    return (
                      <div
                        key={metric}
                        title={desc}
                        className={`flex cursor-help items-center gap-1.5 rounded-md border px-2.5 py-1 font-mono text-xs ${
                          passes
                            ? "border-primary/25 bg-primary/5 text-foreground"
                            : "border-destructive/30 bg-destructive/10 text-destructive"
                        }`}
                      >
                        <span className="text-[10px] uppercase text-muted-foreground">{label(metric)}:</span>
                        <span className="font-bold">{val.toFixed(3)}</span>
                        {passes ? (
                          <CheckCircle2 className="size-3 shrink-0 text-primary" />
                        ) : (
                          <AlertCircle className="size-3 shrink-0 text-destructive" />
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>

              {gate && (
                <section className="space-y-2">
                  <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
                    <Layers className="size-3.5 text-primary" />
                    CI gate outcome
                    <Badge
                      variant="outline"
                      className={
                        gate.passed
                          ? "border-primary/40 bg-primary/15 text-[10px] text-primary"
                          : "border-destructive/40 text-[10px] text-destructive"
                      }
                    >
                      {gate.passed ? "passed" : "failed"}
                    </Badge>
                  </h3>
                  <div className="overflow-x-auto rounded-lg border border-border/60">
                    <table className="w-full text-xs">
                      <thead className="bg-muted/30">
                        <tr>
                          <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">Metric</th>
                          <th className="px-3 py-1.5 text-right font-medium text-muted-foreground">Value</th>
                          <th className="px-3 py-1.5 text-right font-medium text-muted-foreground">Floor</th>
                          <th className="px-3 py-1.5 text-right font-medium text-muted-foreground">Baseline</th>
                          <th className="px-3 py-1.5 text-right font-medium text-muted-foreground">Drop</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(gate.details).map(([metric, d]) => (
                          <tr key={metric} className="border-t border-border/50">
                            <td className="px-3 py-1.5 font-mono">{label(metric)}</td>
                            <td className="px-3 py-1.5 text-right font-mono">{d.value.toFixed(3)}</td>
                            <td className="px-3 py-1.5 text-right font-mono text-muted-foreground">
                              {d.min !== undefined ? d.min.toFixed(2) : "—"}
                            </td>
                            <td className="px-3 py-1.5 text-right font-mono text-muted-foreground">
                              {d.baseline !== undefined ? d.baseline.toFixed(3) : "—"}
                            </td>
                            <td className="px-3 py-1.5 text-right font-mono text-muted-foreground">
                              {d.drop !== undefined ? d.drop.toFixed(3) : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {gate.failures.length > 0 && (
                    <ul className="list-disc space-y-0.5 pl-5 text-xs text-destructive">
                      {gate.failures.map((f) => (
                        <li key={f}>{f}</li>
                      ))}
                    </ul>
                  )}
                </section>
              )}

              {!gate && run.trigger !== "ci-gate" && (
                <p className="text-xs text-muted-foreground">
                  No CI gate outcome attached - this run came from a manual{" "}
                  <code>evaluator run</code>, not <code>evaluator gate</code>.
                </p>
              )}
            </>
          )}
        </div>

        <div className="flex shrink-0 items-center justify-between border-t border-border/60 bg-muted/10 px-6 py-3 text-xs text-muted-foreground">
          <span className="font-mono">{run.run_id}</span>
          <Button variant="secondary" size="sm" onClick={onClose} className="h-7 text-xs">
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
