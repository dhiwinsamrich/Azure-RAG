"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Eye, Loader2, Trash2 } from "lucide-react";
import { ChunkExplorer, ChunkExplorerSkeleton } from "@/components/ChunkExplorer";
import { DocumentEmbeddingModal } from "@/components/DocumentEmbeddingModal";
import { RelevanceVerdict } from "@/components/RelevanceVerdict";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { IndexedDocument, IngestResult, Relevance } from "@/lib/types";

type Mode = "preview" | "upload";

export default function CorpusPage() {
  const [result, setResult] = useState<IngestResult | null>(null);
  const [docs, setDocs] = useState<IndexedDocument[]>([]);
  const [busy, setBusy] = useState<Mode | null>(null);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [rejected, setRejected] = useState<Relevance | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [inspectDoc, setInspectDoc] = useState<IndexedDocument | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function loadDocs() {
    try {
      const res = await fetch("/api/corpus");
      if (res.ok) setDocs((await res.json()) as IndexedDocument[]);
    } catch {
      /* the list is a convenience; a failure here should not block ingesting */
    }
  }

  useEffect(() => {
    loadDocs();
  }, []);

  async function run(mode: Mode, force = false) {
    if (!file) return;
    setBusy(mode);
    setError("");
    setRejected(null);
    setResult(null);

    const body = new FormData();
    body.append("file", file);
    body.append("mode", mode);
    if (force) body.append("force", "true");

    try {
      const res = await fetch("/api/corpus", { method: "POST", body });
      const data = (await res.json()) as IngestResult;
      if (!res.ok) {
        // 422 carries the gate's verdict; anything else is a plain failure.
        const detail = data.detail;
        if (detail && typeof detail === "object" && "relevance" in detail) {
          setRejected(detail.relevance);
        } else {
          setError(
            typeof detail === "string" ? detail : `request failed (${res.status})`,
          );
        }
      } else {
        setResult(data);
        if (mode === "upload") loadDocs();
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function remove(docId: string) {
    setDeleting(docId);
    try {
      await fetch(`/api/corpus/${encodeURIComponent(docId)}`, { method: "DELETE" });
      await loadDocs();
      if (result?.doc_id === docId) setResult(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDeleting(null);
    }
  }

  const tableChunks = result?.chunks.filter((c) => c.contains_table).length ?? 0;
  const tokens = result?.chunks.reduce((a, c) => a + c.token_count, 0) ?? 0;

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Corpus</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Upload a document to see exactly how it is parsed, chunked and
          embedded. <span className="text-foreground">Preview</span> parses and
          chunks only — free, instant, and the right loop for tuning chunking.{" "}
          <span className="text-foreground">Ingest</span> also embeds and writes
          to the search index.
        </p>
      </div>

      <Card
        className={`border-dashed transition-colors ${
          dragging ? "border-primary bg-primary/5" : "border-border/60"
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files?.[0];
          if (f) setFile(f);
        }}
      >
        <CardContent className="flex flex-wrap items-center gap-4 py-8">
          <input
            ref={input}
            type="file"
            accept=".md,.markdown,.txt,.pdf,.xlsx"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <div className="min-w-0 grow">
            <p className="text-sm font-medium">
              {file ? file.name : "Drop a document here, or choose a file"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {file
                ? `${(file.size / 1024).toFixed(1)} KB`
                : "Markdown and text locally · PDF and XLSX once Document Intelligence is configured"}
            </p>
          </div>
          <Button variant="outline" onClick={() => input.current?.click()}>
            Choose file
          </Button>
          <Button
            variant="secondary"
            disabled={!file || busy !== null}
            onClick={() => run("preview")}
          >
            {busy === "preview" ? "Chunking…" : "Preview chunking"}
          </Button>
          <Button disabled={!file || busy !== null} onClick={() => run("upload")}>
            {busy === "upload" ? "Embedding…" : "Ingest & index"}
          </Button>
        </CardContent>
      </Card>

      {error && (
        <Card className="border-destructive/40 bg-destructive/10">
          <CardContent className="pt-6 text-sm text-destructive">{error}</CardContent>
        </Card>
      )}

      {rejected && (
        <div className="space-y-3">
          <RelevanceVerdict relevance={rejected} />
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs text-muted-foreground">
              This corpus is meant to hold financial filings. An unrelated
              document competes for every query, and a large one crowds the
              filings out entirely.
            </p>
            <Button
              variant="outline"
              size="sm"
              disabled={busy !== null}
              onClick={() => run("upload", true)}
              className="border-destructive/40 text-destructive hover:bg-destructive/10"
            >
              Index anyway
            </Button>
          </div>
        </div>
      )}

      {busy && <ProcessingSkeleton mode={busy} />}

      {result && !busy && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-semibold">{result.doc_id}</h2>
            {result.indexed ? (
              <Badge className="border-primary/40 bg-primary/15 text-primary" variant="outline">
                indexed · {result.indexed_count} chunks
              </Badge>
            ) : (
              <Badge variant="outline" className="border-chart-3/40 text-chart-3">
                preview only · not indexed
              </Badge>
            )}
            {result.from_cache && (
              <Badge variant="secondary" className="font-mono text-[11px] font-normal">
                parse served from cache
              </Badge>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
            <Stat label="Pages" value={String(result.pages)} />
            <Stat label="Chunks" value={String(result.chunks.length)} />
            <Stat label="Table chunks" value={String(tableChunks)} />
            <Stat label="Total tokens" value={String(tokens)} />
            <Stat
              label="Avg tokens"
              value={
                result.chunks.length
                  ? String(Math.round(tokens / result.chunks.length))
                  : "—"
              }
            />
            <Stat
              label="Embedding"
              value={result.embed_dims ? `${result.embed_dims}d` : "none"}
            />
          </div>

          {result.relevance && (
            <RelevanceVerdict relevance={result.relevance} forced={result.forced} />
          )}

          {result.chunk_settings && (
            <p className="font-mono text-[11px] text-muted-foreground">
              chunker · target {result.chunk_settings.target_tokens} tok · overlap{" "}
              {result.chunk_settings.overlap_tokens} · hard cap{" "}
              {result.chunk_settings.max_tokens} (the semantic ranker reads
              roughly this much)
            </p>
          )}

          {!result.indexed && (
            <p className="rounded-md border border-chart-3/25 bg-chart-3/5 px-3 py-2 text-xs text-muted-foreground">
              Preview mode: no embedding model was called and nothing was
              written to the index. Use <span className="text-foreground">Ingest &amp; index</span> once the chunking looks right.
            </p>
          )}

          <ChunkExplorer chunks={result.chunks} />
        </div>
      )}

      <Card className="border-border/60">
        <CardHeader>
          <CardTitle className="text-sm font-medium">Indexed documents</CardTitle>
        </CardHeader>
        <CardContent>
          {docs.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nothing indexed yet. Upload a document above, or ingest a folder
              with <code className="font-mono text-xs">apps.ingest.main --local</code>.
            </p>
          ) : (
            <ul className="divide-y divide-border/60">
              {docs.map((d) => (
                <li
                  key={d.doc_id}
                  className="flex flex-wrap items-center gap-3 py-2.5 transition-colors hover:bg-muted/10 rounded-md px-1"
                >
                  <span className="min-w-0 truncate font-mono text-xs font-medium text-foreground">
                    {d.doc_id}
                  </span>
                  {/* An unknown type is absent information, not a label. */}
                  {d.doc_type && d.doc_type !== "unknown" && (
                    <Badge variant="secondary" className="text-[11px] font-normal">
                      {d.doc_type}
                    </Badge>
                  )}
                  {d.fiscal_year && (
                    <Badge variant="secondary" className="text-[11px] font-normal">
                      FY{d.fiscal_year}
                    </Badge>
                  )}
                  {!d.has_vectors && (
                    <Badge
                      variant="outline"
                      className="border-chart-3/40 text-[11px] font-normal text-chart-3"
                    >
                      keyword only
                    </Badge>
                  )}
                  <span className="ml-auto shrink-0 font-mono text-[11px] text-muted-foreground">
                    {d.chunk_count} {d.chunk_count === 1 ? "chunk" : "chunks"}
                    {/* page_count comes from the store, so it is absent for
                        anything ingested through the CLI. */}
                    {d.page_count
                      ? ` · ${d.page_count} ${d.page_count === 1 ? "page" : "pages"}`
                      : ""}
                  </span>

                  <div className="flex items-center gap-1">
                    {/* View Chunks & Embeddings Icon Button */}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setInspectDoc(d)}
                      className="h-8 w-8 p-0 text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                      title="Inspect chunks & vector embeddings"
                    >
                      <Eye className="size-4" />
                      <span className="sr-only">Inspect document embeddings</span>
                    </Button>

                    {/* Delete Icon Button with Confirmation State */}
                    {confirmDeleteId === d.doc_id ? (
                      <div className="flex items-center gap-1 animate-in fade-in zoom-in-95 duration-150">
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={deleting !== null}
                          onClick={() => {
                            setConfirmDeleteId(null);
                            remove(d.doc_id);
                          }}
                          className="h-7 px-2 text-[11px]"
                          title="Confirm deletion"
                        >
                          {deleting === d.doc_id ? (
                            <Loader2 className="size-3.5 animate-spin" />
                          ) : (
                            "Confirm"
                          )}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={deleting !== null}
                          onClick={() => setConfirmDeleteId(null)}
                          className="h-7 px-2 text-[11px] text-muted-foreground hover:bg-accent"
                        >
                          Cancel
                        </Button>
                      </div>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={deleting !== null}
                        onClick={() => setConfirmDeleteId(d.doc_id)}
                        className="h-8 w-8 p-0 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                        title="Delete this document, its chunks and their embeddings"
                      >
                        {deleting === d.doc_id ? (
                          <Loader2 className="size-4 animate-spin text-destructive" />
                        ) : (
                          <Trash2 className="size-4" />
                        )}
                        <span className="sr-only">Delete document</span>
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Document Chunks & Vector Embedding Modal */}
      <DocumentEmbeddingModal
        doc={inspectDoc}
        isOpen={inspectDoc !== null}
        onClose={() => setInspectDoc(null)}
      />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="border-border/60">
      <CardContent className="space-y-1 pt-5">
        <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          {label}
        </p>
        <p className="tabular text-xl font-bold">{value}</p>
      </CardContent>
    </Card>
  );
}

function ProcessingSkeleton({ mode }: { mode: Mode }) {
  const stages =
    mode === "upload"
      ? ["parsing", "chunking", "embedding", "indexing"]
      : ["parsing", "chunking"];
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="flex gap-1">
          <span className="thinking-dot size-1.5 rounded-full bg-primary" />
          <span className="thinking-dot size-1.5 rounded-full bg-primary" />
          <span className="thinking-dot size-1.5 rounded-full bg-primary" />
        </span>
        <span className="font-mono uppercase tracking-wider">{stages.join(" · ")}</span>
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i} className="border-border/60">
            <CardContent className="space-y-2 pt-5">
              <Skeleton className="h-2.5 w-16" />
              <Skeleton className="h-6 w-12" />
            </CardContent>
          </Card>
        ))}
      </div>
      <ChunkExplorerSkeleton />
    </div>
  );
}
