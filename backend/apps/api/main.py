"""FastAPI application: chat, retrieval debug, corpus and evaluation."""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

# Ensure libs and apps root are on sys.path
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_ROOT / "libs") not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT / "libs"))
if str(_BACKEND_ROOT / "apps") not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT / "apps"))
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from rag_core import relevance
from rag_core.config import get_config, load_configs
from rag_core.evaluation.custom import ALL_METRICS
from rag_core.retrieval import build_odata_filter, extract_filters
from rag_core.schemas import QueryFilters, Trace

from .deps import get_pipeline, get_store, settings

app = FastAPI(
    title="Financial RAG API",
    version="0.1.0",
    description="Hybrid retrieval over financial filings with validated citations.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")


# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------

class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    config_id: str | None = None
    apply_filters: bool = True
    # Empty means every indexed document.
    doc_ids: list[str] = Field(default_factory=list)


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@api.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """Server-sent events.

    The client needs more than tokens: citation objects, per-citation validation
    verdicts and stage timings arrive as distinct event types it renders
    differently, which a bare token stream cannot express.
    """
    config = get_config(req.config_id or settings().default_config_id)
    pipeline = get_pipeline()
    store = get_store()

    async def stream():
        yield sse("start", {"config_id": config.id, "config": config.label()})
        try:
            trace = await pipeline.answer(
                req.query, config, req.apply_filters, req.doc_ids
            )
        except Exception as exc:  # surfaced to the UI rather than a dead stream
            yield sse("error", {"message": str(exc)})
            return

        # The answer is produced as one structured object, then replayed in
        # word chunks so the UI can render progressively.
        words = trace.answer.split(" ")
        for i in range(0, len(words), 6):
            yield sse("token", {"text": " ".join(words[i:i + 6]) + " "})
            await asyncio.sleep(0)

        yield sse("citations", [c.model_dump() for c in trace.citations])
        yield sse("validation", {
            "verdicts": [v.model_dump() for v in trace.verdicts],
            "validity": round(
                sum(v.valid for v in trace.verdicts) / len(trace.verdicts), 4
            ) if trace.verdicts else 1.0,
            "failures": sum(not v.valid for v in trace.verdicts),
        })
        yield sse("trace", {
            "trace_id": trace.id,
            "refused": trace.refused,
            "chunks_retrieved": len(trace.retrieved),
            "filters": trace.filters.model_dump(),
            "timings": trace.timings.model_dump(),
            "total_ms": round(trace.timings.total_ms, 1),
            "usage": trace.usage.model_dump(),
            "estimated_cost_usd": trace.estimated_cost_usd,
            "sources": [
                {
                    "chunk_id": s.chunk.id,
                    "doc_id": s.chunk.metadata.doc_id,
                    "header": s.chunk.context_header(),
                    "page_start": s.chunk.metadata.page_start,
                    "page_end": s.chunk.metadata.page_end,
                    "score": s.score,
                }
                for s in trace.retrieved
            ],
        })
        store.save_trace(trace)
        yield sse("done", {"trace_id": trace.id})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------
# Retrieval debug
# --------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    config_id: str | None = None
    apply_filters: bool = True
    doc_ids: list[str] = Field(default_factory=list)


@api.post("/search")
async def search(req: SearchRequest) -> dict[str, Any]:
    """Retrieval only. Returns each candidate with its per-retriever position so
    a bad answer can be diagnosed without guessing."""
    config = get_config(req.config_id or settings().default_config_id)
    filters = extract_filters(req.query) if req.apply_filters else QueryFilters()
    if req.doc_ids:
        filters = filters.model_copy(update={"doc_ids": list(req.doc_ids)})
    scored = await get_pipeline().retrieve(req.query, config, filters)
    return {
        "config_id": config.id,
        "filters": filters.model_dump(),
        "odata_filter": build_odata_filter(filters),
        "results": [
            {
                "chunk_id": s.chunk.id,
                "header": s.chunk.context_header(),
                "content": s.chunk.content[:600],
                "bm25_rank": s.bm25_rank,
                "vector_rank": s.vector_rank,
                "rrf_score": s.rrf_score,
                "rerank_score": s.rerank_score,
                "contains_table": s.chunk.metadata.contains_table,
            }
            for s in scored
        ],
    }


@api.get("/traces/{trace_id}")
async def get_trace(trace_id: str) -> Trace:
    trace = get_store().get_trace(trace_id)
    if trace is None:
        raise HTTPException(404, f"no trace {trace_id}")
    return trace


@api.get("/traces")
async def list_traces(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    return [
        {
            "id": t.id, "query": t.query, "config_id": t.config_id,
            "refused": t.refused, "total_ms": round(t.timings.total_ms, 1),
            "citation_failures": sum(not v.valid for v in t.verdicts),
            "created_at": t.created_at,
        }
        for t in get_store().recent_traces(limit)
    ]


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

@api.get("/configs")
async def configs() -> list[dict[str, Any]]:
    return [c.model_dump() for c in load_configs().values()]


# --------------------------------------------------------------------------
# Corpus: upload, inspect chunking, inspect embeddings
# --------------------------------------------------------------------------

def _chunk_view(chunk, vector: list[float] | None = None) -> dict[str, Any]:
    m = chunk.metadata
    header, _, body = chunk.content.partition("\n\n")
    view: dict[str, Any] = {
        "id": chunk.id,
        "chunk_index": m.chunk_index,
        "section_path": m.section_path,
        "page_start": m.page_start,
        "page_end": m.page_end,
        "contains_table": m.contains_table,
        "token_count": chunk.token_count,
        # The context header is stored inside the indexed text, so it is split
        # out here to make visible what the chunker prepends and why.
        "context_header": header.strip("[]") if header.startswith("[") else "",
        "body": body or chunk.content,
        "content": chunk.content,
    }
    if vector:
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        view["embedding"] = {
            "dims": len(vector),
            "norm": round(norm, 4),
            # A short slice is enough to show the vector is real and to render
            # a sparkline; sending 1536 floats per chunk to the browser is not.
            "preview": [round(v, 4) for v in vector[:48]],
        }
    return view


@api.post("/ingest/preview")
async def ingest_preview(file: UploadFile = File(...)) -> dict[str, Any]:
    """Parse and chunk an uploaded document WITHOUT embedding or indexing.

    Free and instant: it is the loop for tuning chunking, which is the setting
    that drives retrieval quality more than any other.
    """
    from rag_core.chunking import LayoutChunker
    from rag_core.clients import build_parser

    from apps.ingest.pipeline import IngestPipeline

    s = settings()
    content = await file.read()
    pipeline = IngestPipeline(
        parser=build_parser(s), embedder=None, searcher=None, settings=s
    )
    doc_id = (file.filename or "upload").rsplit(".", 1)[0]

    try:
        parsed, _ = await pipeline.parse(doc_id, content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"parse failed: {exc}") from exc

    chunks = pipeline.to_chunks(parsed, source_url=f"upload://{file.filename}")
    chunker = LayoutChunker()
    verdict = relevance.assess(relevance.sample_text(parsed), doc_id)
    return {
        "doc_id": doc_id,
        "relevance": verdict.to_dict(),
        "filename": file.filename,
        "indexed": False,
        "pages": len(parsed.get("pages", []) or []),
        "blocks": len(parsed.get("paragraphs", []) or []) + len(parsed.get("tables", []) or []),
        "chunk_settings": {
            "target_tokens": chunker.target,
            "overlap_tokens": chunker.overlap,
            "max_tokens": chunker.max_tokens,
        },
        "chunks": [_chunk_view(c) for c in chunks],
    }


@api.post("/ingest/upload")
async def ingest_upload(
    file: UploadFile = File(...),
    index: bool = Form(True),
    force: bool = Form(False),
) -> dict[str, Any]:
    """Parse, chunk, embed and index an uploaded document.

    Non-financial documents are refused: one in the index competes for every
    query and a large one crowds the filings out entirely. `force` overrides
    the check, because a keyword heuristic will eventually be wrong and a hard
    block with no escape hatch is worse than a warning.
    """
    from rag_core.clients import build_embedder, build_parser, build_searcher
    from rag_core.indexing import chunk_to_document

    from apps.ingest.pipeline import IngestPipeline

    s = settings()
    content = await file.read()
    embedder = build_embedder(s)
    searcher = build_searcher(s)
    pipeline = IngestPipeline(
        parser=build_parser(s), embedder=embedder, searcher=searcher, settings=s
    )
    doc_id = (file.filename or "upload").rsplit(".", 1)[0]

    try:
        parsed, from_cache = await pipeline.parse(doc_id, content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"parse failed: {exc}") from exc

    verdict = relevance.assess(relevance.sample_text(parsed), doc_id)
    if not verdict.accepted and not force:
        raise HTTPException(
            422,
            {
                "message": "This does not look like a financial document.",
                "relevance": verdict.to_dict(),
            },
        )

    chunks = pipeline.to_chunks(parsed, source_url=f"upload://{file.filename}")
    vectors: list[list[float]] = []
    indexed = 0
    if index and chunks:
        try:
            vectors = await embedder.embed([c.content for c in chunks])
            indexed = await searcher.upload([
                chunk_to_document(c, v) for c, v in zip(chunks, vectors, strict=True)
            ])
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"index failed: {exc}") from exc

    dims = len(vectors[0]) if vectors else 0
    store = get_store()
    meta = chunks[0].metadata if chunks else None
    store.save_document(
        doc_id,
        {
            "company": meta.company if meta else "",
            "ticker": meta.ticker if meta else "",
            "doc_type": meta.doc_type.value if meta else "",
            "fiscal_year": meta.fiscal_year if meta else None,
            "page_count": len(parsed.get("pages", []) or []),
            "source_url": f"upload://{file.filename}",
        },
        len(chunks),
        bool(indexed),
    )
    store.save_chunks(chunks, dims)

    return {
        "doc_id": doc_id,
        "filename": file.filename,
        "relevance": verdict.to_dict(),
        "forced": bool(force and not verdict.accepted),
        "indexed": bool(indexed),
        "indexed_count": indexed,
        "from_cache": from_cache,
        "pages": len(parsed.get("pages", []) or []),
        "embed_dims": dims,
        "chunks": [
            _chunk_view(c, vectors[i] if i < len(vectors) else None)
            for i, c in enumerate(chunks)
        ],
    }


@api.get("/documents")
async def list_documents() -> list[dict[str, Any]]:
    """Documents that can actually be searched.

    Sourced from the index rather than the store, because anything ingested
    with the CLI is searchable but was never written to the store. Store
    metadata is merged in where it exists.
    """
    from rag_core.clients import build_searcher

    searcher = build_searcher(settings())
    lister = getattr(searcher, "list_documents", None)
    if lister is None:
        return get_store().documents()

    docs = lister()
    if asyncio.iscoroutine(docs):
        docs = await docs

    stored = {d["id"]: d for d in get_store().documents()}
    for d in docs:
        extra = stored.get(d["doc_id"])
        if extra:
            d["company"] = d.get("company") or extra.get("company", "")
            d["ticker"] = d.get("ticker") or extra.get("ticker", "")
            d["doc_type"] = d.get("doc_type") or extra.get("doc_type", "")
            d["fiscal_year"] = d.get("fiscal_year") or extra.get("fiscal_year")
            d["page_count"] = extra.get("page_count")
    return docs


@api.get("/documents/{doc_id}/chunks")
async def document_chunks(doc_id: str) -> dict[str, Any]:
    from rag_core.clients import build_searcher

    store = get_store()
    chunks = store.chunks(doc_id)
    searcher = build_searcher(settings())

    # Collect vectors from searcher if available
    doc_vectors: dict[str, list[float]] = {}
    if hasattr(searcher, "docs"):
        for cid, d in searcher.docs.items():
            did = d.get("doc_id") or cid.split("::")[0]
            if did == doc_id and d.get("content_vector"):
                doc_vectors[cid] = d["content_vector"]

    if not chunks:
        # Fallback to search index if document was ingested via CLI without store chunks
        if hasattr(searcher, "docs"):
            matching = [
                d for cid, d in searcher.docs.items()
                if (d.get("doc_id") or cid.split("::")[0]) == doc_id
            ]
            if matching:
                matching.sort(key=lambda x: x.get("chunk_index", 0))
                views = []
                dims = 0
                for d in matching:
                    vec = d.get("content_vector")
                    if vec and not dims:
                        dims = len(vec)
                    header, _, body = d.get("content", "").partition("\n\n")
                    view: dict[str, Any] = {
                        "id": d.get("id"),
                        "chunk_index": d.get("chunk_index", 0),
                        "section_path": d.get("section_path", ""),
                        "page_start": d.get("page_start", 1),
                        "page_end": d.get("page_end", 1),
                        "contains_table": bool(d.get("contains_table", False)),
                        "token_count": d.get("token_count", 0),
                        "context_header": header.strip("[]") if header.startswith("[") else "",
                        "body": body or d.get("content", ""),
                        "content": d.get("content", ""),
                    }
                    if vec:
                        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
                        view["embedding"] = {
                            "dims": len(vec),
                            "norm": round(norm, 4),
                            "preview": [round(v, 4) for v in vec[:48]],
                        }
                    views.append(view)
                return {
                    "doc_id": doc_id,
                    "embed_dims": dims,
                    "chunks": views,
                }
        raise HTTPException(404, f"no chunks stored for {doc_id}")

    dims = store.chunk_dims(doc_id)
    views = []
    for c in chunks:
        vec = doc_vectors.get(c.id)
        if vec and not dims:
            dims = len(vec)
        views.append(_chunk_view(c, vec))

    return {
        "doc_id": doc_id,
        "embed_dims": dims,
        "chunks": views,
    }


@api.delete("/documents/{doc_id}")
async def delete_document(doc_id: str) -> dict[str, Any]:
    """Remove a document from the index and the store.

    The index is what retrieval reads, so clearing only the store would leave
    the chunks and their embeddings answering queries.
    """
    from rag_core.clients import build_searcher

    searcher = build_searcher(settings())
    removed = 0
    remover = getattr(searcher, "delete_document", None)
    if remover is not None:
        result = remover(doc_id)
        removed = await result if asyncio.iscoroutine(result) else result

    get_store().delete_document(doc_id)
    return {"status": "deleted", "doc_id": doc_id, "chunks_removed": removed}


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

@api.get("/eval/golden-set")
async def golden_set() -> list[dict[str, Any]]:
    return [q.model_dump() for q in get_store().questions()]


@api.get("/eval/runs")
async def eval_runs(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    return get_store().list_runs(limit)


@api.get("/eval/runs/{run_id}/summary")
async def run_summary(run_id: str) -> dict[str, Any]:
    store = get_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"no eval run {run_id}")
    questions = {q.id: q for q in store.questions()}
    return {
        "run_id": run.id,
        "config_id": run.config_id,
        "trigger": run.trigger,
        "status": run.status,
        "judge_model": run.judge_model,
        "n_questions": len(run.results),
        "overall": {k: round(v, 4) for k, v in run.aggregate().items()},
        # The segment breakdown is the point: a healthy mean routinely hides a
        # failing question type.
        "by_question_type": {
            t: {k: round(v, 4) for k, v in metrics.items()}
            for t, metrics in run.aggregate_by_type(questions).items()
        },
    }


@api.get("/eval/runs/{run_id}/questions")
async def run_questions(run_id: str) -> list[dict[str, Any]]:
    store = get_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"no eval run {run_id}")
    questions = {q.id: q for q in store.questions()}
    out = []
    for r in run.results:
        q = questions.get(r.question_id)
        out.append({
            "question_id": r.question_id,
            "question": q.question if q else "",
            "q_type": q.q_type.value if q else "",
            "answerable": q.answerable if q else True,
            "gold_answer": q.gold_answer if q else "",
            "gold_chunk_ids": q.gold_chunk_ids if q else [],
            "trace_id": r.trace_id,
            "metrics": [m.model_dump() for m in r.metrics],
        })
    return out


@api.get("/eval/compare")
async def compare(metrics: str = Query(",".join(ALL_METRICS[:4]))) -> dict[str, Any]:
    """Configs x metrics - renders the ablation matrix directly."""
    store = get_store()
    wanted = [m.strip() for m in metrics.split(",") if m.strip()]
    matrix: dict[str, dict[str, float]] = {}
    for metric in wanted:
        for row in store.compare(metric):
            matrix.setdefault(row["config_id"], {})[metric] = row["value"]
    return {"metrics": wanted, "configs": matrix}


app.include_router(api)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
