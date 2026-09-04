# Architecture

A file-by-file guide to the backend. For setup and commands see the
[README](README.md); for the design rationale see the
[build plan](Project1_Azure_RAG_Build_Plan.pdf).

---

## What this is

A question-answering service over financial filings. You feed it SEC 10-Ks and
shareholder letters; someone asks *"How did gross margin change between FY22
and FY23?"* and gets an answer where **every factual claim is backed by a
citation that has been verified in code** — not merely claimed by the model.

There are exactly **two paths** through the system, and almost every file
belongs to one of them.

---

## Path 1 — Ingestion (batch, offline)

A PDF becomes searchable chunks.

```
PDF in Blob ─► queue message ─► Document Intelligence ─► blocks
     ─► merge page-split tables ─► chunk ─► embed ─► Azure AI Search
```

| Step | File | What happens |
|---|---|---|
| Job entry | `apps/ingest/main.py` | Drains the queue, or walks a local folder. A queue message is deleted only **after** indexing succeeds, so a crash redelivers the document instead of losing it. Also carries `--create-index`. |
| Orchestration | `apps/ingest/pipeline.py` | Translates Document Intelligence's JSON into `Block` objects, infers company / fiscal year / doc type from the cover page, then parse → chunk → embed → upload. **Caches the parse result to disk** — parsing is the slow, billed, non-deterministic step, so a chunker change re-embeds without re-parsing anything. |
| Table repair | `libs/rag_core/tables.py` | A table spanning a page break arrives as *two* tables. This stitches them back together, but only on strong evidence (repeated header row, or a headerless continuation with matching column count) — a wrong merge corrupts a financial statement, so the bar is deliberately high. |
| Chunking | `libs/rag_core/chunking.py` | The highest-leverage file in the repo. Splits on section headings rather than character counts, **never through a table**, overlaps prose at paragraph boundaries, and prepends a context header (`[Microsoft · 10-K · FY2023 · Item 7]`) so a chunk reading "revenue increased 12%" still has a referent. Caps chunk size below the semantic ranker's ~2,000-token read window, because above that the ranker silently scores a truncated chunk. |
| Index shape | `libs/rag_core/indexing.py` | The search index defined as code: fields, HNSW vector profile (`m=8`, cosine), semantic configuration. The vector field is marked **not retrievable** — the raw floats are never needed back and they bloat every response. |

## Path 2 — Answering a question (live)

```
question ─► extract filters ─► hybrid search ─► semantic rerank
        ─► generate ─► VERIFY CITATIONS ─► stream to browser
```

| Step | File | What happens |
|---|---|---|
| Orchestration | `libs/rag_core/pipeline.py` | The five stages, each timed separately. Collaborators are injected as protocols, which is why the test suite can drive the real pipeline with fakes. |
| Filters + search | `libs/rag_core/retrieval.py` | Extracts ticker / fiscal year / quarter from the question and renders an OData filter — filtering *before* search beats hoping the ranker sorts it out. Builds **one** request carrying both a text query and a vector query; Azure AI Search performs the RRF fusion server-side. Also implements RRF locally, for the ablation arms. |
| Prompt | `libs/rag_core/generation.py` | The citation-constrained system prompt and the provider-neutral JSON schema for `{answer, citations, refused}`. Retrieved text goes in the **user** message, never the system message — that is the indirect prompt-injection boundary for third-party PDFs. |
| **Verification** | `libs/rag_core/citations.py` | The heart of the project. For each citation: was that `chunk_id` actually in the context we sent, and does the quoted span really occur in it? Failures are dropped from the rendered answer and counted. Folds whitespace, smart quotes and thousands separators, but rejects a quote that *skips* source text. Microseconds, no model call. |
| HTTP | `apps/api/main.py` | The endpoints. `/api/chat` streams typed SSE events (`token`, `citations`, `validation`, `trace`) because the UI renders each differently. `/api/search` returns per-retriever ranks for diagnosing a bad answer. |
| Wiring | `apps/api/deps.py` | Pipeline and store singletons, with a `configure()` seam the tests use to inject fakes. |

---

## Supporting modules

| File | Role |
|---|---|
| `libs/rag_core/schemas.py` | Every data contract in one place — `Chunk`, `Citation`, `Trace`, `RetrievalConfig`, `EvalRun`. Also holds the aggregation that produces *"overall faithfulness 0.93, but table-dependent questions 0.79."* |
| `libs/rag_core/config.py` | Settings, plus the named retrieval configs (`vector_only`, `bm25_only`, `hybrid_rrf`, `hybrid_semantic`) the ablation compares. |
| `libs/rag_core/clients.py` | All external service adapters — Gemini, Azure OpenAI, AI Search, Document Intelligence — plus retry-with-backoff, the provider factory, and index creation. Every SDK import is **deferred inside a method**, which is why the tests run with no SDKs and no credentials. |
| `libs/rag_core/store.py` | Traces and evaluation results in SQLite locally, PostgreSQL in Azure. Metrics are stored **as rows**, so adding a metric needs no migration and no UI change. |

## Evaluation

| File | Role |
|---|---|
| `libs/rag_core/evaluation/custom.py` | Seven free, deterministic metrics: citation validity, citation precision/recall, context hit rate, MRR, refusal accuracy, numeric exactness, fiscal-period correctness. |
| `libs/rag_core/numerics.py` | Parses `$211.9 billion`, `(1,234)`, `140 bps`; normalises scale; compares within tolerance. Catches the **1000× scale error** that scores nearly identically on embedding similarity — the failure mode no generic RAG metric measures. |
| `libs/rag_core/evaluation/ragas_runner.py` | The LLM-judge suite (faithfulness, context recall, noise sensitivity, …) plus a content-addressed **verdict cache**, so re-running after an unrelated change is close to free. |
| `libs/rag_core/evaluation/gate.py` | The CI gate: absolute floors plus maximum regression against the stored baseline. This is what fails a build when quality drops. |
| `apps/evaluator/cli.py` | `run` / `gate` / `compare` / `seed`. The same code path runs locally, nightly and in CI — a gate running different code measures a different system. |

## Tests and data

The ten test files mirror the modules: `test_chunking.py`, `test_tables.py`,
`test_citations.py`, `test_numerics.py`, `test_retrieval.py`,
`test_evaluation.py`, `test_ingest.py`, `test_providers.py`, and
`test_api.py`, which drives the entire HTTP path with fakes.

`evals/golden_set.yaml` holds the Q&A pairs, `evals/thresholds.yaml` the gate
limits, `evals/configs/sweeps.yaml` the extra ablation arms.
`infra/main.bicep` provisions Azure; `infra/sql/schema.sql` is the PostgreSQL
mirror of `store.py`.

---

## The one structural rule

**`libs/rag_core` imports no SDK at module level.**

That is not stylistic. It is why 109 tests run in under a second with no Azure
account, no API key and no network. The algorithms — chunking, table merging,
citation checking, number parsing — are pure functions. Anything that touches a
network lives behind a protocol in `clients.py`, and the apps inject the real
implementation at startup.

**If you read four files, read these:** `chunking.py` (the decision that drives
retrieval quality), `citations.py` (the differentiator), `pipeline.py` (how it
all connects), `evaluation/custom.py` (why the metrics are domain-specific).

---

## Why this is not a "normal" RAG app

Most RAG tutorials are: split text every 500 characters, embed, cosine search,
stuff the top 5 into a prompt. Five things here are deliberately different, and
four of them are consequences of the document type rather than the cloud.

**1. Retrieval is hybrid, in one request.** Embeddings are unreliable on exact
tokens — tickers, fiscal periods, defined terms. A query for "AAPL Q3 2024
gross margin" is semantically near-identical to Q2 2023 Microsoft margins, and
a vector-only retriever will happily return the wrong issuer. BM25 catches the
literal tokens, vectors catch the paraphrase, and Azure AI Search fuses them
with Reciprocal Rank Fusion **server-side** — a single call, not two searches
merged in application code. A Microsoft-hosted cross-encoder then re-scores the
survivors using the full query-document pair.

**2. Chunking follows the document, not a character count.** Financial filings
are mostly tables. Fixed-size chunking flattens a balance sheet into
unreadable soup and splits answers across boundaries. Here the layout model
gives real section headings and structured table cells, tables are atomic, and
every chunk carries its own context header.

**3. Citations are verified, not trusted.** The usual pattern asks the model to
write `[1]` and hopes. This requests structured output with a `chunk_id` and a
verbatim `quoted_span`, then checks both against the context actually sent.
That is programmatic hallucination detection, and it is cheap enough to run on
every request and to gate a build on.

**4. Metadata filtering happens before search.** Company, fiscal year and doc
type are extracted from the question and pushed into an OData filter, so the
candidate set is already scoped before ranking begins.

**5. Evaluation is a product surface.** A golden set with four deliberate
question types (including *unanswerable*), deterministic domain metrics, the
RAGAS judge suite, an ablation matrix across retrieval configs, and a CI gate
that fails the build on regression.

### What Azure specifically buys

The point of Azure here is not "the cloud" — it is that four things that would
otherwise be separate services and separate failure modes come as one:

| Capability | Why it matters |
|---|---|
| **AI Search** | BM25, HNSW vectors, RRF fusion and a hosted semantic reranker in a **single index and a single query**. With pgvector or a bare vector DB you get vectors, then hand-build fusion and reranking yourself. |
| **Document Intelligence** | `prebuilt-layout` returns tables as structured cells with row/column indices and spans, section headings with hierarchy, and page bounding regions. That last one is what makes a citation resolve to a page and a highlight box rather than a filename. |
| **Managed identity + RBAC** | No Azure key exists in code, config or an image layer. The app authenticates as itself. (Gemini is the one exception — its API key lives in Key Vault and is fetched at runtime with that same identity.) |
| **Container Apps + Bicep + DevOps** | Ingestion and evaluation are scale-to-zero jobs rather than endpoints, the whole environment is one reviewable template, and the quality gate runs in the same pipeline as the tests. |

The models are deliberately **not** part of that lock-in: `ChatModel` and
`Embedder` are protocols, and `LLM_PROVIDER` switches between Gemini and Azure
OpenAI without touching the pipeline.
