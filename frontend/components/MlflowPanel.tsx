"use client";

import { useMemo } from "react";
import { GitCommit, Workflow } from "lucide-react";
import { InteractiveTrendChart } from "@/components/EvalCharts";
import { MetricTile } from "@/components/MetricTile";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { THRESHOLDS, type MlflowRun } from "@/lib/types";

const TRACKED_METRICS = [
  "citation_validity",
  "regression_pass_rate",
  "mrr",
  "context_hit_rate",
  "refusal_correct",
  "numeric_exactness",
];

export function MlflowPanel({ runs }: { runs: MlflowRun[] }) {
  const sorted = useMemo(
    () => [...runs].sort((a, b) => b.start_time - a.start_time),
    [runs],
  );
  const latest = sorted[0];
  const previous = sorted[1];

  if (runs.length === 0) {
    return (
      <Card className="border-border/60">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base font-semibold">
            <Workflow className="size-4 text-primary" />
            Regression Tracking (MLflow)
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="max-w-prose text-sm text-muted-foreground">
            Every <code>run</code>/<code>gate</code> invocation logs its retrieval
            config next to its metrics as one MLflow run, so a change to the
            validator or the retrieval config becomes a run comparison instead
            of a one-off manual check.
          </p>
          <pre className="overflow-x-auto rounded-lg border border-border/60 bg-card p-4 font-mono text-xs text-muted-foreground">
{`cd backend
pip install -e ".[eval]"
python -m apps.evaluator.cli run --config hybrid_rrf --regression
mlflow ui --backend-store-uri sqlite:///mlflow.db`}
          </pre>
        </CardContent>
      </Card>
    );
  }

  const trendRuns = sorted.map((r) => ({
    id: r.run_id.slice(0, 8),
    config_id: r.config_id,
    metrics: r.metrics,
  }));
  const trendMetrics = TRACKED_METRICS.filter((m) =>
    trendRuns.some((r) => r.metrics[m] !== undefined),
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-2">
        <div className="flex items-center gap-2">
          <Workflow className="size-4 text-primary" />
          <h2 className="text-base font-semibold text-foreground">
            Regression Tracking (MLflow)
          </h2>
          <Badge
            variant="outline"
            className="border-primary/40 bg-primary/10 font-mono text-xs text-primary"
          >
            {runs.length} tracked run{runs.length === 1 ? "" : "s"}
          </Badge>
        </div>
        <p className="hidden font-mono text-[11px] text-muted-foreground sm:block">
          mlflow ui --backend-store-uri sqlite:///mlflow.db
        </p>
      </div>

      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricTile
          label="Citation accuracy"
          metricKey="citation_validity"
          value={latest?.metrics.citation_validity}
          previous={previous?.metrics.citation_validity}
          threshold={THRESHOLDS.citation_validity}
        />
        <MetricTile
          label="Regression pass rate"
          value={latest?.metrics.regression_pass_rate}
          previous={previous?.metrics.regression_pass_rate}
          threshold={1.0}
        />
        <MetricTile
          label="MRR"
          metricKey="mrr"
          value={latest?.metrics.mrr}
          previous={previous?.metrics.mrr}
          threshold={THRESHOLDS.mrr}
        />
        <MetricTile
          label="Context hit rate"
          metricKey="context_hit_rate"
          value={latest?.metrics.context_hit_rate}
          previous={previous?.metrics.context_hit_rate}
          threshold={THRESHOLDS.context_hit_rate}
        />
      </section>

      <Card className="border-border/60">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Tracked metric trend</CardTitle>
        </CardHeader>
        <CardContent>
          <InteractiveTrendChart
            runs={trendRuns}
            defaultMetric={trendMetrics[0] ?? "citation_validity"}
            availableMetrics={trendMetrics}
          />
        </CardContent>
      </Card>

      <Card className="border-border/60">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">MLflow run log</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="border-border/60 hover:bg-transparent">
                <TableHead>Run</TableHead>
                <TableHead>Config</TableHead>
                <TableHead>Trigger</TableHead>
                <TableHead>Commit</TableHead>
                <TableHead>Gate</TableHead>
                <TableHead className="text-right">Citation acc.</TableHead>
                <TableHead className="text-right">MRR</TableHead>
                <TableHead className="text-right">Regression</TableHead>
                <TableHead>When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((r) => (
                <TableRow key={r.run_id} className="border-border/60 hover:bg-muted/20">
                  <TableCell className="font-mono text-xs font-semibold text-foreground">
                    {r.run_name || r.run_id.slice(0, 8)}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="outline"
                      className="border-primary/30 bg-primary/5 font-mono text-[11px] text-primary"
                    >
                      {r.config_id}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary" className="font-mono text-[10px] font-normal uppercase">
                      {r.trigger}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {r.git_sha ? (
                      <span className="inline-flex items-center gap-1">
                        <GitCommit className="size-3" />
                        {r.git_sha}
                      </span>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell>
                    {r.gate_passed === "" ? (
                      <span className="text-xs text-muted-foreground">—</span>
                    ) : r.gate_passed === "True" ? (
                      <Badge
                        variant="outline"
                        className="border-primary/40 bg-primary/15 text-[10px] text-primary"
                      >
                        passed
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="border-destructive/40 text-[10px] text-destructive">
                        failed
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="tabular text-right font-mono text-xs">
                    {r.metrics.citation_validity?.toFixed(3) ?? "—"}
                  </TableCell>
                  <TableCell className="tabular text-right font-mono text-xs">
                    {r.metrics.mrr?.toFixed(3) ?? "—"}
                  </TableCell>
                  <TableCell className="tabular text-right font-mono text-xs">
                    {r.metrics.regression_pass_rate?.toFixed(3) ?? "—"}
                  </TableCell>
                  <TableCell className="font-mono text-[10px] text-muted-foreground">
                    {new Date(r.start_time).toLocaleString(undefined, {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
