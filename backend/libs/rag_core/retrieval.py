"""Hybrid retrieval: filter extraction, request construction, RRF.

The key design point is that hybrid search is ONE request. Azure AI Search
performs the reciprocal-rank fusion server-side when a request carries both a
`search_text` and a `vector_queries` array - you do not issue two searches and
merge them in application code.

`reciprocal_rank_fusion` is still implemented here because the ablation needs a
local, deterministic fusion for the BM25-only and vector-only comparisons, and
because it is the thing worth being able to explain.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from .schemas import Chunk, QueryFilters, RetrievalConfig, ScoredChunk

# A ticker is 1-5 upper-case letters, but so are plenty of English words in
# caps, so we require it to look deliberate rather than incidental.
_TICKER = re.compile(r"\b([A-Z]{1,5})\b")
_TICKER_STOP = {
    "A", "I", "AN", "THE", "AND", "OR", "OF", "IN", "ON", "TO", "FOR", "BY",
    "FY", "Q", "US", "USA", "GAAP", "SEC", "CEO", "CFO", "EPS", "YOY", "CAGR",
    "PDF", "AI", "IT", "IS", "WAS", "HOW", "WHAT", "WHEN", "DID", "VS",
}

_FY = re.compile(r"\b(?:FY|fiscal(?:\s+year)?\s*)[\s']*((?:19|20)\d{2}|\d{2})\b", re.IGNORECASE)
_BARE_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_QUARTER = re.compile(r"\bQ([1-4])\b", re.IGNORECASE)

_DOC_TYPES = {
    "10-k": "10-K", "10k": "10-K", "annual report": "10-K",
    "10-q": "10-Q", "10q": "10-Q", "quarterly": "10-Q",
    "letter": "manager-letter", "shareholder letter": "manager-letter",
    "prospectus": "prospectus", "press release": "press-release",
}


def extract_filters(query: str, known_tickers: Iterable[str] | None = None) -> QueryFilters:
    """Pull structured constraints out of a natural-language query.

    Filtering before search beats hoping the ranker sorts it out: a query for
    "AAPL Q3 2024 gross margin" is answered by the wrong company's chunk far
    more often than people expect, because the semantic content is nearly
    identical across issuers.
    """
    f = QueryFilters()
    if not query:
        return f

    known = {t.upper() for t in (known_tickers or [])}
    for m in _TICKER.finditer(query):
        tok = m.group(1)
        if tok in _TICKER_STOP:
            continue
        if known and tok not in known:
            continue
        if not known and len(tok) < 2:
            continue
        f.tickers.append(tok)

    years: set[int] = set()
    for m in _FY.finditer(query):
        raw = m.group(1)
        years.add(int(raw) if len(raw) == 4 else 2000 + int(raw))
    for m in _BARE_YEAR.finditer(query):
        years.add(int(m.group(1)))
    f.fiscal_years = sorted(years)
    f.fiscal_quarters = sorted({int(m.group(1)) for m in _QUARTER.finditer(query)})

    low = query.lower()
    for needle, doc_type in _DOC_TYPES.items():
        if needle in low and doc_type not in f.doc_types:
            f.doc_types.append(doc_type)

    f.tickers = sorted(set(f.tickers))
    return f


def _quote(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"


def build_odata_filter(f: QueryFilters) -> str | None:
    """Render filters as an OData expression for Azure AI Search."""
    clauses: list[str] = []
    if f.doc_ids:
        clauses.append(f"search.in(doc_id, {_quote('|'.join(f.doc_ids))}, '|')")
    if f.tickers:
        clauses.append(f"search.in(ticker, {_quote(','.join(f.tickers))}, ',')")
    if f.companies:
        clauses.append(f"search.in(company, {_quote('|'.join(f.companies))}, '|')")
    if f.doc_types:
        clauses.append(f"search.in(doc_type, {_quote(','.join(f.doc_types))}, ',')")
    if f.fiscal_years:
        inner = " or ".join(f"fiscal_year eq {y}" for y in f.fiscal_years)
        clauses.append(f"({inner})")
    if f.fiscal_quarters:
        inner = " or ".join(f"fiscal_quarter eq {q}" for q in f.fiscal_quarters)
        clauses.append(f"({inner})")
    return " and ".join(clauses) if clauses else None


def build_search_request(
    query: str,
    config: RetrievalConfig,
    filters: QueryFilters | None = None,
    vector: Sequence[float] | None = None,
    vector_field: str = "content_vector",
) -> dict[str, Any]:
    """Build the kwargs for a single `SearchClient.search` call.

    Both retrievers ride in one request so the service fuses them with RRF;
    `select` deliberately omits the vector field, which is large and never
    needed back.
    """
    req: dict[str, Any] = {
        "top": config.top_k,
        "select": [
            "id", "content", "doc_id", "company", "ticker", "doc_type",
            "fiscal_year", "fiscal_quarter", "section_path",
            "page_start", "page_end", "contains_table", "source_url", "chunk_index",
        ],
    }

    req["search_text"] = query if config.use_bm25 else None

    if config.use_vector:
        if vector is None:
            raise ValueError("config.use_vector is set but no query vector was supplied")
        try:
            from azure.search.documents.models import VectorizedQuery
        except ImportError:
            # The `azure` extra is optional - local mode never needs it - so
            # falling back to a plain dict here is expected. A real bug inside
            # the SDK call below must NOT be caught by the same branch, or it
            # silently swaps in a differently-shaped query object instead of
            # surfacing the compatibility problem.
            req["vector_queries"] = [{
                "kind": "vector",
                "vector": list(vector),
                "k_nearest_neighbors": max(config.top_k, config.rerank_top_n),
                "fields": vector_field,
            }]
        else:
            req["vector_queries"] = [
                VectorizedQuery(
                    vector=list(vector),
                    k_nearest_neighbors=max(config.top_k, config.rerank_top_n),
                    fields=vector_field,
                )
            ]

    if config.use_semantic_ranker:
        if not config.use_bm25:
            # The semantic ranker re-scores textual results; without a text
            # query there is nothing for it to read.
            raise ValueError("semantic ranker requires use_bm25=True")
        req["query_type"] = "semantic"
        req["semantic_configuration_name"] = "default"
        req["top"] = config.rerank_top_n

    odata = build_odata_filter(filters) if filters else None
    if odata:
        req["filter"] = odata
    return req


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], k: int = 60
) -> dict[str, float]:
    """RRF over any number of ranked id lists.

    score(d) = sum over rankings of 1 / (k + rank(d)), rank being 1-based.
    The constant k damps the influence of top positions so one retriever
    cannot dominate purely by being confident.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for i, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + i)
    return scores


def fuse(
    chunks_by_id: dict[str, Chunk],
    bm25_ids: Sequence[str],
    vector_ids: Sequence[str],
    k: int = 60,
    top_n: int | None = None,
) -> list[ScoredChunk]:
    """Local fusion used by the ablation harness."""
    rankings = [r for r in (bm25_ids, vector_ids) if r]
    scores = reciprocal_rank_fusion(rankings, k=k)
    bm25_pos = {d: i + 1 for i, d in enumerate(bm25_ids)}
    vec_pos = {d: i + 1 for i, d in enumerate(vector_ids)}

    out = [
        ScoredChunk(
            chunk=chunks_by_id[doc_id],
            bm25_rank=bm25_pos.get(doc_id),
            vector_rank=vec_pos.get(doc_id),
            rrf_score=score,
        )
        for doc_id, score in scores.items()
        if doc_id in chunks_by_id
    ]
    out.sort(key=lambda s: (-(s.rrf_score or 0.0), s.chunk.id))
    return out[:top_n] if top_n else out
