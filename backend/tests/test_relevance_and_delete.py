"""The financial-document gate, and deletion that actually removes chunks."""

from __future__ import annotations

from rag_core import relevance
from rag_core.local_search import LocalSearcher

FILING = """
Annual Report on Form 10-K for the fiscal year ended June 30, 2023.

Total revenue was $211,915 million in fiscal year 2023, an increase of 7%.
Gross margin was 69.8%, an improvement of approximately 140 basis points.

Consolidated Balance Sheets show total assets of $411,976 million and total
stockholders' equity of $206,223 million. Management's discussion follows.
"""

RESUME = """
AI ML Engineer Resume Analysis and Targeting Guide.

The current resume is strong for a one-year GenAI profile, especially around
LLM application development, RAG, LangGraph, multi-agent systems, routing and
failover, NLP classification, LoRA and PEFT, FastAPI, Redis, Celery, Docker,
RBAC, audit logging and production reliability. The target role is more
specialised and expects two major competency areas that are not yet evidenced
anywhere in the document as written today.
"""

RECIPE = """
Slow roasted tomato soup for a winter evening. Halve the tomatoes, scatter
over the garlic and thyme, and roast until the edges catch. Blend with stock,
season generously, and finish with cream. Serve with bread. This makes enough
for four people and keeps in the fridge for three days without losing much.
"""


# --------------------------------------------------------------------------
# Accepting real filings
# --------------------------------------------------------------------------

def test_a_filing_is_accepted():
    v = relevance.assess(FILING, "MSFT-10K-FY23")
    assert v.accepted
    assert v.score > 0.5
    assert "financial statements" in v.matched
    assert "fiscal period" in v.matched


def test_the_reason_names_the_matched_categories():
    v = relevance.assess(FILING, "MSFT-10K-FY23")
    assert "financial statements" in v.reason


# --------------------------------------------------------------------------
# Rejecting everything else
# --------------------------------------------------------------------------

def test_a_resume_is_rejected():
    v = relevance.assess(RESUME, "AI_ML_Engineer_Resume_Analysis")
    assert not v.accepted
    assert v.missing


def test_unrelated_prose_is_rejected():
    assert not relevance.assess(RECIPE, "tomato-soup").accepted


def test_rejection_explains_what_was_missing():
    v = relevance.assess(RECIPE, "tomato-soup")
    assert "Missing:" in v.reason and "financial statements" in v.reason


def test_a_filing_name_alone_cannot_carry_a_document():
    # The filename is evidence, never sufficient evidence.
    v = relevance.assess(RECIPE, "MSFT-10K-FY23-annual-report-form-10-K")
    assert not v.accepted


def test_short_documents_are_refused_rather_than_guessed_at():
    v = relevance.assess("Revenue was up.", "x")
    assert not v.accepted
    assert "too short" in v.reason


def test_a_resume_matches_no_category_at_all():
    # Not merely below the bar - it carries no financial evidence whatsoever.
    assert relevance.assess(RESUME, "r").matched == {}


def test_threshold_is_configurable():
    # One category only: metrics, with no statements, period or amounts.
    one_category = (
        "Our revenue model is described at length below. " * 6
        + "The team discusses revenue in weekly planning sessions and the "
        "revenue conversation shapes the roadmap for the coming half."
    )
    lenient = relevance.assess(one_category, "notes", min_categories=1)
    strict = relevance.assess(one_category, "notes", min_categories=3)

    assert lenient.accepted
    assert not strict.accepted
    assert lenient.matched_categories == ["financial metrics"]


def test_repeating_one_term_does_not_pass_the_gate():
    # Categories, not keyword counts: 40 mentions of revenue is one category.
    v = relevance.assess("revenue " * 200, "spam")
    assert not v.accepted
    assert v.matched_categories == ["financial metrics"]


def test_sample_text_reads_paragraphs_and_tables():
    parsed = {
        "paragraphs": [{"content": "Total revenue was"}],
        "tables": [{"cells": [{"content": "211,915"}, {"content": "Segment"}]}],
    }
    text = relevance.sample_text(parsed)
    assert "Total revenue was" in text and "211,915" in text


# --------------------------------------------------------------------------
# Deletion removes chunks from the index, not just the store
# --------------------------------------------------------------------------

def doc(chunk_id: str, doc_id: str, content: str, **over):
    d = {
        "id": chunk_id, "content": content, "doc_id": doc_id,
        "company": "", "ticker": "", "doc_type": "10-K", "fiscal_year": 2023,
        "fiscal_quarter": None, "section_path": "", "page_start": 1,
        "page_end": 1, "chunk_index": 0, "contains_table": False,
        "source_url": "", "token_count": 5,
    }
    d.update(over)
    return d


async def test_delete_removes_every_chunk_of_the_document(tmp_path):
    s = LocalSearcher(tmp_path / "idx.json")
    await s.upload([
        doc("A::0", "A", "revenue", content_vector=[0.1, 0.2]),
        doc("A::1", "A", "margin", content_vector=[0.3, 0.4]),
        doc("B::0", "B", "revenue", content_vector=[0.5, 0.6]),
    ])

    removed = await s.delete_document("A")
    assert removed == 2
    assert s.count == 1
    assert [d["doc_id"] for d in s.list_documents()] == ["B"]


async def test_deleted_chunks_stop_being_retrievable(tmp_path):
    s = LocalSearcher(tmp_path / "idx.json")
    await s.upload([doc("A::0", "A", "unique-token-here"), doc("B::0", "B", "other")])

    assert await s.search(search_text="unique-token-here", top=5)
    await s.delete_document("A")
    assert await s.search(search_text="unique-token-here", top=5) == []


async def test_delete_persists_across_reload(tmp_path):
    s = LocalSearcher(tmp_path / "idx.json")
    await s.upload([doc("A::0", "A", "x"), doc("B::0", "B", "y")])
    await s.delete_document("A")

    assert LocalSearcher(tmp_path / "idx.json").count == 1


async def test_deleting_an_unknown_document_is_a_no_op(tmp_path):
    s = LocalSearcher(tmp_path / "idx.json")
    await s.upload([doc("A::0", "A", "x")])
    assert await s.delete_document("NOPE") == 0
    assert s.count == 1


# --------------------------------------------------------------------------
# The local index must not be served stale
# --------------------------------------------------------------------------

async def test_a_second_instance_sees_writes_from_the_first(tmp_path):
    """An in-memory index held by two objects would serve deleted chunks.

    This is exactly what happened: DELETE mutated one LocalSearcher while the
    API's pipeline kept answering from another.
    """
    path = tmp_path / "idx.json"
    writer = LocalSearcher(path)
    reader = LocalSearcher(path)

    await writer.upload([doc("A::0", "A", "unique-token")])
    assert await reader.search(search_text="unique-token", top=5)

    await writer.delete_document("A")
    assert await reader.search(search_text="unique-token", top=5) == []


async def test_reader_picks_up_documents_added_by_another_process(tmp_path):
    path = tmp_path / "idx.json"
    reader = LocalSearcher(path)
    assert reader.count == 0

    # Stands in for the ingest CLI writing the index from its own process.
    await LocalSearcher(path).upload([doc("B::0", "B", "later-added")])

    assert await reader.search(search_text="later-added", top=5)
    assert [d["doc_id"] for d in reader.list_documents()] == ["B"]


def test_build_searcher_shares_one_local_instance(tmp_path):
    from rag_core.clients import build_searcher
    from rag_core.config import Settings

    s = Settings(
        _env_file=None, search_backend="local",
        local_index_path=str(tmp_path / "shared.json"),
    )
    assert build_searcher(s) is build_searcher(s)
