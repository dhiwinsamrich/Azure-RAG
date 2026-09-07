# Financial Document Intelligence & RAG on Azure

Hybrid retrieval over SEC filings with **programmatically validated citations**
and evaluation treated as a product surface rather than a notebook.

Generation, embeddings and the eval judge run on **Gemini**; retrieval, parsing
and storage run on **Azure**. The provider is one setting (`LLM_PROVIDER`) -
Azure OpenAI is the alternate.

Docs: [architecture](ARCHITECTURE.md) (file-by-file) ·
[Azure setup](docs/AZURE_SETUP.md) ·
[build guide](Project1_Azure_RAG_Build_Guide.md) ·
[build plan](Project1_Azure_RAG_Build_Plan.pdf)

---

## Status

| Area | State |
|---|---|
| Core library (`backend/libs/rag_core`) | Implemented, 195 tests passing |
| API (`backend/apps/api`) | Implemented; verified end to end against a **live** Azure deployment |
| Ingestion job (`backend/apps/ingest`) | Implemented; upload also available through the web UI |
| Evaluator + CLI (`backend/apps/evaluator`) | Implemented; RAGAS path exercised against real Azure + Gemini |
| Web app (`frontend/`) | Ask, Corpus (upload/inspect/delete) and Quality screens - all live |
| Infrastructure (`backend/infra`) | Bicep, plus a Docker Compose path for a single-machine deploy |
| CI/CD (`.azure-pipelines`) | Written, not yet run |
| Gemini adapters | Verified against the live API - generation, embeddings and the eval judge |

A reference environment (real Azure AI Search with hybrid + semantic ranking,
real Document Intelligence, real Gemini) has been deployed and produces
verified, cited answers end to end. Resource names are intentionally left out
of this README; see [Deploying](#deploying) to stand up your own.

---

## Five ideas worth reading the code for

**1. Citations are verified, not trusted.**
The model returns `{answer, citations:[{chunk_id, quoted_span}]}` as structured
output. [`citations.py`](backend/libs/rag_core/citations.py) then asserts every
`chunk_id` was in the context we actually sent, and that the quoted span occurs
verbatim in that chunk. Failures are dropped from the rendered answer and
counted. It runs in microseconds, needs no model call, and is the difference
between trusting a model and checking it.

**2. Retrieval configs are data, and every result references one.**
A `RetrievalConfig` row names the chunker, `top_k`, which retrievers are on,
the embedding dimensions and the prompt version. Traces and eval results carry
its id, so *"did hybrid beat vector-only?"* is a `GROUP BY`, and a new ablation
arm is a [YAML file](backend/evals/configs/sweeps.yaml), never a code change.

**3. The model provider is a seam, not a rewrite.**
`ChatModel` and `Embedder` are protocols. `GeminiChat` / `GeminiEmbedder` and
`AzureOpenAIChat` / `AzureOpenAIEmbedder` implement them, `build_chat()` picks
one from settings, and the citation JSON schema is defined once, neutrally, in
`generation.answer_schema()` - each adapter wraps it in its own envelope. The
tests drive the whole pipeline through those same protocols with fakes.

**4. Metrics are rows, not columns.**
`eval_metric_value(result_id, metric_name, value, reason)`. Adding a RAGAS
metric needs no migration and no UI change. The dashboard pivots generically,
and `reason` stores the judge's justification so a low score can be explained.

**5. An unrelated document in the index is a retrieval bug, not clutter.**
[`relevance.py`](backend/libs/rag_core/relevance.py) screens every upload
against six categories of financial evidence (filing type, statements,
metrics, fiscal period, monetary amounts, regulatory language) before it is
embedded and indexed - a single off-topic 92-chunk upload was enough to
out-rank real filings on a plain query for "revenue". Scoping a question to
specific `doc_ids` (never inferred from the question text) is the second half
of the same fix - see [`ScopeSelector`](frontend/components/ScopeSelector.tsx).

---

## Layout

```
backend/
  libs/rag_core/       pure logic - no Azure SDK imports at module level
    chunking.py        layout-aware chunker (never splits a table)
    tables.py          cross-page table reconciliation
    citations.py       the programmatic hallucination check
    numerics.py        financial figure parsing and scale comparison
    relevance.py        the financial-document evidence gate
    retrieval.py         filter extraction, hybrid request, RRF
    generation.py         citation-constrained prompt + JSON schema
    pipeline.py            filter -> retrieve -> rank -> generate -> validate
    clients.py              Azure + Gemini adapters, key/managed-identity auth
    local_search.py          free-tier BM25 + cosine index (no Azure needed)
    local_parse.py            free-tier markdown/text parser (no Doc Intel needed)
    store.py                   trace + eval store (SQLite locally, Postgres in Azure)
    evaluation/                  custom metrics, RAGAS wiring, CI gate
  apps/api                   FastAPI: chat (SSE), corpus upload/inspect/delete, eval API
  apps/ingest                Container Apps Job: queue-driven, resumable
  apps/evaluator              eval CLI: run / gate / compare / seed
  tests/                       195 tests, no Azure account needed
  evals/                        golden set (+ a local variant), ablation configs, gate thresholds
  infra/                         Bicep + the PostgreSQL schema
  deploy/                         api and jobs Dockerfiles
  pyproject.toml

frontend/                        Next.js 15 + shadcn/ui: Ask, Corpus and Quality screens
  app/
    page.tsx                     Ask - streaming chat, citation markers, document scope selector
    corpus/                       upload, chunk explorer, embedding inspector, delete
    eval/                          quality dashboard: KPI tiles, radar, ablation, run drilldown
    api/                            route handlers proxying chat / corpus / eval / status to the API
  components/
    ScopeSelector, RelevanceVerdict, ChunkExplorer, DocumentEmbeddingModal,
    EvalCharts, QualityRadarChart, QuestionTypeBreakdownChart, RunDrilldownDrawer
    evilcharts/                   animated chart primitives (bar/line, tooltip, legend, brush)
    ui/                            shadcn primitives (button, card, dialog, table, tabs, ...)
  Dockerfile

.azure-pipelines/                 CI (with the eval gate) and nightly evaluation
docker-compose.yml                 single-command local stack (backend + frontend)
```

The core library imports no Azure SDK at module level, which is why the whole
test suite runs with no cloud account and no credentials.

---

## Running it free, with no Azure at all

There is a local mode that swaps two Azure services for on-disk equivalents, so
the app runs end to end with **no cloud resources and no API key**:

| Azure service | Local substitute | Trade-off |
|---|---|---|
| AI Search | `local_search.py` — Okapi BM25 + cosine + RRF over a JSON index | No semantic ranker (`hybrid_semantic` degrades to fused ranking), no scale |
| Document Intelligence | `local_parse.py` — markdown/text parser | No OCR, no bounding regions for citation highlighting |

```bash
cd backend
cat > .env <<'EOF'
SEARCH_BACKEND=local
PARSER_BACKEND=local
ENABLE_EMBEDDINGS=false
DEFAULT_CONFIG_ID=bm25_only
EOF

python -m apps.ingest.main --local ./corpus     # 2 sample filings, 10 chunks
uvicorn apps.api.main:app --port 8000

cd ../frontend && npm run dev                   # http://localhost:3000
```

That gives you working ingestion, filtering and BM25 retrieval with **no key at
all**. To get generated answers with citations, add your Gemini key and turn
vectors on:

```bash
# backend/.env
GEMINI_API_KEY=your-key
ENABLE_EMBEDDINGS=true
DEFAULT_CONFIG_ID=hybrid_rrf
```

Then re-run the ingest so chunks get embedded.

`backend/corpus/` holds two **synthetic** sample filings (Northwind Traders — a
fictional company, invented figures) purely so the app has something to
retrieve. Replace them with real filings when you move to Azure.

### Why not just use the Azure free tiers?

**AI Search Free works** — 50 MB, 3 indexes, vectors supported — but the
**semantic ranker is not offered below Basic**, so the reranking stage is
unavailable.

**Document Intelligence F0 does not work for filings.** It allows 500
pages/month, but processes only the **first two pages of any multi-page
document**, with a 4 MB file cap. On a 100-page 10-K you would index the cover
page and nothing else. That is why the local parser exists.

## Running locally

```bash
python -m venv .venv && .venv/Scripts/activate   # source .venv/bin/activate
pip install -e "./backend[api,dev]"
cd backend && pytest tests -q                     # 195 passing, no Azure needed
```

API and web (the API needs Azure endpoints configured to answer real queries):

```bash
cd backend
cp .env.example .env      # fill in your endpoints
uvicorn apps.api.main:app --reload --port 8000

cd ../frontend && npm install && npm run dev      # http://localhost:3000
```

Evaluation:

All Python commands below run from `backend/`.

```bash
python -m apps.evaluator.cli seed                      # load the golden set
python -m apps.evaluator.cli run --config hybrid_rrf   # deterministic metrics
python -m apps.evaluator.cli run --ragas               # + the LLM-judge suite
python -m apps.evaluator.cli gate --limit 20           # what CI runs
python -m apps.evaluator.cli compare --metric mrr      # ablation column
```

Ingestion:

```bash
python -m apps.ingest.main --create-index     # once, before the first ingest
python -m apps.ingest.main --local ./corpus   # a directory of PDFs
python -m apps.ingest.main --queue            # drain the storage queue
```

---

## Running with Docker Compose

The whole stack - API and web app, wired to each other - in one command.
`docker-compose.yml` defaults to local mode (`SEARCH_BACKEND=local`,
`PARSER_BACKEND=local`) so it runs with nothing configured:

```bash
docker compose up --build
# http://localhost:3000
```

Point it at real Azure by exporting the same variables `backend/.env.example`
documents before running it (`SEARCH_ENDPOINT`, `SEARCH_KEY` or managed
identity, `DOC_INTELLIGENCE_ENDPOINT`, `GEMINI_API_KEY`, ...) - the compose
file passes them straight through to the container. **CORS is currently wide
open** (`allow_origins=["*"]`) regardless of the compose file's unused
`CORS_ORIGINS` variable; tighten `apps/api/main.py` before exposing this
beyond localhost.

---

## Corpus management: upload, inspect, and the financial-document gate

The `/corpus` screen is where a document actually enters the system, and it
exists because early testing surfaced a real failure: a 92-chunk resume
upload out-ranked two real 10-Ks on the query "revenue," because nothing
stopped an unrelated document from competing for every question asked
afterwards.

**Preview vs. ingest.** Preview parses and chunks a file with no embedding
call and no index write - the loop for tuning chunking, since that setting
drives retrieval quality more than any other and shouldn't cost anything to
inspect. Ingest also embeds and writes to the index. The chunk explorer shows
the context header the chunker prepended, the token count, whether a table
was kept whole, and (once embedded) a sparkline of the first 48 vector
dimensions.

**The relevance gate.** Every upload is scored against six categories of
financial evidence before indexing (filing type, financial statements,
metrics, fiscal period, monetary amounts, regulatory language); documents
matching fewer than three are refused with the specific evidence they were
missing, and an explicit override is available for a false rejection. This is
a deterministic, free, zero-model-call classifier - the LLM-based classifier
and the accuracy/cost comparison against it are Phase 9, not yet built.

**Deletion actually deletes.** `DELETE /api/documents/{doc_id}` removes the
document's chunks - and their embeddings - from whichever index is active
(local or Azure), not only from the metadata store; leaving stale vectors
behind after a "delete" was a real bug caught while building this.

**Document ids are sanitized for Azure's key constraints.** Azure AI Search
document keys allow only letters, digits, `_`, `-` and `=`. A raw filename
like `Q3 2024 Report (Final).pdf` would otherwise produce a chunk key Azure
rejects outright; `sanitize_doc_id()` runs once, at the point a doc_id is
first derived from a filename, so every chunk id, cache path and search
filter built from it downstream stays consistent.

---

## Deploying

```bash
az deployment group create \
  -g rg-finrag-dev \
  -f backend/infra/main.bicep \
  -p environmentName=dev postgresAdminPassword=<secret>
```

Then apply [`backend/infra/sql/schema.sql`](backend/infra/sql/schema.sql), put the
Bicep outputs into `.env`, and create the search index with
`python -m apps.ingest.main --create-index`. The template emits **endpoints only** — no keys, by
design. Every Azure client authenticates with `DefaultAzureCredential`, which is
your `az login` locally and the user-assigned managed identity in Container Apps.

The Gemini API is the one key-based dependency. It stays out of config and
image layers: `main.bicep` writes it to Key Vault, and `resolve_gemini_api_key`
fetches it at runtime with the same managed identity. Locally it comes from
`.env` instead. Pass it at deploy time with `-p geminiApiKey=<key>`.

A reference environment built from this template is live and has served real,
cited answers end to end - so `what-if` first, but the path is proven.

**RBAC is the default, a key is the on-ramp.** `search_credential()` and
`docintel_credential()` fall back to an `AzureKeyCredential` when
`SEARCH_KEY` / `DOC_INTELLIGENCE_KEY` are set, and use
`DefaultAzureCredential` (managed identity / `az login`) otherwise. The key
path exists so a personal setup does not need full RBAC role assignments on
day one; leave those settings empty in anything beyond a portfolio deploy.

---

## Models

| Role | Model | Why |
|---|---|---|
| Generation | `gemini-3.8-flash` | Fast, cheap, structured-output capable |
| Eval judge | `gemini-2.5-pro` | Stronger **and stable** - see below |
| Embeddings | `gemini-embedding-001` | Returns one vector **per input string** |

Three things worth knowing before changing any of these:

**The judge must not be the generator.** A model grading its own output
inflates faithfulness. It is also deliberately a *stable* model, not a preview
one: a preview model's drift shows up on the dashboard as a quality change that
never actually happened.

**`gemini-embedding-2` cannot be used here.** It returns a *single aggregated
embedding* for a list of inputs, so passing it a batch of chunks would index
one vector for the whole batch and silently corrupt retrieval.
`gemini-embedding-001` returns one embedding per string. `GeminiEmbedder`
rejects the aggregating model at construction and asserts the returned count
matches the batch size.

**Embedding dimensions are fixed at index creation.** Gemini supports 768 /
1536 / 3072 (MRL truncation); the default here is 1536. Changing `EMBED_DIMS`
means creating a **new** search index and re-embedding the corpus - it is not a
config-only change. The parsed cache makes that re-embed cheap, since nothing
needs re-parsing.

## Evaluation

Three producers, one metric store, so *"did last night's change help?"* and
*"is production still healthy?"* are the same query.

| Path | Metrics | Cost |
|---|---|---|
| CI gate (20 questions) | deterministic only | cents, < 2 min |
| Nightly (full set × 4 configs) | + RAGAS LLM judges | the real budget |
| Online (5% sample) | NLI faithfulness + free checks | negligible |

**Deterministic metrics** (free, in [`evaluation/custom.py`](backend/libs/rag_core/evaluation/custom.py)):
`citation_validity`, `citation_precision/recall`, `context_hit_rate`, `mrr`,
`refusal_correct`, `numeric_exactness`, `fiscal_period_correctness`.

The last two are the domain-specific ones. `numeric_exactness` parses figures,
normalises scale and unit, and compares within tolerance — catching the
`$211.9 billion` vs `$211.9 million` error that scores nearly identically on
embedding similarity. `refusal_correct` is scored in **both** directions and
reported alongside the false-refusal rate, because a system that refuses
everything scores 1.0 on the unanswerable subset and is useless.

**LLM-judge metrics** via RAGAS ([`ragas_runner.py`](backend/libs/rag_core/evaluation/ragas_runner.py)):
faithfulness, answer relevancy, context precision/recall, context entity
recall, noise sensitivity, factual correctness, semantic similarity.

Gemini's free tier takes real pressure off the nightly judge budget, which was
the largest variable cost in the original design.

Two cost controls: the judge is a **separate, stronger model** from the
generator (self-grading inflates faithfulness, and eval must not compete with
serving traffic for quota), and verdicts are cached on
`hash(question, answer, contexts, metric, judge_model)` so a re-run after an
unrelated change is close to free.

The gate is deliberately boring to run and hard to bypass: floors plus a
maximum regression against the stored baseline, in
[`backend/evals/thresholds.yaml`](backend/evals/thresholds.yaml).

[`evals/golden_set_local.yaml`](backend/evals/golden_set_local.yaml) is a
second golden set scoped to the two synthetic sample filings in
`backend/corpus/` - the default `golden_set.yaml` targets a real corpus and
scores zero against the sample data, so use the `_local` variant
(`--golden-set evals/golden_set_local.yaml`) when demoing without real
filings loaded.

---

## What is deliberately not built yet

Phase 9 of the plan: document classification, structured financial extraction
with accounting-identity checks, and manager-letter tone scoring. The
`extraction` table and `DocType` enum are in place for them.

Also outstanding: the pdf.js citation viewer with bounding-box overlay (a
citation currently resolves to a page number, not a highlighted region), the
online 5% sampling loop against production traffic, and OpenTelemetry export
(the span fields are listed in the plan but not yet emitted).

The run-history drilldown, the quality radar chart and the embedding
inspector modal described in the plan **are** built -
[`RunDrilldownDrawer`](frontend/components/RunDrilldownDrawer.tsx),
[`QualityRadarChart`](frontend/components/QualityRadarChart.tsx), and
[`DocumentEmbeddingModal`](frontend/components/DocumentEmbeddingModal.tsx).
