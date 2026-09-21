"use client";

import { useEffect, useRef, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { AnswerSkeleton } from "@/components/AnswerSkeleton";
import PromptBar, { MODES, type Mode } from "@/components/PromptBar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { readSse } from "@/lib/sse";
import type {
  Citation,
  IndexedDocument,
  Source,
  TraceEvent,
  ValidationEvent,
} from "@/lib/types";

type Status = "idle" | "streaming" | "done" | "error";

export default function AskPage() {
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [validation, setValidation] = useState<ValidationEvent | null>(null);
  const [trace, setTrace] = useState<TraceEvent | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [stage, setStage] = useState("retrieving");
  const [error, setError] = useState("");
  const [documents, setDocuments] = useState<IndexedDocument[]>([]);
  const [scope, setScope] = useState<string[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [mode, setMode] = useState<Mode>("Thorough");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(true);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    fetch("/api/corpus")
      .then((r) => (r.ok ? r.json() : []))
      .then(setDocuments)
      .catch(() => setDocuments([]))
      .finally(() => setLoadingDocs(false));
  }, []);

  const scopeKey = scope.join(",");
  useEffect(() => {
    if (loadingDocs) return;
    const ctl = new AbortController();
    const qs = new URLSearchParams();
    scope.forEach((d) => qs.append("doc_ids", d));
    setLoadingSuggestions(true);
    fetch(`/api/suggestions?${qs}`, { signal: ctl.signal })
      .then((r) => (r.ok ? r.json() : { suggestions: [] }))
      .then((d) => setSuggestions(d.suggestions ?? []))
      .catch((err) => err.name !== "AbortError" && setSuggestions([]))
      .finally(() => !ctl.signal.aborted && setLoadingSuggestions(false));
    return () => ctl.abort();
    // scopeKey stands in for the scope array so a new array with the same ids doesn't refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeKey, loadingDocs, documents.length]);

  function stop() {
    abort.current?.abort();
    setStatus(answer ? "done" : "idle");
  }

  async function ask(q: string) {
    if (!q.trim()) return;

    abort.current?.abort();
    abort.current = new AbortController();
    setAnswer("");
    setCitations([]);
    setValidation(null);
    setTrace(null);
    setError("");
    setStatus("streaming");
    setStage("retrieving");

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q, doc_ids: scope, config_id: MODES[mode].configId }),
        signal: abort.current.signal,
      });

      await readSse(
        res,
        (event, data) => {
          if (event === "start") setStage("retrieving");
          else if (event === "token") {
            setStage("generating");
            setAnswer((a) => a + (data as { text: string }).text);
          } else if (event === "citations") setCitations(data as Citation[]);
          else if (event === "validation") {
            setStage("verifying citations");
            setValidation(data as ValidationEvent);
          } else if (event === "trace") setTrace(data as TraceEvent);
          else if (event === "done") setStatus("done");
          else if (event === "error") {
            setError((data as { message: string }).message);
            setStatus("error");
          }
        },
        abort.current.signal,
      );
      setStatus((s) => (s === "streaming" ? "done" : s));
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message);
        setStatus("error");
      }
    }
  }

  const thinking = status === "streaming" && !answer;
  const idle = status === "idle";
  const totalChunks = documents.reduce((n, d) => n + d.chunk_count, 0);
  const embedded = documents.filter((d) => d.has_vectors).length;

  return (
    <div className={`mx-auto w-full max-w-3xl ${idle ? "flex min-h-[calc(100dvh-8.75rem)] flex-col justify-center gap-6" : "space-y-6"}`}>
      {idle && (
        <div className="space-y-3 text-center">
          <Badge
            variant="outline"
            className="border-primary/30 bg-primary/10 px-3 py-1 font-mono text-[11px] font-normal text-primary"
          >
            <ShieldCheck className="mr-1.5 inline size-3" />
            Every citation verified
          </Badge>
          <h1 className="text-balance text-4xl font-semibold tracking-tight sm:text-5xl">
            Ask the filings
          </h1>
          <p className="mx-auto max-w-xl text-balance text-muted-foreground">
            Answers are grounded in retrieved passages, and every quote is
            checked against its source before it reaches you.
          </p>
        </div>
      )}

      <PromptBar
        value={query}
        onChange={setQuery}
        onSubmit={ask}
        onStop={stop}
        busy={status === "streaming"}
        documents={documents}
        scope={scope}
        onScopeChange={setScope}
        mode={mode}
        onModeChange={setMode}
      />

      {idle && (
        <>
          <div className="flex min-h-8 flex-wrap justify-center gap-2">
            {loadingSuggestions &&
              [64, 80, 56].map((w) => (
                <Skeleton key={w} className="h-8 rounded-full" style={{ width: `${w * 4}px` }} />
              ))}
            {!loadingSuggestions && suggestions.map((ex) => (
              <button
                key={ex}
                onClick={() => {
                  setQuery(ex);
                  ask(ex);
                }}
                className="rounded-full border border-border/60 bg-card px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
              >
                {ex}
              </button>
            ))}
          </div>

          {!loadingDocs && (
            <p className="text-center font-mono text-[11px] text-muted-foreground">
              {documents.length} documents · {totalChunks} chunks indexed · {embedded} with embeddings
            </p>
          )}
        </>
      )}

      {trace && <FilterChips trace={trace} />}

      {error && (
        <Card className="border-destructive/40 bg-destructive/10">
          <CardContent className="pt-6 text-sm text-destructive">{error}</CardContent>
        </Card>
      )}

      {thinking && <AnswerSkeleton stage={stage} />}

      {answer && (
        <Card className="border-border/60">
          <CardContent className="space-y-5 pt-6">
            {trace?.refused ? (
              <div className="space-y-3">
                <Badge variant="outline" className="border-amber-500/40 text-amber-400">
                  Not found in corpus
                </Badge>
                <p className="text-sm leading-relaxed text-muted-foreground">{answer}</p>
              </div>
            ) : (
              <AnswerBody text={answer} count={citations.length} />
            )}

            {citations.length > 0 && <CitationList citations={citations} trace={trace} />}
            {validation && trace && <QualityFooter validation={validation} trace={trace} />}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/** Renders [n] markers as interactive superscripts that scroll to the source. */
function AnswerBody({ text, count }: { text: string; count: number }) {
  const parts = text.split(/(\[\d{1,2}\])/g);
  return (
    <p className="text-[15px] leading-7">
      {parts.map((part, i) => {
        const m = /^\[(\d{1,2})\]$/.exec(part);
        if (!m) return <span key={i}>{part}</span>;
        const n = Number(m[1]);
        if (n < 1 || n > count) return null;
        return (
          <a key={i} href={`#cite-${n}`} className="cite">
            [{n}]
          </a>
        );
      })}
    </p>
  );
}

function FilterChips({ trace }: { trace: TraceEvent }) {
  const f = trace.filters as Record<string, unknown[]>;
  const chips = Object.entries(f)
    .filter(([k, v]) => k !== "doc_ids" && Array.isArray(v) && v.length > 0)
    .map(([k, v]) => `${k.replace(/_/g, " ")}: ${(v as unknown[]).join(", ")}`);
  if (chips.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        Filters applied before search
      </span>
      {chips.map((c) => (
        <Badge key={c} variant="secondary" className="font-mono text-[11px] font-normal">
          {c}
        </Badge>
      ))}
    </div>
  );
}

function CitationList({
  citations,
  trace,
}: {
  citations: Citation[];
  trace: TraceEvent | null;
}) {
  const byId = new Map((trace?.sources ?? []).map((s: Source) => [s.chunk_id, s]));
  return (
    <ol className="space-y-3 border-t border-border/60 pt-4">
      {citations.map((c, i) => {
        const s = byId.get(c.chunk_id);
        return (
          <li key={c.chunk_id + i} id={`cite-${i + 1}`} className="text-xs scroll-mt-20">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="font-mono font-semibold text-primary">[{i + 1}]</span>
              <span className="text-muted-foreground">
                {s ? `${s.header} · p.${s.page_start}` : c.chunk_id}
              </span>
              <Badge
                variant="outline"
                className="border-primary/30 px-1.5 py-0 text-[10px] text-primary"
              >
                verified
              </Badge>
            </div>
            <blockquote className="mt-1.5 border-l-2 border-border pl-3 leading-relaxed text-muted-foreground/80">
              “{c.quoted_span}”
            </blockquote>
          </li>
        );
      })}
    </ol>
  );
}

/** Evaluation in the product, not only on the dashboard. */
function QualityFooter({
  validation,
  trace,
}: {
  validation: ValidationEvent;
  trace: TraceEvent;
}) {
  const verified = validation.verdicts.length - validation.failures;
  const items = [
    {
      label: "Citations verified",
      value: `${verified}/${validation.verdicts.length}`,
      bad: validation.failures > 0,
    },
    { label: "Chunks retrieved", value: String(trace.chunks_retrieved) },
    { label: "Latency", value: `${Math.round(trace.total_ms)} ms` },
    {
      label: "Tokens",
      value: String(trace.usage.prompt_tokens + trace.usage.completion_tokens),
    },
    { label: "Cost", value: `$${trace.estimated_cost_usd.toFixed(4)}` },
  ];

  return (
    <div className="flex flex-wrap gap-x-8 gap-y-3 border-t border-border/60 pt-4">
      {items.map((i) => (
        <div key={i.label} className="space-y-0.5">
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            {i.label}
          </p>
          <p
            className={`tabular text-sm font-semibold ${
              i.bad ? "text-destructive" : "text-foreground"
            }`}
          >
            {i.value}
          </p>
        </div>
      ))}
    </div>
  );
}
