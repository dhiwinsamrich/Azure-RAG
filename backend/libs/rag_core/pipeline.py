"""The answer pipeline: filter -> retrieve -> rank -> generate -> validate.

The evaluator imports this exact class, so an eval score is a statement about
the code that serves production traffic, not a reimplementation of it.

Dependencies arrive as protocols, which is what lets the test suite drive the
whole pipeline with fakes and no Azure account.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from .citations import validate_answer
from .clients import ChatModel, Embedder, Searcher
from .config import Settings, get_settings
from .generation import (
    answer_schema,
    build_messages,
    estimate_cost,
    parse_model_output,
)
from .retrieval import build_search_request, extract_filters
from .schemas import (
    Chunk,
    ChunkMetadata,
    DocType,
    QueryFilters,
    RetrievalConfig,
    ScoredChunk,
    StageTimings,
    TokenUsage,
    Trace,
)


class _Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = (time.perf_counter() - self.t0) * 1000.0
        return False


def hit_to_chunk(hit: dict[str, Any]) -> Chunk:
    """Map a search result back into the domain model."""
    doc_type = hit.get("doc_type") or DocType.UNKNOWN.value
    try:
        doc_type = DocType(doc_type)
    except ValueError:
        doc_type = DocType.UNKNOWN
    meta = ChunkMetadata(
        doc_id=hit.get("doc_id", ""),
        company=hit.get("company", "") or "",
        ticker=hit.get("ticker", "") or "",
        doc_type=doc_type,
        fiscal_year=hit.get("fiscal_year"),
        fiscal_quarter=hit.get("fiscal_quarter"),
        section_path=hit.get("section_path", "") or "",
        page_start=hit.get("page_start", 1) or 1,
        page_end=hit.get("page_end", 1) or 1,
        chunk_index=hit.get("chunk_index", 0) or 0,
        contains_table=bool(hit.get("contains_table", False)),
        source_url=hit.get("source_url", "") or "",
    )
    return Chunk(id=hit["id"], content=hit.get("content", ""), metadata=meta)


@dataclass
class RagPipeline:
    searcher: Searcher
    embedder: Embedder
    chat: ChatModel
    settings: Settings | None = None
    known_tickers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.s = self.settings or get_settings()

    async def retrieve(
        self, query: str, config: RetrievalConfig, filters: QueryFilters | None = None
    ) -> list[ScoredChunk]:
        vector = None
        if config.use_vector:
            vector = (await self.embedder.embed([query]))[0]

        request = build_search_request(query, config, filters, vector)
        hits = await self.searcher.search(**request)

        out: list[ScoredChunk] = []
        for i, hit in enumerate(hits):
            out.append(
                ScoredChunk(
                    chunk=hit_to_chunk(hit),
                    # Azure fuses server-side, so the response carries the fused
                    # order plus the reranker score when semantic ranking is on.
                    rrf_score=hit.get("@search.score"),
                    rerank_score=hit.get("@search.reranker_score"),
                    bm25_rank=i + 1 if config.use_bm25 and not config.use_vector else None,
                    vector_rank=i + 1 if config.use_vector and not config.use_bm25 else None,
                )
            )
        return out

    async def answer(
        self,
        query: str,
        config: RetrievalConfig,
        apply_filters: bool = True,
        doc_ids: list[str] | None = None,
    ) -> Trace:
        timings = StageTimings()

        with _Timer() as t:
            filters = (
                extract_filters(query, self.known_tickers) if apply_filters else QueryFilters()
            )
            # An explicit scope is authoritative: it is a choice the caller
            # made, not a guess from the question text.
            if doc_ids:
                filters = filters.model_copy(update={"doc_ids": list(doc_ids)})
        timings.filter_ms = t.ms

        with _Timer() as t:
            scored = await self.retrieve(query, config, filters)
        timings.retrieval_ms = t.ms

        context = [s.chunk for s in scored][: config.rerank_top_n]

        with _Timer() as t:
            raw, prompt_tokens, completion_tokens = await self.chat.complete(
                build_messages(query, context), answer_schema()
            )
        timings.generation_ms = t.ms

        model_answer = parse_model_output(raw)

        with _Timer() as t:
            validated = validate_answer(model_answer, context)
        timings.validation_ms = t.ms

        usage = TokenUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        return Trace(
            id=str(uuid.uuid4()),
            config_id=config.id,
            query=query,
            filters=filters,
            retrieved=scored,
            answer=validated.answer,
            citations=validated.citations,
            verdicts=validated.verdicts,
            refused=validated.refused,
            timings=timings,
            usage=usage,
            estimated_cost_usd=estimate_cost(
                prompt_tokens,
                completion_tokens,
                self.s.prompt_cost_per_1k,
                self.s.completion_cost_per_1k,
            ),
            model_deployment=config.gen_model,
        )
