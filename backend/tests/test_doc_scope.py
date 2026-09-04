"""Explicit document scoping.

Without it every indexed document competes for every question: a resume in the
index answered "revenue" alongside two 10-Ks, which is a retrieval failure the
ranker cannot fix.
"""

from __future__ import annotations

import pytest
from rag_core.local_search import LocalSearcher, matches_filter
from rag_core.retrieval import build_odata_filter, extract_filters
from rag_core.schemas import QueryFilters


def doc(chunk_id: str, doc_id: str, content: str, **over):
    d = {
        "id": chunk_id, "content": content, "doc_id": doc_id,
        "company": "", "ticker": "", "doc_type": "10-K",
        "fiscal_year": 2023, "fiscal_quarter": None, "section_path": "Item 7",
        "page_start": 1, "page_end": 1, "chunk_index": 0,
        "contains_table": False, "source_url": "", "token_count": 10,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------
# Filter construction
# --------------------------------------------------------------------------

def test_doc_ids_render_into_the_odata_filter():
    odata = build_odata_filter(QueryFilters(doc_ids=["MSFT-10K-FY23"]))
    assert "search.in(doc_id, 'MSFT-10K-FY23', '|')" in odata


def test_scope_uses_a_pipe_separator_so_ids_may_contain_commas():
    odata = build_odata_filter(QueryFilters(doc_ids=["A,B", "C"]))
    assert "'A,B|C'" in odata


def test_scope_combines_with_inferred_filters():
    f = extract_filters("FY23 revenue", [])
    f = f.model_copy(update={"doc_ids": ["DOC-1"]})
    odata = build_odata_filter(f)
    assert "doc_id" in odata and "fiscal_year eq 2023" in odata and " and " in odata


def test_empty_scope_adds_no_clause():
    assert build_odata_filter(QueryFilters()) is None


def test_scope_is_never_inferred_from_the_question():
    # Only the caller sets scope; guessing it from text would be a silent
    # restriction the user never asked for.
    assert extract_filters("tell me about MSFT-10K-FY23", []).doc_ids == []


# --------------------------------------------------------------------------
# Enforcement
# --------------------------------------------------------------------------

def test_local_matcher_understands_the_scope_clause():
    odata = build_odata_filter(QueryFilters(doc_ids=["KEEP"]))
    assert matches_filter(doc("KEEP::0", "KEEP", "x"), odata)
    assert not matches_filter(doc("DROP::0", "DROP", "x"), odata)


async def test_search_returns_only_scoped_documents(tmp_path):
    s = LocalSearcher(tmp_path / "idx.json")
    await s.upload([
        doc("FILING::0", "FILING", "total revenue was 211,915 million"),
        doc("RESUME::0", "RESUME", "revenue experience on the resume"),
    ])

    odata = build_odata_filter(QueryFilters(doc_ids=["FILING"]))
    hits = await s.search(search_text="revenue", filter=odata, top=10)
    assert [h["doc_id"] for h in hits] == ["FILING"]


async def test_without_scope_every_document_competes(tmp_path):
    s = LocalSearcher(tmp_path / "idx.json")
    await s.upload([
        doc("FILING::0", "FILING", "total revenue was 211,915 million"),
        doc("RESUME::0", "RESUME", "revenue experience on the resume"),
    ])
    hits = await s.search(search_text="revenue", top=10)
    assert {h["doc_id"] for h in hits} == {"FILING", "RESUME"}


async def test_multiple_documents_can_be_scoped_together(tmp_path):
    s = LocalSearcher(tmp_path / "idx.json")
    await s.upload([
        doc("A::0", "A", "revenue"), doc("B::0", "B", "revenue"),
        doc("C::0", "C", "revenue"),
    ])
    odata = build_odata_filter(QueryFilters(doc_ids=["A", "C"]))
    hits = await s.search(search_text="revenue", filter=odata, top=10)
    assert sorted(h["doc_id"] for h in hits) == ["A", "C"]


# --------------------------------------------------------------------------
# Listing what can be scoped
# --------------------------------------------------------------------------

async def test_list_documents_groups_chunks_by_document(tmp_path):
    s = LocalSearcher(tmp_path / "idx.json")
    await s.upload([
        doc("A::0", "A", "one"), doc("A::1", "A", "two"),
        doc("B::0", "B", "three", content_vector=[0.1, 0.2]),
    ])
    docs = {d["doc_id"]: d for d in s.list_documents()}

    assert docs["A"]["chunk_count"] == 2
    assert docs["B"]["chunk_count"] == 1
    # Whether a document is embedded decides if vector search can reach it.
    assert docs["A"]["has_vectors"] is False
    assert docs["B"]["has_vectors"] is True


async def test_list_documents_is_empty_for_an_empty_index(tmp_path):
    assert LocalSearcher(tmp_path / "idx.json").list_documents() == []


# --------------------------------------------------------------------------
# Pipeline honours an explicit scope
# --------------------------------------------------------------------------

@pytest.fixture
def scoped_pipeline():
    import json

    from rag_core.pipeline import RagPipeline

    class Searcher:
        def __init__(self):
            self.last = None

        async def search(self, **kwargs):
            self.last = kwargs
            return []

    class Chat:
        async def complete(self, messages, schema=None):
            return json.dumps({"answer": "", "citations": [], "refused": True}), 1, 1

    class Embedder:
        async def embed(self, texts):
            return [[0.1] for _ in texts]

    searcher = Searcher()
    return searcher, RagPipeline(searcher=searcher, embedder=Embedder(), chat=Chat())


async def test_pipeline_applies_the_caller_scope(scoped_pipeline):
    from rag_core.config import BUILTIN_CONFIGS

    searcher, pipeline = scoped_pipeline
    trace = await pipeline.answer(
        "revenue", BUILTIN_CONFIGS["bm25_only"], doc_ids=["ONLY-THIS"]
    )
    assert "search.in(doc_id, 'ONLY-THIS', '|')" in searcher.last["filter"]
    assert trace.filters.doc_ids == ["ONLY-THIS"]


async def test_pipeline_without_scope_sends_no_doc_filter(scoped_pipeline):
    from rag_core.config import BUILTIN_CONFIGS

    searcher, pipeline = scoped_pipeline
    await pipeline.answer("revenue", BUILTIN_CONFIGS["bm25_only"])
    assert "doc_id" not in (searcher.last.get("filter") or "")
