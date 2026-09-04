from __future__ import annotations

import pytest
from rag_core.retrieval import (
    build_odata_filter,
    build_search_request,
    extract_filters,
    fuse,
    reciprocal_rank_fusion,
)
from rag_core.schemas import Chunk, ChunkMetadata, QueryFilters, RetrievalConfig

KNOWN = ["MSFT", "AAPL", "BRK"]


def test_extracts_ticker_year_and_quarter():
    f = extract_filters("AAPL Q3 2024 gross margin", KNOWN)
    assert f.tickers == ["AAPL"]
    assert 2024 in f.fiscal_years
    assert f.fiscal_quarters == [3]


def test_fy_shorthand_expands():
    assert 2023 in extract_filters("MSFT FY23 revenue", KNOWN).fiscal_years


def test_common_capitalised_words_are_not_treated_as_tickers():
    f = extract_filters("WHAT WAS THE REVENUE IN 2023", KNOWN)
    assert f.tickers == []


def test_unknown_ticker_is_ignored_when_a_universe_is_supplied():
    assert extract_filters("ZZZZ revenue", KNOWN).tickers == []


def test_doc_type_is_detected():
    assert "10-K" in extract_filters("in the annual report", KNOWN).doc_types


def test_no_constraints_gives_an_empty_filter():
    f = extract_filters("how did margins move", KNOWN)
    assert f.is_empty()
    assert build_odata_filter(f) is None


def test_odata_filter_shape():
    f = QueryFilters(tickers=["MSFT"], fiscal_years=[2023], doc_types=["10-K"])
    odata = build_odata_filter(f)
    assert "search.in(ticker, 'MSFT', ',')" in odata
    assert "fiscal_year eq 2023" in odata
    assert " and " in odata


def test_odata_escapes_single_quotes():
    f = QueryFilters(companies=["O'Reilly"])
    assert "O''Reilly" in build_odata_filter(f)


def test_hybrid_request_carries_both_retrievers_in_one_call():
    cfg = RetrievalConfig(id="h", use_bm25=True, use_vector=True, use_semantic_ranker=False)
    req = build_search_request("revenue", cfg, None, vector=[0.1, 0.2])

    assert req["search_text"] == "revenue"
    assert req["vector_queries"][0]["fields"] == "content_vector"
    # The vector field is never selected back - large and never needed.
    assert "content_vector" not in req["select"]


def test_semantic_ranker_switches_query_type_and_trims_to_rerank_top_n():
    cfg = RetrievalConfig(id="s", top_k=50, rerank_top_n=8)
    req = build_search_request("revenue", cfg, None, vector=[0.1])
    assert req["query_type"] == "semantic"
    assert req["top"] == 8


def test_bm25_only_sends_no_vector():
    cfg = RetrievalConfig(id="b", use_bm25=True, use_vector=False, use_semantic_ranker=False)
    req = build_search_request("revenue", cfg)
    assert "vector_queries" not in req


def test_vector_config_without_a_vector_is_a_programming_error():
    cfg = RetrievalConfig(id="v", use_bm25=False, use_vector=True, use_semantic_ranker=False)
    with pytest.raises(ValueError):
        build_search_request("revenue", cfg)


def test_semantic_ranker_requires_a_text_query():
    cfg = RetrievalConfig(id="x", use_bm25=False, use_vector=True, use_semantic_ranker=True)
    with pytest.raises(ValueError, match="semantic ranker"):
        build_search_request("revenue", cfg, vector=[0.1])


def test_rrf_rewards_agreement_between_retrievers():
    scores = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]], k=60)
    # b is 2nd and 1st; a is 1st and 2nd - equal, and both beat singletons.
    assert scores["a"] == pytest.approx(scores["b"])
    assert scores["a"] > scores["c"] > 0
    assert scores["d"] == pytest.approx(1 / 63)  # rank 3 in the second list only


def test_fuse_orders_by_score_and_records_both_ranks():
    chunks = {
        cid: Chunk(id=cid, content=cid, metadata=ChunkMetadata(doc_id="d"))
        for cid in ("a", "b", "c")
    }
    out = fuse(chunks, bm25_ids=["a", "b"], vector_ids=["b", "c"])

    assert out[0].chunk.id == "b"
    assert out[0].bm25_rank == 2 and out[0].vector_rank == 1
    assert [s.chunk.id for s in out] == sorted(
        [s.chunk.id for s in out], key=lambda i: -dict(
            (s.chunk.id, s.rrf_score) for s in out
        )[i]
    )
