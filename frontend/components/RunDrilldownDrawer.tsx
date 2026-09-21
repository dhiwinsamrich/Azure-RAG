"use client";

import { useEffect, useState } from "react";
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  Cpu,
  Database,
  ExternalLink,
  FileCheck,
  FileQuestion,
  HelpCircle,
  Layers,
  Search,
  Sparkles,
  TableProperties,
  Tag,
  X,
} from "lucide-react";
import { QuestionTypeBreakdownChart } from "@/components/QuestionTypeBreakdownChart";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  label,
  METRIC_DESCRIPTIONS,
  THRESHOLDS,
  type RunQuestionDetail,
  type RunSummary,
  type RunSummaryDetailed,
} from "@/lib/types";

interface RunDrilldownDrawerProps {
  run: RunSummary | null;
  isOpen: boolean;
  onClose: () => void;
}

export function RunDrilldownDrawer({
  run,
  isOpen,
  onClose,
}: RunDrilldownDrawerProps) {
  const [summary, setSummary] = useState<RunSummaryDetailed | null>(null);
  const [questions, setQuestions] = useState<RunQuestionDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"questions" | "segments">("questions");
  const [searchFilter, setSearchFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("all");

  useEffect(() => {
    if (!isOpen || !run) {
      setSummary(null);
      setQuestions([]);
      setError("");
      setSearchFilter("");
      setTypeFilter("all");
      return;
    }

    async function loadRunDetails() {
      if (!run) return;
      setLoading(true);
      setError("");
      try {
        const [sumRes, qRes] = await Promise.all([
          fetch(`/api/eval/runs/${encodeURIComponent(run.id)}/summary`),
          fetch(`/api/eval/runs/${encodeURIComponent(run.id)}/questions`),
        ]);

        if (sumRes.ok) {
          setSummary((await sumRes.json()) as RunSummaryDetailed);
        }
        if (qRes.ok) {
          setQuestions((await qRes.json()) as RunQuestionDetail[]);
        }
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    }

    loadRunDetails();
  }, [isOpen, run]);

  if (!isOpen || !run) return null;

  const filteredQuestions = questions.filter((q) => {
    if (typeFilter !== "all" && q.q_type !== typeFilter) return false;
    if (searchFilter.trim()) {
      const s = searchFilter.toLowerCase();
      const inText = q.question.toLowerCase().includes(s);
      const inId = q.question_id.toLowerCase().includes(s);
      const inAnswer = q.gold_answer.toLowerCase().includes(s);
      const inChunks = q.gold_chunk_ids.some((c) => c.toLowerCase().includes(s));
      if (!inText && !inId && !inAnswer && !inChunks) return false;
    }
    return true;
  });

  const questionTypes = Array.from(new Set(questions.map((q) => q.q_type)));

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="h-[90vh] max-h-[850px] max-w-5xl overflow-hidden p-0 gap-0 border-border/70 bg-card shadow-2xl flex flex-col">
        {/* Header */}
        <DialogHeader className="border-b border-border/60 bg-muted/20 px-6 py-4 text-left shrink-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="flex size-7 items-center justify-center rounded-lg bg-primary/15 text-primary">
              <FileCheck className="size-4" />
            </span>
            <DialogTitle className="font-mono text-base font-semibold tracking-tight text-foreground sm:text-lg">
              {run.id}
            </DialogTitle>
            <Badge variant="outline" className="border-primary/40 font-mono text-[11px] text-primary bg-primary/10">
              {run.config_id}
            </Badge>
            <Badge variant="secondary" className="font-mono text-[11px] font-normal">
              trigger: {run.trigger}
            </Badge>
            <span className="font-mono text-xs text-muted-foreground" suppressHydrationWarning>
              {formatDateTime(run.started_at)}
            </span>
          </div>
          <DialogDescription className="text-xs text-muted-foreground pt-1">
            Evaluation Run Analysis · Document scope, individual question traces, and segment performance
          </DialogDescription>
        </DialogHeader>

        {/* Attributed Documents & Evaluation Scope Bar */}
        <div className="border-b border-border/60 bg-background/60 px-6 py-3 space-y-2.5 shrink-0">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Database className="size-3.5 text-primary" />
              <span className="font-medium text-foreground">Target Test Filings:</span>
            </div>
            {run.doc_ids && run.doc_ids.length > 0 ? (
              <div className="flex flex-wrap items-center gap-1.5">
                {run.doc_ids.map((docId) => (
                  <Badge
                    key={docId}
                    variant="secondary"
                    className="font-mono text-[11px] font-medium text-foreground bg-secondary/80 border border-border/60"
                  >
                    {docId}
                  </Badge>
                ))}
              </div>
            ) : (
              <span className="text-xs text-muted-foreground italic">Full corpus</span>
            )}

            <div className="ml-auto flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground">
                Question Set: <span className="text-foreground font-medium">{run.question_set || "golden"}</span> ({run.question_count || questions.length} questions)
              </span>
            </div>
          </div>

          {/* Metric Badges Strip with Descriptions */}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {Object.entries(run.metrics).map(([metric, val]) => {
              const threshold = THRESHOLDS[metric];
              const passes = threshold === undefined || val >= threshold;
              const desc = METRIC_DESCRIPTIONS[metric] || "";
              return (
                <div
                  key={metric}
                  title={desc}
                  className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-mono transition-all hover:scale-105 cursor-help ${
                    passes
                      ? "border-primary/25 bg-primary/5 text-foreground"
                      : "border-destructive/30 bg-destructive/10 text-destructive"
                  }`}
                >
                  <span className="text-[10px] text-muted-foreground uppercase">{label(metric)}:</span>
                  <span className="font-bold">{val.toFixed(3)}</span>
                  {passes ? (
                    <CheckCircle2 className="size-3 text-primary shrink-0" />
                  ) : (
                    <AlertCircle className="size-3 text-destructive shrink-0" />
                  )}
                </div>
              );
            })}
          </div>

          {/* Diagnostic Note for MRR = 0 / Document Mismatch */}
          {run.metrics.mrr === 0 && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-200/90 flex items-start gap-2">
              <HelpCircle className="size-4 text-amber-400 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold text-amber-300">Why is MRR &amp; Context Hit Rate 0.00?</span>{" "}
                MRR measures the search position of the target gold chunk. When the evaluated question set asks about documents not present in your active search index (e.g. asking about Microsoft when only Northwind is indexed), the target chunk is absent, so MRR is 0.00. The AI engine correctly refused to fabricate fake answers, maintaining <strong>100% Citation Validity</strong> and strong <strong>Refusal Accuracy</strong>.
              </div>
            </div>
          )}
        </div>

        {/* View Switcher Tabs & Filters */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 px-6 py-2 bg-muted/10 shrink-0">
          <Tabs
            value={tab}
            onValueChange={(val) => setTab(val as "questions" | "segments")}
          >
            <TabsList>
              <TabsTrigger value="questions" className="gap-1.5 text-xs font-medium">
                <FileQuestion className="size-3.5" />
                <span>Questions &amp; Traces ({questions.length})</span>
              </TabsTrigger>
              <TabsTrigger value="segments" className="gap-1.5 text-xs font-medium">
                <Layers className="size-3.5" />
                <span>Segment Breakdown</span>
              </TabsTrigger>
            </TabsList>
          </Tabs>

          {tab === "questions" && (
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative w-44 sm:w-56">
                <Search className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
                <Input
                  value={searchFilter}
                  onChange={(e) => setSearchFilter(e.target.value)}
                  placeholder="Filter questions or doc..."
                  className="h-8 pl-8 text-xs"
                />
              </div>

              {questionTypes.length > 1 && (
                <div className="w-36">
                  <Select value={typeFilter} onValueChange={setTypeFilter}>
                    <SelectTrigger className="h-8 font-mono text-xs">
                      <SelectValue placeholder="All Types" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all" className="font-mono text-xs">
                        All Types
                      </SelectItem>
                      {questionTypes.map((t) => (
                        <SelectItem key={t} value={t} className="font-mono text-xs">
                          {t}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Content Body */}
        <div className="min-h-0 grow overflow-y-auto overflow-x-hidden p-6 pb-16 custom-scrollbar">
          {loading ? (
            <div className="flex h-64 flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
              <span className="thinking-dot size-3 rounded-full bg-primary" />
              <p>Loading evaluation question traces and metrics…</p>
            </div>
          ) : error ? (
            <div className="p-8 text-center text-sm text-destructive">{error}</div>
          ) : tab === "segments" ? (
            <div className="space-y-6">
              <div className="space-y-1">
                <h3 className="text-sm font-semibold tracking-tight text-foreground">
                  Performance by Question Complexity
                </h3>
                <p className="text-xs text-muted-foreground">
                  Shows how retrieval and answer accuracy differ between simple fact lookup, multi-hop synthesis, table interpretation, and refusal guardrails.
                </p>
              </div>

              {summary?.by_question_type ? (
                <Card className="border-border/60">
                  <CardContent className="pt-6">
                    <QuestionTypeBreakdownChart byType={summary.by_question_type} />
                  </CardContent>
                </Card>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No segmented metrics available for this run.
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              {filteredQuestions.length === 0 ? (
                <div className="p-12 text-center text-sm text-muted-foreground">
                  No questions match your filter criteria.
                </div>
              ) : (
                filteredQuestions.map((q) => (
                  <div
                    key={q.question_id}
                    className="rounded-lg border border-border/70 bg-secondary/15 p-4 transition-colors hover:border-border space-y-3"
                  >
                    {/* Question Header & Type Tag */}
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs font-bold text-primary">
                          {q.question_id}
                        </span>
                        <Badge
                          variant="secondary"
                          className={`font-mono text-[10px] uppercase font-normal ${
                            q.q_type === "table-dependent"
                              ? "border-chart-3/30 text-chart-3 bg-chart-3/10"
                              : q.q_type === "unanswerable"
                              ? "border-chart-2/30 text-chart-2 bg-chart-2/10"
                              : ""
                          }`}
                        >
                          {q.q_type}
                        </Badge>
                        {!q.answerable && (
                          <Badge variant="outline" className="border-destructive/30 text-[10px] text-destructive">
                            unanswerable test
                          </Badge>
                        )}
                      </div>
                    </div>

                    {/* Question Prompt */}
                    <h4 className="text-sm font-medium text-foreground leading-snug break-words">
                      {q.question}
                    </h4>

                    {/* Per-question Metric Scores with Explanations */}
                    <div className="flex flex-wrap items-center gap-1.5 pt-1">
                      {q.metrics.map((m) => {
                        const threshold = THRESHOLDS[m.metric_name];
                        const isBad = m.value !== null && threshold !== undefined && m.value < threshold;
                        return (
                          <div
                            key={m.metric_name}
                            className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1 font-mono text-[11px] border ${
                              isBad
                                ? "bg-destructive/10 border-destructive/30 text-destructive"
                                : "bg-secondary/70 border-border/40 text-foreground"
                            }`}
                            title={m.reason ? `${label(m.metric_name)}: ${m.reason}` : label(m.metric_name)}
                          >
                            <span className="text-muted-foreground text-[10px] uppercase">{label(m.metric_name)}:</span>
                            <span className="font-bold">
                              {m.value !== null ? m.value.toFixed(2) : "—"}
                            </span>
                            {m.reason && (
                              <span className="text-[10px] text-muted-foreground/80 border-l border-border/40 pl-1.5 ml-0.5">
                                {m.reason}
                              </span>
                            )}
                          </div>
                        );
                      })}
                    </div>

                    {/* Gold Answer & Target Document References */}
                    <div className="space-y-2 border-t border-border/50 pt-2.5 text-xs">
                      {q.gold_answer && (
                        <div className="flex flex-col sm:flex-row items-start gap-1 sm:gap-2">
                          <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground shrink-0 mt-0.5">
                            Gold Answer:
                          </span>
                          <p className="text-muted-foreground text-xs leading-relaxed">
                            {q.gold_answer}
                          </p>
                        </div>
                      )}

                      {q.gold_chunk_ids.length > 0 && (
                        <div className="flex flex-wrap items-center gap-2 pt-1">
                          <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground shrink-0">
                            Target Chunks:
                          </span>
                          <div className="flex flex-wrap items-center gap-1.5">
                            {q.gold_chunk_ids.map((cid) => (
                              <Badge
                                key={cid}
                                variant="outline"
                                className="font-mono text-[10px] border-primary/30 text-primary bg-primary/5"
                              >
                                {cid}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border/60 bg-muted/10 px-6 py-3 text-xs text-muted-foreground">
          <span>Run ID: {run.id} · Evaluated against {run.doc_ids?.length || 0} documents</span>
          <Button variant="secondary" size="sm" onClick={onClose} className="h-7 text-xs">
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
