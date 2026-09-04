# Project 1 — Financial Document Intelligence & RAG on Azure

**What it proves:** RAG design and operation, chunking, embeddings, hybrid retrieval, re-ranking, evaluation, citation display, document classification, PDF/Excel extraction, secure Azure deployment, observability, CI/CD.

**Covers:** JD requirements 1, 4, 5, 7 (Azure half) and the NLP/Document Intelligence Engine bullet (finance half).

**Realistic time:** 3–4 weeks part-time.

---

## 1. Choose a corpus you can actually defend

Use real financial documents. Free and public:

- **SEC EDGAR** — 10-K and 10-Q filings. Full-text API, no key required. Table-heavy, long, messy: exactly the hard case.
- **Berkshire Hathaway shareholder letters** — the classic "fund manager letter" analogue, decades of them, narrative + numbers.
- **Annual reports** from any listed company's investor-relations page as PDF.

Target 100–300 documents. Enough that retrieval quality actually varies; small enough to re-index cheaply while you're tuning.

Do not use a synthetic or toy corpus. The entire value of this project in an interview is that you hit real problems — tables spanning pages, footnotes, restated figures — and can describe how you handled them.

---

## 2. Architecture

```
Blob Storage (raw PDFs/XLSX)
        ↓
Azure AI Document Intelligence  (prebuilt-layout)
        ↓
Layout-aware chunker  +  metadata enrichment
        ↓
Azure OpenAI embeddings  (text-embedding-3-large)
        ↓
Azure AI Search index   (BM25 + HNSW vector + semantic config)
        ↓
Hybrid query → RRF fusion → semantic ranker → (optional cross-encoder)
        ↓
Azure OpenAI chat completion  (citation-constrained prompt)
        ↓
Answer + inline citations (doc, page, section)

Cross-cutting: Key Vault + Managed Identity · App Insights + Log Analytics
               RAGAS/Azure AI Evaluation harness · Azure DevOps pipeline
```

---

## 3. Stage-by-stage design

### 3.1 Parsing — Azure AI Document Intelligence

Use the **`prebuilt-layout`** model, not `prebuilt-read`. Layout gives you what makes this project work:

- **Tables as structured objects** — cells with row/column indices and spans. Financial documents are mostly tables. Naive PDF text extraction flattens a balance sheet into unreadable soup; this is the single biggest quality difference in the whole pipeline.
- **Section headings with hierarchy** — your chunk boundaries.
- **Page numbers and bounding regions** — without these you cannot build real citations.
- **Markdown output mode** — returns the document as markdown with tables preserved in pipe syntax. Easiest path for LLM consumption.

Design notes:

- It's an async operation: submit, poll for completion. Budget for that in your ingestion job.
- Tables that span a page break come back as two tables. You need reconciliation logic — check whether the next page starts with a table whose column count and header row match the previous one, and merge. This is a genuinely good thing to have solved and to talk about.
- Excel files don't go through Document Intelligence. Use `openpyxl`/`pandas` and convert sheets to markdown tables, then join the same chunking path.

### 3.2 Chunking — the decision that drives everything

Do not use fixed-size character chunking. Justify a layout-aware strategy:

**Rules:**
1. Split on section headings from the layout model, not on character counts.
2. **Never split a table.** If a table alone exceeds your target size, emit it as its own chunk and prepend the section heading for context.
3. If a section exceeds the target, split on paragraph boundaries with ~10–15% overlap.
4. Prepend a context header to every chunk: `[Company] · [Doc type] · [Fiscal period] · [Section path]`. Small chunks lose their referent otherwise — "revenue increased 12%" is useless without knowing whose revenue, and which year.

**Target size:** 500–800 tokens with ~100 token overlap is a reasonable starting point. Then *test it* — run your eval harness at 300/500/800/1200 and report the curve. Having that curve is what separates you from candidates who guessed once.

**Metadata to attach to every chunk** (this is what makes filtering work later):
`doc_id`, `company`, `ticker`, `doc_type`, `fiscal_year`, `fiscal_quarter`, `section_path`, `page_start`, `page_end`, `chunk_index`, `contains_table` (bool), `source_url`.

### 3.3 Embeddings

`text-embedding-3-large` (3072 dims) or `-small` (1536). Large is better on financial jargon; small is ~5× cheaper and often sufficient.

Worth knowing: `text-embedding-3-*` supports **dimension shortening** — you can request 1024 dims from the large model and retain most of the quality at a third of the index storage. Being able to explain that tradeoff is a good interview moment.

Batch your embedding calls (up to a few hundred inputs per request) and handle 429s with exponential backoff — you will hit rate limits on first ingestion.

### 3.4 Index design in Azure AI Search

This is the technical core. Fields:

| Field | Type | Config |
|---|---|---|
| `id` | Edm.String | key |
| `content` | Edm.String | searchable (BM25), retrievable |
| `content_vector` | Collection(Edm.Single) | searchable, **retrievable: false**, HNSW profile |
| `company`, `doc_type`, `fiscal_year` | Edm.String / Int32 | **filterable**, facetable |
| `section_path` | Edm.String | searchable, retrievable |
| `page_start`, `page_end` | Edm.Int32 | retrievable |
| `contains_table` | Edm.Boolean | filterable |

Set `retrievable: false` on the vector field. You never need the raw floats back and it meaningfully cuts response payload size.

**Vector config (HNSW):** `m` (graph connectivity, default 4 — raise to 8–10 for better recall at higher memory), `efConstruction` (build quality, 400 is a good default), `efSearch` (query-time breadth, tune this). Choose `cosine` similarity for OpenAI embeddings.

**Semantic configuration:** name the fields the semantic ranker should read — title field (`section_path`), content fields (`content`). Required to enable semantic ranking.

### 3.5 Retrieval — why hybrid, specifically

This is the part to understand deeply, because it's the most likely interview question.

**Run BM25 and vector search in parallel, fuse with Reciprocal Rank Fusion (RRF), then re-rank the fused set with the semantic ranker.** Azure AI Search does the RRF fusion natively when you send both a `search` text and a `vectorQueries` array in one request.

Why hybrid matters *especially* for financial documents: **embeddings are unreliable on exact numbers, tickers, and defined terms.** A query for "AAPL Q3 2024 gross margin" needs lexical matching on `AAPL` and `Q3` — vector similarity will happily return Q2 2023 Microsoft margins because the semantic content is nearly identical. BM25 catches the exact tokens; vectors catch the paraphrase ("profitability on sales"). Neither alone is sufficient. That reasoning, stated in an interview, lands well.

**Then the semantic ranker.** It's a Microsoft-hosted cross-encoder that re-scores the top ~50 results using the full query-document pair rather than independent embeddings. It's a separate billed tier — enable it deliberately.

⚠️ **Gotcha:** the semantic ranker only reads roughly the first 2,000 tokens of your content field. If your chunks are larger than that, the ranker silently scores a truncated version. Another argument for chunks in the 500–800 range.

**Metadata filtering:** if the query mentions a company or period, extract it (a small LLM call or regex) and pass an OData `$filter`. Filtering before search is dramatically better than hoping ranking sorts it out.

### 3.6 Optional: your own re-ranker

After the semantic ranker, you can add a cross-encoder like `BAAI/bge-reranker-v2-m3` locally. Usually unnecessary given the semantic ranker — but implementing it once and *measuring that it didn't help* is a legitimately strong result to report. Negative findings with data beat unmeasured additions.

### 3.7 Generation and citations

The citation requirement is the part most people implement badly. Do this:

1. Number the retrieved chunks in the prompt: `[1] ... [2] ...`, each with its metadata header.
2. System prompt: answer **only** from provided context; cite the bracket number after every factual claim; if the context doesn't contain the answer, say so explicitly and cite nothing.
3. Request **structured output** (JSON schema / tool call) with `answer` and `citations: [{chunk_id, quoted_span}]` rather than parsing brackets out of prose.
4. **Post-validate.** Check every returned `chunk_id` was actually in the context set, and that `quoted_span` appears in that chunk. Drop or flag any that fail. This is programmatic hallucination detection and it's cheap.
5. Render citations back to `company · doc_type · fiscal_period · page N`, linked to the source.

Step 4 is the differentiator. "I validate citations programmatically rather than trusting the model" is a strong sentence.

---

## 4. The three extra capabilities (finance-half coverage)

Bolt these onto the same corpus — they cost little extra and unlock the finance-track bullets.

**Document classification.** Classify each doc as 10-K / 10-Q / manager letter / prospectus / press release. Start with a few-shot LLM classifier on the first page; build a labeled set of ~200 from its output plus manual correction; then fine-tune a small encoder (DistilBERT/RoBERTa — you've already done this with RoBERTa) and compare. Report both accuracy and cost-per-document. The comparison *is* the result.

**Structured financial extraction.** Pull a fixed schema — revenue, COGS, operating income, net income, total assets, total equity — from the parsed tables into a typed Pydantic model. Validate with accounting identities (assets = liabilities + equity; margins within plausible bounds) and flag violations rather than silently accepting. Feeds DuPont decomposition later in Project 3.

**Summarization + sentiment on manager letters.** Per-letter summary plus a sentiment/tone score. Track the score across time per author. Anchor sentiment to a defined rubric (e.g. forward-looking confidence, 1–5, with anchor descriptions) rather than a bare "positive/negative" — it's more defensible and more useful.

---

## 5. Evaluation — do not skip this

This is where most portfolio RAG projects stop, and it's the single highest-signal part.

**Build a golden set.** 50–80 question/answer pairs over your corpus, each with the correct source chunk(s) recorded. Mix the types deliberately:
- Single-fact lookup ("what was FY23 revenue")
- Multi-hop ("how did gross margin change between FY22 and FY23")
- Table-dependent ("what was the largest segment by operating income")
- **Unanswerable** ("what is the CEO's home address") — tests refusal behavior, which most people never measure

**Metrics — retrieval:** context precision, context recall, hit rate @k, MRR.
**Metrics — generation:** faithfulness/groundedness, answer relevancy, citation accuracy (your programmatic check).
**Metrics — operational:** p50/p95 latency, tokens per query, cost per query.

**Tooling:** RAGAS for the standard metrics, Azure AI Evaluation SDK for groundedness/relevance/retrieval evaluators that plug into Foundry.

**Run ablations and keep the table.** Vector-only vs BM25-only vs hybrid vs hybrid+semantic ranker. Chunk size sweep. This table is the best artifact of the whole project — put it in the README and bring it to the interview.

---

## 6. Production wrap

**Security.** Azure OpenAI and AI Search keys in Key Vault; the app authenticates with **Managed Identity** so no secret ever touches application code or config. Use RBAC data-plane roles (Search Index Data Reader, Cognitive Services OpenAI User) rather than admin keys. Add Private Endpoints if you want to go further.

**Observability.** Instrument with OpenTelemetry → Application Insights. Custom dimensions worth logging per request: `retrieval_latency_ms`, `generation_latency_ms`, `chunks_retrieved`, `prompt_tokens`, `completion_tokens`, `estimated_cost`, `citation_validation_failures`, `refusal` (bool), `model_deployment`.

Then write **KQL queries** against Log Analytics — p95 latency by query type, token spend per day, citation-failure rate over time. Screenshot the dashboard for your portfolio. KQL is a concrete listable skill and almost nobody at your level has it.

**CI/CD.** Azure DevOps pipeline: lint → unit tests (chunker, citation validator, metadata extractor) → integration tests against a small fixture index → build container → deploy to App Service or Container Apps. Add a **quality gate**: run the eval harness on a 20-question subset and fail the build if faithfulness drops below threshold. That's a genuinely senior move and very few candidates do it.

---

## 7. Sequenced build order

| Week | Deliverable |
|---|---|
| 1 | Blob ingestion + Document Intelligence parsing + table reconciliation. Output: clean markdown + metadata JSON per doc. |
| 1–2 | Chunker with layout awareness. Embedding pipeline. Index creation and population. |
| 2 | Hybrid retrieval + semantic ranker + filters. Basic answer generation. |
| 2–3 | Citation generation and programmatic validation. Golden set construction. |
| 3 | Eval harness, ablation table, chunk-size sweep. |
| 3–4 | Key Vault + Managed Identity, App Insights + KQL, Azure DevOps pipeline with eval gate. |
| 4 | Classification, extraction, sentiment add-ons. README with architecture diagram and results table. |

---

## 8. Traps that will cost you time

- Document Intelligence async polling — build retry/resume into ingestion or a mid-run failure restarts everything.
- Tables split across page boundaries. Handle explicitly.
- Embedding rate limits on first bulk ingest. Batch and back off.
- Semantic ranker's ~2,000 token read limit silently truncating oversized chunks.
- Re-indexing is slow. Store parsed output and chunks on disk so you can re-embed without re-parsing.
- Azure OpenAI quota is per-region and per-deployment. Check your TPM allocation before assuming throughput.
- Product naming: current portal branding is **Microsoft Foundry** (renamed from Azure AI Foundry, Jan 2026). Azure AI Search and Azure AI Document Intelligence kept their names. Write both forms in your README and resume.
