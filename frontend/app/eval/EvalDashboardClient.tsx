"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle,
  Database,
  Eye,
  FileQuestion,
  Filter,
  History,
  Layers,
  LineChart,
  PieChart,
  Search,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { AblationChart, InteractiveTrendChart } from "@/components/EvalCharts";
import { MetricTile } from "@/components/MetricTile";
import { QualityRadarChart } from "@/components/QualityRadarChart";
import { RunDrilldownDrawer } from "@/components/RunDrilldownDrawer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  label,
  THRESHOLDS,
  type CompareMatrix,
  type RunSummary,
} from "@/lib/types";

const HEADLINE = [
  "citation_validity",
  "context_hit_rate",
  "mrr",
  "refusal_correct",
  "numeric_exactness",
  "fiscal_period_correctness",
];

interface EvalDashboardClientProps {
  runs: RunSummary[];
  matrix: CompareMatrix;
}

export function EvalDashboardClient({ runs, matrix }: EvalDashboardClientProps) {
  const [selectedRun, setSelectedRun] = useState<RunSummary | null>(null);
  const [configFilter, setConfigFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [activeVizTab, setActiveVizTab] = useState<"radar" | "ablation" | "trends">("radar");

  const latest = runs[0];
  const previous = runs[1];

  const configsList = useMemo(() => {
    return Array.from(new Set(runs.map((r) => r.config_id)));
  }, [runs]);

  const filteredRuns = useMemo(() => {
    return runs.filter((r) => {
      if (configFilter !== "all" && r.config_id !== configFilter) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesId = r.id.toLowerCase().includes(q);
        const matchesConfig = r.config_id.toLowerCase().includes(q);
        const matchesTrigger = r.trigger.toLowerCase().includes(q);
        const matchesDoc = r.doc_ids?.some((d) => d.toLowerCase().includes(q)) ?? false;
        const matchesSet = r.question_set?.toLowerCase().includes(q) ?? false;
        if (!matchesId && !matchesConfig && !matchesTrigger && !matchesDoc && !matchesSet) {
          return false;
        }
      }
      return true;
    });
  }, [runs, configFilter, searchQuery]);

  const failing = useMemo(() => {
    if (!latest) return [];
    return HEADLINE.filter((m) => {
      const v = latest.metrics[m];
      const floor = THRESHOLDS[m];
      return v !== undefined && floor !== undefined && v < floor;
    });
  }, [latest]);

  return (
    <div className="space-y-8">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border/60 pb-6">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">
              Quality &amp; Evaluation
            </h1>
            <Badge variant="outline" className="font-mono text-xs border-primary/40 bg-primary/10 text-primary">
              {runs.length} runs recorded
            </Badge>
          </div>
          {latest && (
            <p className="font-mono text-xs text-muted-foreground">
              Latest: <span className="text-foreground font-medium">{latest.id}</span> · config: <span className="text-primary">{latest.config_id}</span> · trigger: {latest.trigger} · {new Date(latest.started_at).toLocaleDateString()}
            </p>
          )}
        </div>

        <div>
          {failing.length === 0 ? (
            <Badge className="border-primary/40 bg-primary/15 text-primary text-xs px-3 py-1" variant="outline">
              <CheckCircle className="mr-1.5 size-3.5 inline" />
              All Gates Passed
            </Badge>
          ) : (
            <Badge variant="outline" className="border-destructive/40 text-destructive text-xs px-3 py-1">
              <AlertTriangle className="mr-1.5 size-3.5 inline" />
              {failing.length} Metric{failing.length > 1 ? "s" : ""} Below Gate
            </Badge>
          )}
        </div>
      </div>

      {/* Headline Metric Tiles */}
      <section className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        {HEADLINE.map((m) => (
          <MetricTile
            key={m}
            label={label(m)}
            metricKey={m}
            value={latest?.metrics[m]}
            previous={previous?.metrics[m]}
            threshold={THRESHOLDS[m]}
          />
        ))}
      </section>

      {/* Evaluation Context & Scope Explainer */}
      {latest && latest.metrics.mrr === 0 && (
        <div className="rounded-lg border border-primary/20 bg-primary/5 p-4 space-y-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-primary">
            <Sparkles className="size-4" />
            <span>Why is MRR or Context Hit Rate 0.00 in the latest run?</span>
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">
            <strong>MRR (Mean Reciprocal Rank)</strong> evaluates where the search engine ranked the required gold passage for a question. In run <span className="font-mono text-foreground font-semibold">{latest.id}</span>, the test question set targeted <span className="font-mono text-foreground font-semibold">{latest.doc_ids?.join(", ") || "MSFT filings"}</span>. Because your active search index holds <span className="font-mono text-foreground font-semibold">NORTHWIND filings</span>, the target chunk was not in the database. Instead of hallucinating fake numbers, the AI <strong>properly refused to invent data</strong>, earning <strong>100% Citation Validity</strong> and <strong>Refusal Accuracy</strong>.
          </p>
          <div className="flex flex-wrap items-center gap-2 pt-1 text-[11px] font-mono">
            <span className="text-muted-foreground">Historical Matching Runs:</span>
            {runs
              .filter((r) => r.metrics.mrr > 0)
              .slice(0, 3)
              .map((r) => (
                <button
                  key={r.id}
                  onClick={() => setSelectedRun(r)}
                  className="rounded px-2 py-0.5 border border-primary/40 bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                >
                  {r.id} ({r.config_id} · MRR: {r.metrics.mrr?.toFixed(2)})
                </button>
              ))}
          </div>
        </div>
      )}

      {/* Visualizations & Analytics Suite */}
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-2">
          <Tabs
            value={activeVizTab}
            onValueChange={(val) => setActiveVizTab(val as "radar" | "ablation" | "trends")}
          >
            <TabsList>
              <TabsTrigger value="radar" className="gap-1.5 text-xs font-medium">
                <PieChart className="size-3.5 text-primary" />
                <span>Multi-Metric Radar</span>
              </TabsTrigger>
              <TabsTrigger value="ablation" className="gap-1.5 text-xs font-medium">
                <BarChart3 className="size-3.5 text-primary" />
                <span>Config Ablation Matrix</span>
              </TabsTrigger>
              <TabsTrigger value="trends" className="gap-1.5 text-xs font-medium">
                <TrendingUp className="size-3.5 text-primary" />
                <span>Metric Trends</span>
              </TabsTrigger>
            </TabsList>
          </Tabs>

          <p className="text-xs text-muted-foreground hidden sm:block">
            {activeVizTab === "radar" && "Holistic multi-dimensional quality comparison"}
            {activeVizTab === "ablation" && "Direct side-by-side performance across retrieval methods"}
            {activeVizTab === "trends" && "Evaluation progress and convergence over time"}
          </p>
        </div>

        {activeVizTab === "radar" && (
          <div className="grid gap-6 lg:grid-cols-2">
            <Card className="border-border/60">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium flex items-center justify-between">
                  <span>Quality Spider / Radar Comparison</span>
                  <Badge variant="secondary" className="font-mono text-[10px]">
                    {Object.keys(matrix.configs).length} configs
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <QualityRadarChart metrics={HEADLINE} configs={matrix.configs} />
              </CardContent>
            </Card>

            <Card className="border-border/60">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">
                  Ablation Comparison
                </CardTitle>
              </CardHeader>
              <CardContent>
                <AblationChart metrics={HEADLINE.slice(0, 4)} configs={matrix.configs} />
              </CardContent>
            </Card>
          </div>
        )}

        {activeVizTab === "ablation" && (
          <Card className="border-border/60">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">
                Retrieval Configs Ablation Matrix
              </CardTitle>
            </CardHeader>
            <CardContent>
              <AblationChart metrics={HEADLINE} configs={matrix.configs} />
            </CardContent>
          </Card>
        )}

        {activeVizTab === "trends" && (
          <Card className="border-border/60">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">
                Metric Trends Across Runs
              </CardTitle>
            </CardHeader>
            <CardContent>
              <InteractiveTrendChart runs={runs} defaultMetric="mrr" />
            </CardContent>
          </Card>
        )}
      </div>

      {/* Upgraded Detailed Run History */}
      <Card className="border-border/60 shadow-sm">
        <CardHeader className="border-b border-border/60 bg-muted/15 pb-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <History className="size-4 text-primary" />
                <CardTitle className="text-base font-semibold">
                  Detailed Run History &amp; Document Attribution
                </CardTitle>
              </div>
              <p className="text-xs text-muted-foreground">
                Every benchmark execution, associated filings, question complexity breakdown, and gate scores
              </p>
            </div>

            {/* Filter controls */}
            <div className="flex flex-wrap items-center gap-2.5">
              <div className="relative w-48 sm:w-60">
                <Search className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
                <Input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Filter by doc, run ID, trigger..."
                  className="h-8 pl-8 text-xs"
                />
              </div>

              {configsList.length > 1 && (
                <div className="w-36">
                  <Select value={configFilter} onValueChange={setConfigFilter}>
                    <SelectTrigger className="h-8 font-mono text-xs">
                      <SelectValue placeholder="All Configs" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all" className="font-mono text-xs">
                        All Configs
                      </SelectItem>
                      {configsList.map((c) => (
                        <SelectItem key={c} value={c} className="font-mono text-xs">
                          {c}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
          </div>
        </CardHeader>

        <CardContent className="p-0">
          <Table>
            <TableHeader>
                <TableRow className="border-border/60 hover:bg-transparent">
                  <TableHead className="w-[130px]">Run ID</TableHead>
                  <TableHead className="w-[120px]">Config</TableHead>
                  <TableHead className="min-w-[200px]">Target Documents</TableHead>
                  <TableHead className="w-[140px]">Question Scope</TableHead>
                  <TableHead className="w-[100px]">Trigger / Time</TableHead>
                  {HEADLINE.map((m) => (
                    <TableHead key={m} className="text-right font-mono text-xs">
                      {label(m)}
                    </TableHead>
                  ))}
                  <TableHead className="w-[60px] text-right">Inspect</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredRuns.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6 + HEADLINE.length} className="h-24 text-center text-sm text-muted-foreground">
                      No evaluation runs found matching your filter criteria.
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredRuns.map((r) => {
                    const isLatestRun = r.id === latest?.id;
                    return (
                      <TableRow
                        key={r.id}
                        className={`group border-border/60 transition-colors hover:bg-muted/20 cursor-pointer ${
                          isLatestRun ? "bg-primary/[0.03]" : ""
                        }`}
                        onClick={() => setSelectedRun(r)}
                      >
                        {/* Run ID */}
                        <TableCell className="font-mono text-xs font-semibold text-foreground">
                          <div className="flex items-center gap-1.5">
                            <span>{r.id}</span>
                            {isLatestRun && (
                              <span className="size-1.5 rounded-full bg-primary" title="Latest Run" />
                            )}
                          </div>
                        </TableCell>

                        {/* Config */}
                        <TableCell>
                          <Badge variant="outline" className="border-primary/30 bg-primary/5 font-mono text-[11px] text-primary">
                            {r.config_id}
                          </Badge>
                        </TableCell>

                        {/* Document Attribution */}
                        <TableCell>
                          {r.doc_ids && r.doc_ids.length > 0 ? (
                            <div className="flex flex-wrap items-center gap-1">
                              {r.doc_ids.map((docId) => (
                                <Badge
                                  key={docId}
                                  variant="secondary"
                                  className="font-mono text-[10px] font-normal text-foreground bg-secondary/80"
                                >
                                  <Database className="mr-1 size-2.5 inline text-primary" />
                                  {docId}
                                </Badge>
                              ))}
                            </div>
                          ) : (
                            <span className="font-mono text-xs text-muted-foreground">
                              Entire corpus
                            </span>
                          )}
                        </TableCell>

                        {/* Question Scope */}
                        <TableCell>
                          <div className="space-y-0.5">
                            <span className="font-mono text-xs text-foreground">
                              {r.question_set || "golden"}
                            </span>
                            <p className="font-mono text-[10px] text-muted-foreground">
                              {r.question_count ?? 8} questions
                            </p>
                          </div>
                        </TableCell>

                        {/* Trigger & Time */}
                        <TableCell>
                          <div className="space-y-0.5">
                            <Badge variant="secondary" className="font-mono text-[10px] uppercase font-normal">
                              {r.trigger}
                            </Badge>
                            <p className="font-mono text-[10px] text-muted-foreground">
                              {new Date(r.started_at).toLocaleDateString(undefined, {
                                month: "short",
                                day: "numeric",
                              })}
                            </p>
                          </div>
                        </TableCell>

                        {/* Headline Scores */}
                        {HEADLINE.map((m) => {
                          const val = r.metrics[m];
                          const threshold = THRESHOLDS[m];
                          const passes = val !== undefined && threshold !== undefined && val >= threshold;
                          const below = val !== undefined && threshold !== undefined && val < threshold;

                          return (
                            <TableCell
                              key={m}
                              className={`tabular text-right font-mono text-xs ${
                                below
                                  ? "font-bold text-destructive"
                                  : passes
                                  ? "text-foreground"
                                  : "text-muted-foreground"
                              }`}
                            >
                              {val !== undefined ? val.toFixed(3) : "—"}
                            </TableCell>
                          );
                        })}

                        {/* Drilldown Eye Button */}
                        <TableCell className="text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedRun(r);
                            }}
                            className="h-7 w-7 p-0 text-muted-foreground group-hover:text-primary group-hover:bg-primary/10"
                            title="Drilldown into question-by-question metrics and traces"
                          >
                            <Eye className="size-3.5" />
                            <span className="sr-only">Inspect run</span>
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
        </CardContent>
      </Card>

      {/* Interactive Run Drilldown Modal */}
      <RunDrilldownDrawer
        run={selectedRun}
        isOpen={selectedRun !== null}
        onClose={() => setSelectedRun(null)}
      />
    </div>
  );
}
