"""Tests for the zero-cost local backends.

The local searcher must accept exactly the requests `build_search_request`
produces and the filters `build_odata_filter` produces - otherwise "runs
locally" would quietly mean "runs a different system".
"""

from __future__ import annotations

import pytest
from rag_core.local_parse import parse_text
from rag_core.local_search import LocalSearcher, matches_filter, tokenize
from rag_core.retrieval import (
    build_odata_filter,
    build_search_request,
    extract_filters,
)
from rag_core.schemas import BlockKind, QueryFilters, RetrievalConfig

from .conftest import make_chunk  # noqa: F401  (kept for symmetry)


def doc(doc_id, content, **over):
    d = {
        "id": doc_id, "content": content, "doc_id": "D",
        "company": "Northwind Traders", "ticker": "NWND", "doc_type": "10-K",
        "fiscal_year": 2023, "fiscal_quarter": None, "section_path": "Item 7",
        "page_start": 1, "page_end": 1, "chunk_index": 0,
        "contains_table": False, "source_url": "", "token_count": 10,
    }
    d.update(over)
    return d


@pytest.fixture
def searcher(tmp_path):
    s = LocalSearcher(tmp_path / "idx.json")
    return s


# --------------------------------------------------------------------------
# BM25
# --------------------------------------------------------------------------

async def test_bm25_ranks_the_relevant_document_first(searcher):
    await searcher.upload([
        doc("a", "Gross margin was 69.8% in fiscal year 2023."),
        doc("b", "Currency fluctuations may affect reported results."),
        doc("c", "Total revenue was $211,915 million in fiscal year 2023."),
    ])
    hits = await searcher.search(search_text="gross margin", top=3)
    assert hits[0]["id"] == "a"


async def test_search_returns_azure_shaped_results(searcher):
    await searcher.upload([doc("a", "gross margin improved")])
    hit = (await searcher.search(search_text="margin", top=1))[0]

    assert "@search.score" in hit
    # No local semantic ranker exists, so no rerank score is invented.
    assert hit["@search.reranker_score"] is None
    # The vector is never returned - same as the Azure index config.
    assert "content_vector" not in hit


async def test_no_match_returns_nothing(searcher):
    await searcher.upload([doc("a", "gross margin improved")])
    assert await searcher.search(search_text="zzzz nonexistent", top=5) == []


async def test_index_persists_across_instances(tmp_path):
    a = LocalSearcher(tmp_path / "idx.json")
    await a.upload([doc("a", "gross margin improved")])

    b = LocalSearcher(tmp_path / "idx.json")
    assert b.count == 1
    assert (await b.search(search_text="margin", top=1))[0]["id"] == "a"


async def test_upload_is_idempotent(searcher):
    await searcher.upload([doc("a", "text one")])
    await searcher.upload([doc("a", "text one")])
    assert searcher.count == 1


# --------------------------------------------------------------------------
# Vectors and fusion
# --------------------------------------------------------------------------

async def test_cosine_ranking_with_a_query_vector(searcher):
    await searcher.upload([
        doc("a", "alpha", content_vector=[1.0, 0.0]),
        doc("b", "beta", content_vector=[0.0, 1.0]),
    ])
    hits = await searcher.search(
        vector_queries=[{"vector": [0.9, 0.1], "fields": "content_vector"}], top=2
    )
    assert hits[0]["id"] == "a"


async def test_hybrid_fuses_both_retrievers(searcher):
    await searcher.upload([
        doc("a", "gross margin", content_vector=[0.0, 1.0]),
        doc("b", "unrelated text", content_vector=[1.0, 0.0]),
    ])
    hits = await searcher.search(
        search_text="gross margin",
        vector_queries=[{"vector": [1.0, 0.0], "fields": "content_vector"}],
        top=2,
    )
    # Each retriever wins one document, so both survive fusion.
    assert {h["id"] for h in hits} == {"a", "b"}
    assert hits[0]["@search.bm25_score"] is not None or \
           hits[0]["@search.vector_score"] is not None


# --------------------------------------------------------------------------
# Filters - must understand everything build_odata_filter emits
# --------------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "NWND FY23 gross margin",
    "NWND Q3 2023 revenue",
    "revenue in the annual report",
    "NWND 2022 and 2023 revenue",
])
def test_every_generated_filter_is_understood_locally(query):
    filters = extract_filters(query, ["NWND"])
    odata = build_odata_filter(filters)
    sample = doc("a", "x")
    # Must not raise: the local matcher has to cover the generator's output.
    matches_filter(sample, odata)


def test_filter_excludes_the_wrong_year():
    odata = build_odata_filter(QueryFilters(fiscal_years=[2022]))
    assert not matches_filter(doc("a", "x", fiscal_year=2023), odata)
    assert matches_filter(doc("a", "x", fiscal_year=2022), odata)


def test_filter_excludes_the_wrong_ticker():
    odata = build_odata_filter(QueryFilters(tickers=["ACME"]))
    assert not matches_filter(doc("a", "x"), odata)


def test_combined_filters_are_all_required():
    odata = build_odata_filter(QueryFilters(tickers=["NWND"], fiscal_years=[2022]))
    assert not matches_filter(doc("a", "x", fiscal_year=2023), odata)


def test_unparseable_filter_fails_loudly():
    with pytest.raises(ValueError, match="cannot evaluate"):
        matches_filter(doc("a", "x"), "startswith(company, 'North')")


async def test_filter_is_applied_by_search(searcher):
    await searcher.upload([
        doc("a", "gross margin", fiscal_year=2023),
        doc("b", "gross margin", fiscal_year=2022),
    ])
    odata = build_odata_filter(QueryFilters(fiscal_years=[2022]))
    hits = await searcher.search(search_text="gross margin", filter=odata, top=5)
    assert [h["id"] for h in hits] == ["b"]


async def test_accepts_a_request_built_by_build_search_request(searcher):
    await searcher.upload([doc("a", "gross margin", content_vector=[1.0, 0.0])])
    cfg = RetrievalConfig(id="h", use_bm25=True, use_vector=True,
                          use_semantic_ranker=False)
    request = build_search_request("gross margin", cfg, None, vector=[1.0, 0.0])
    hits = await searcher.search(**request)
    assert hits and hits[0]["id"] == "a"


# --------------------------------------------------------------------------
# Local parser
# --------------------------------------------------------------------------

SAMPLE = """<!-- page: 1 -->

# Annual Report

Intro paragraph one.

<!-- page: 2 -->

## Item 7. MD&A

Revenue grew 7%.

| Segment | FY23 |
| --- | --- |
| Cloud | 87,907 |
"""


def test_parser_extracts_headings_paragraphs_and_pages():
    result = parse_text(SAMPLE, "DOC")
    roles = [p["role"] for p in result["paragraphs"]]

    assert "title" in roles and "sectionHeading" in roles
    assert len(result["pages"]) == 2
    md = next(p for p in result["paragraphs"] if p["content"].startswith("Revenue"))
    assert md["boundingRegions"][0]["pageNumber"] == 2


def test_parser_extracts_markdown_tables_as_structured_cells():
    table = parse_text(SAMPLE, "DOC")["tables"][0]
    assert table["rowCount"] == 2 and table["columnCount"] == 2
    headers = [c for c in table["cells"] if c["kind"] == "columnHeader"]
    assert {c["content"] for c in headers} == {"Segment", "FY23"}


def test_parsed_output_feeds_the_existing_ingest_translation():
    from apps.ingest.pipeline import blocks_from_di

    parsed = blocks_from_di(parse_text(SAMPLE, "DOC"))
    kinds = {b.kind for b in parsed.blocks}
    assert BlockKind.TABLE in kinds and BlockKind.HEADING in kinds

    table = next(b for b in parsed.blocks if b.kind is BlockKind.TABLE)
    assert table.header == ["Segment", "FY23"]
    assert table.rows == [["Cloud", "87,907"]]


def test_tokenizer_keeps_financial_tokens_intact():
    assert "10-k" in tokenize("Form 10-K filing")
    assert "69.8" in tokenize("margin was 69.8%")


# --------------------------------------------------------------------------
# Index schema - validated against the real Azure SDK models
# --------------------------------------------------------------------------

def test_index_builds_against_the_real_sdk_models():
    """Catches schema errors offline, before they cost an Azure round trip.

    The SDK has no SearchIndex.from_dict, so the index must be constructed from
    typed models; this asserts that construction actually works.
    """
    pytest.importorskip("azure.search.documents")
    from rag_core.indexing import build_search_index

    idx = build_search_index("filings", 1536)
    vector_field = next(f for f in idx.fields if f.name == "content_vector")

    assert vector_field.vector_search_dimensions == 1536
    # `hidden` is the SDK spelling of retrievable=false.
    assert vector_field.hidden is True
    assert vector_field.vector_search_profile_name == "hnsw-cosine"
    assert idx.vector_search.algorithms[0].parameters.m == 8
    assert [c.name for c in idx.semantic_search.configurations] == ["default"]


def test_free_tier_index_omits_the_semantic_configuration():
    # The Free tier has no semantic ranker; defining a config there would
    # promise a capability the service cannot serve.
    pytest.importorskip("azure.search.documents")
    from rag_core.indexing import build_search_index

    assert build_search_index("filings", 768, include_semantic=False).semantic_search is None


def test_declared_schema_and_sdk_model_cannot_drift():
    pytest.importorskip("azure.search.documents")
    from rag_core.indexing import build_search_index, index_definition

    declared = {f["name"] for f in index_definition("filings", 1536)["fields"]}
    built = {f.name for f in build_search_index("filings", 1536).fields}
    assert declared == built


def test_every_indexed_document_field_exists_in_the_schema():
    from rag_core.indexing import chunk_to_document, index_definition
    from rag_core.schemas import Chunk, ChunkMetadata

    chunk = Chunk(id="a", content="x", metadata=ChunkMetadata(doc_id="d"))
    doc_fields = set(chunk_to_document(chunk, [0.1, 0.2]))
    schema_fields = {f["name"] for f in index_definition("filings", 2)["fields"]}
    assert doc_fields <= schema_fields, doc_fields - schema_fields
