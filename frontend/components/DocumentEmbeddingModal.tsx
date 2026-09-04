"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Check,
  Copy,
  Database,
  Eye,
  FileSpreadsheet,
  FileText,
  Filter,
  Layers,
  Search,
  Sparkles,
  TableProperties,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
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
import type { ChunkView, IndexedDocument } from "@/lib/types";

interface DocumentEmbeddingModalProps {
  doc: IndexedDocument | null;
  isOpen: boolean;
  onClose: () => void;
}

interface DocumentChunkResponse {
  doc_id: string;
  embed_dims: number;
  chunks: ChunkView[];
}

export function DocumentEmbeddingModal({
  doc,
  isOpen,
  onClose,
}: DocumentEmbeddingModalProps) {
  const [data, setData] = useState<DocumentChunkResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [tableOnly, setTableOnly] = useState(false);
  const [showRawVector, setShowRawVector] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!isOpen || !doc) {
      setData(null);
      setError("");
      setSelectedIdx(0);
      setSearchQuery("");
      setTableOnly(false);
      setShowRawVector(false);
      return;
    }

    async function fetchDocChunks() {
      if (!doc) return;
      setLoading(true);
      setError("");
      try {
        const res = await fetch(`/api/corpus/${encodeURIComponent(doc.doc_id)}`);
        if (!res.ok) {
          throw new Error(`Failed to load document data (${res.status})`);
        }
        const json = (await res.json()) as DocumentChunkResponse;
        setData(json);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    }

    fetchDocChunks();
  }, [isOpen, doc]);

  const chunks = data?.chunks ?? [];
  const maxTokens = Math.max(...chunks.map((c) => c.token_count), 1);

  const filteredChunks = useMemo(() => {
    return chunks.filter((c) => {
      if (tableOnly && !c.contains_table) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesBody = c.body.toLowerCase().includes(q);
        const matchesSection = c.section_path.toLowerCase().includes(q);
        const matchesId = c.id.toLowerCase().includes(q);
        if (!matchesBody && !matchesSection && !matchesId) return false;
      }
      return true;
    });
  }, [chunks, tableOnly, searchQuery]);

  const activeChunk = filteredChunks[selectedIdx] ?? filteredChunks[0] ?? null;

  const totalTokens = chunks.reduce((acc, c) => acc + c.token_count, 0);
  const avgTokens = chunks.length ? Math.round(totalTokens / chunks.length) : 0;
  const tableChunkCount = chunks.filter((c) => c.contains_table).length;
  const embedDims = data?.embed_dims || activeChunk?.embedding?.dims || 0;

  const avgNorm = useMemo(() => {
    const norms = chunks
      .map((c) => c.embedding?.norm)
      .filter((n): n is number => typeof n === "number");
    if (!norms.length) return null;
    return (norms.reduce((a, b) => a + b, 0) / norms.length).toFixed(4);
  }, [chunks]);

  const copyVectorValues = () => {
    if (!activeChunk?.embedding?.preview) return;
    navigator.clipboard.writeText(JSON.stringify(activeChunk.embedding.preview));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!isOpen || !doc) return null;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="h-[90vh] max-h-[850px] max-w-5xl overflow-hidden p-0 gap-0 border-border/70 bg-card shadow-2xl flex flex-col">
        {/* Header */}
        <DialogHeader className="border-b border-border/60 bg-muted/20 px-6 py-4 text-left shrink-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="flex size-7 items-center justify-center rounded-lg bg-primary/15 text-primary">
              <Database className="size-4" />
            </span>
            <DialogTitle className="font-mono text-base font-semibold tracking-tight text-foreground sm:text-lg">
              {doc.doc_id}
            </DialogTitle>
            {doc.doc_type && doc.doc_type !== "unknown" && (
              <Badge variant="secondary" className="font-mono text-[11px] font-normal">
                {doc.doc_type}
              </Badge>
            )}
            {doc.fiscal_year && (
              <Badge variant="secondary" className="font-mono text-[11px] font-normal">
                FY{doc.fiscal_year}
              </Badge>
            )}
            {embedDims > 0 ? (
              <Badge className="border-primary/40 bg-primary/15 font-mono text-[11px] font-normal text-primary" variant="outline">
                <Sparkles className="mr-1 size-3 inline" />
                {embedDims}d vector index
              </Badge>
            ) : (
              <Badge variant="outline" className="border-chart-3/40 font-mono text-[11px] font-normal text-chart-3">
                keyword only
              </Badge>
            )}
          </div>
          <DialogDescription className="text-xs text-muted-foreground pt-1">
            Document inspection · Chunks, layout hierarchy, and embedding representation
          </DialogDescription>
        </DialogHeader>

        {/* Stats Strip */}
        <div className="grid grid-cols-2 gap-2 border-b border-border/60 bg-background/50 px-6 py-3 sm:grid-cols-5 sm:gap-4 shrink-0">
          <StatTile label="Total Chunks" value={String(chunks.length || doc.chunk_count)} />
          <StatTile label="Total Tokens" value={totalTokens ? totalTokens.toLocaleString() : "—"} />
          <StatTile label="Avg Chunk Tokens" value={avgTokens ? String(avgTokens) : "—"} />
          <StatTile label="Table Chunks" value={String(tableChunkCount)} />
          <StatTile label="Avg Vector Norm" value={avgNorm ?? (embedDims ? "1.000" : "None")} />
        </div>

        {/* Filter Bar */}
        <div className="flex flex-wrap items-center gap-3 border-b border-border/60 px-6 py-2.5 shrink-0">
          <div className="relative min-w-[220px] grow">
            <Search className="absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
            <Input
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setSelectedIdx(0);
              }}
              placeholder="Search chunks by keywords or section..."
              className="h-8 pl-8 text-xs"
            />
          </div>

          <Button
            variant={tableOnly ? "default" : "outline"}
            size="sm"
            onClick={() => {
              setTableOnly(!tableOnly);
              setSelectedIdx(0);
            }}
            className="h-8 gap-1.5 text-xs font-normal"
          >
            <TableProperties className="size-3.5" />
            <span>Tables only {tableChunkCount > 0 ? `(${tableChunkCount})` : ""}</span>
          </Button>

          <span className="font-mono text-xs text-muted-foreground">
            {filteredChunks.length} of {chunks.length} chunks
          </span>
        </div>

        {/* Content Area */}
        <div className="min-h-0 grow overflow-hidden">
          {loading ? (
            <div className="flex h-96 flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
              <span className="thinking-dot size-3 rounded-full bg-primary" />
              <p>Loading document chunks and vector embeddings…</p>
            </div>
          ) : error ? (
            <div className="p-8 text-center">
              <p className="text-sm font-medium text-destructive">{error}</p>
              <Button variant="outline" size="sm" onClick={onClose} className="mt-4">
                Close
              </Button>
            </div>
          ) : chunks.length === 0 ? (
            <div className="p-12 text-center text-sm text-muted-foreground">
              No chunk or embedding records found for this document.
            </div>
          ) : (
            <div className="grid h-full min-h-0 grid-cols-1 divide-y divide-border/60 lg:grid-cols-[300px_minmax(0,1fr)] lg:divide-x lg:divide-y-0 overflow-hidden">
              {/* Chunk Sidebar */}
              <div className="overflow-y-auto overflow-x-hidden p-2 custom-scrollbar h-full">
                {filteredChunks.map((c, i) => {
                  const active = activeChunk?.id === c.id;
                  return (
                    <button
                      key={c.id}
                      onClick={() => setSelectedIdx(i)}
                      className={`group mb-1.5 flex w-full flex-col gap-1 rounded-lg border p-2.5 text-left transition-all last:mb-0 ${
                        active
                          ? "border-primary/40 bg-primary/10 shadow-sm"
                          : "border-transparent hover:border-border/60 hover:bg-accent/40"
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
                        <span className="truncate text-xs font-medium text-foreground">
                          {c.section_path.split(" > ").pop() || "Root section"}
                        </span>
                        <span className="grow" />
                        {c.contains_table && (
                          <span
                            className="size-2 shrink-0 rounded-full bg-chart-3"
                            title="Contains table"
                          />
                        )}
                        <span className="tabular shrink-0 font-mono text-[10px] text-muted-foreground">
                          {c.token_count} tok
                        </span>
                      </div>

                      {/* Relative token distribution bar */}
                      <div className="h-1 w-full overflow-hidden rounded-full bg-secondary/80">
                        <div
                          className={`h-full rounded-full transition-all ${
                            active ? "bg-primary" : "bg-muted-foreground/30"
                          }`}
                          style={{ width: `${Math.max(4, (c.token_count / maxTokens) * 100)}%` }}
                        />
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* Chunk Details & Vector Inspector */}
              <div className="overflow-y-auto overflow-x-hidden p-6 pb-20 custom-scrollbar h-full">
                {activeChunk ? (
                  <div className="space-y-5">
                    {/* Active Chunk Header */}
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-4">
                      <div className="space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline" className="font-mono text-xs text-primary border-primary/30 bg-primary/5">
                            Chunk #{activeChunk.chunk_index}
                          </Badge>
                          <span className="font-mono text-xs text-muted-foreground">
                            {activeChunk.id}
                          </span>
                        </div>
                        {activeChunk.section_path && (
                          <p className="text-xs text-muted-foreground">
                            {activeChunk.section_path.split(" > ").map((seg, i, arr) => (
                              <span key={i}>
                                <span className={i === arr.length - 1 ? "text-foreground font-medium" : ""}>
                                  {seg}
                                </span>
                                {i < arr.length - 1 && <span className="px-1 text-muted-foreground/60">›</span>}
                              </span>
                            ))}
                          </p>
                        )}
                      </div>

                      <div className="flex flex-wrap items-center gap-2">
                        {activeChunk.contains_table && (
                          <Badge variant="secondary" className="border-chart-3/30 text-chart-3 bg-chart-3/10 font-normal text-[11px]">
                            <TableProperties className="mr-1 size-3 inline" />
                            Table structure
                          </Badge>
                        )}
                        <Badge variant="secondary" className="font-mono text-[11px] font-normal">
                          {activeChunk.token_count} tokens
                        </Badge>
                        <Badge variant="secondary" className="font-mono text-[11px] font-normal">
                          {activeChunk.page_start === activeChunk.page_end
                            ? `Page ${activeChunk.page_start}`
                            : `Pages ${activeChunk.page_start}–${activeChunk.page_end}`}
                        </Badge>
                      </div>
                    </div>

                    {/* Prepended context header */}
                    {activeChunk.context_header && (
                      <div className="rounded-lg border border-primary/25 bg-primary/5 p-3">
                        <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                          Prepended Context Header
                        </p>
                        <p className="mt-1 font-mono text-xs text-primary">
                          {activeChunk.context_header}
                        </p>
                      </div>
                    )}

                    {/* Chunk Body Text */}
                    <div className="space-y-2">
                      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                        Extracted Chunk Content
                      </p>
                      <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap rounded-lg border border-border/60 bg-secondary/30 p-4 font-mono text-xs leading-relaxed text-foreground/90 custom-scrollbar">
                        {activeChunk.body}
                      </pre>
                    </div>

                    {/* Vector Embedding Representation */}
                    {activeChunk.embedding ? (
                      <div className="space-y-3 rounded-lg border border-border/70 bg-muted/15 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div className="flex items-center gap-2">
                            <Sparkles className="size-4 text-primary" />
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-foreground">
                              Vector Embedding Profile
                            </h4>
                          </div>
                          <div className="flex items-center gap-3">
                            <span className="font-mono text-[11px] text-muted-foreground">
                              Norm: <strong className="text-foreground">{activeChunk.embedding.norm.toFixed(4)}</strong>
                            </span>
                            <span className="font-mono text-[11px] text-muted-foreground">
                              Dims: <strong className="text-primary">{activeChunk.embedding.dims}</strong>
                            </span>
                          </div>
                        </div>

                        {/* Diverging Sparkline Visualizer */}
                        <div className="space-y-1.5 rounded-md border border-border/60 bg-background/50 p-3">
                          <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground">
                            <span>Component magnitude (first {activeChunk.embedding.preview.length} dimensions)</span>
                            <span className="text-primary">Emerald = pos · Rose = neg</span>
                          </div>
                          <Sparkline values={activeChunk.embedding.preview} />
                        </div>

                        {/* Raw vector toggle button */}
                        <div className="flex items-center justify-between pt-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setShowRawVector(!showRawVector)}
                            className="h-7 gap-1 px-2 text-xs text-muted-foreground hover:text-foreground"
                          >
                            <span>{showRawVector ? "Hide" : "View"} raw vector components</span>
                          </Button>
                        </div>

                        {/* Raw float vector snippet */}
                        {showRawVector && (
                          <div className="space-y-1.5 pt-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[11px] text-muted-foreground">
                                Float array ({activeChunk.embedding.preview.length} sample values):
                              </span>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={copyVectorValues}
                                className="h-6 gap-1 px-2 text-[10px]"
                              >
                                {copied ? (
                                  <>
                                    <Check className="size-3 text-primary" />
                                    <span>Copied</span>
                                  </>
                                ) : (
                                  <>
                                    <Copy className="size-3" />
                                    <span>Copy preview</span>
                                  </>
                                )}
                              </Button>
                            </div>
                            <pre className="max-h-28 overflow-y-auto rounded-md border border-border/60 bg-black/60 p-2.5 font-mono text-[10px] text-muted-foreground custom-scrollbar">
                              [{activeChunk.embedding.preview.join(", ")} … {activeChunk.embedding.dims - activeChunk.embedding.preview.length} more dimensions]
                            </pre>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="rounded-lg border border-border/50 bg-secondary/20 p-4 text-xs text-muted-foreground">
                        Vector embeddings not stored or this document was indexed in keyword-only mode.
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                    Select a chunk to inspect its text and embeddings
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border/60 bg-muted/10 px-6 py-3 text-xs text-muted-foreground">
          <span>Click on any chunk row to inspect content & vector features</span>
          <Button variant="secondary" size="sm" onClick={onClose} className="h-7 text-xs">
            Done
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-0.5">
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="tabular font-mono text-sm font-bold text-foreground">{value}</p>
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  const max = Math.max(...values.map(Math.abs), 1e-6);
  return (
    <div className="flex h-12 w-full items-center rounded-md border border-border/50 bg-black/40 p-2">
      <div className="flex h-full w-full items-center gap-0.5">
        {values.map((v, i) => {
          const h = Math.max(3, (Math.abs(v) / max) * 18);
          return (
            <div
              key={i}
              className="flex h-full flex-1 flex-col justify-center"
              title={`dim[${i}]: ${v.toFixed(4)}`}
            >
              <div
                className={`w-full rounded-[1px] transition-all hover:scale-y-125 ${
                  v >= 0 ? "bg-primary/80" : "bg-chart-2/80"
                }`}
                style={{
                  height: `${h}px`,
                  marginTop: v >= 0 ? `${18 - h}px` : 0,
                  marginBottom: v < 0 ? `${18 - h}px` : 0,
                }}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
