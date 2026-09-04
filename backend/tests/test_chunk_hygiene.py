"""Guards against junk reaching the index.

Every one of these came from looking at a real uploaded document in the corpus
viewer, where a chunk whose entire body was "---" sat next to a context header
reading "AI · unknown".
"""

from __future__ import annotations

import pytest
from rag_core.chunking import LayoutChunker
from rag_core.local_parse import parse_text
from rag_core.schemas import Chunk, ChunkMetadata, DocType, ParsedDocument

from apps.ingest.pipeline import infer_metadata

from .conftest import heading, para

# --------------------------------------------------------------------------
# Thematic breaks are not content
# --------------------------------------------------------------------------

@pytest.mark.parametrize("rule", ["---", "***", "___", "- - -", "-----"])
def test_horizontal_rules_never_become_paragraphs(rule):
    parsed = parse_text(f"# Title\n\nReal text.\n\n{rule}\n\nMore text.\n", "D")
    bodies = [p["content"] for p in parsed["paragraphs"]]
    assert all(b.strip(" -*_") for b in bodies), bodies


@pytest.mark.parametrize("text", ["--", "-", "text", "| a | b |", "-*_"])
def test_ordinary_lines_are_not_mistaken_for_rules(text):
    parsed = parse_text(f"# T\n\n{text}\n", "D")
    joined = " ".join(p["content"] for p in parsed["paragraphs"])
    assert text.strip() in joined or text.startswith("|")


def test_a_document_of_rules_yields_no_junk_chunks(meta):
    parsed = parse_text("# Title\n\n---\n\n***\n\n___\n", "D")
    assert [p["content"] for p in parsed["paragraphs"]] == ["Title"]


# --------------------------------------------------------------------------
# The chunker drops content-free pieces
# --------------------------------------------------------------------------

def test_punctuation_only_block_is_not_emitted_as_a_chunk(meta):
    doc = ParsedDocument(
        doc_id="D",
        blocks=[heading("Section", 1, 1), para("---", 1), para("Real content here.", 1)],
    )
    chunks = LayoutChunker().chunk(doc, meta)
    for c in chunks:
        body = c.content.split("\n\n", 1)[-1]
        assert any(ch.isalnum() for ch in body), f"content-free chunk: {body!r}"


def test_chunk_indices_stay_contiguous_after_dropping(meta):
    doc = ParsedDocument(
        doc_id="D",
        blocks=[heading("S", 1, 1), para("---", 1), para("Alpha.", 1), para("Beta.", 1)],
    )
    chunks = LayoutChunker(target_tokens=5, overlap_tokens=1).chunk(doc, meta)
    assert [c.metadata.chunk_index for c in chunks] == list(range(len(chunks)))


# --------------------------------------------------------------------------
# Metadata inference must not invent a ticker
# --------------------------------------------------------------------------

def test_non_filing_filename_yields_no_ticker():
    # "AI_ML_Engineer_Resume" previously produced the ticker "AI".
    m = infer_metadata("AI_ML_Engineer_Resume_and_Targeting_Guide", "A resume guide.")
    assert m.ticker == ""
    assert m.doc_type is DocType.UNKNOWN


@pytest.mark.parametrize("doc_id", ["MSFT-10K-FY23", "AAPL_10Q_Q3", "NWND-FY2022"])
def test_real_filing_ids_still_yield_a_ticker(doc_id):
    assert infer_metadata(doc_id, "Annual report").ticker != ""


# --------------------------------------------------------------------------
# "unknown" is the absence of a doc type, not a label
# --------------------------------------------------------------------------

def test_context_header_omits_unknown_doc_type():
    c = Chunk(
        id="x", content="",
        metadata=ChunkMetadata(doc_id="d", section_path="2. Match Against the Target Role"),
    )
    header = c.context_header()
    assert "unknown" not in header
    assert header == "2. Match Against the Target Role"


def test_context_header_still_shows_a_known_doc_type():
    c = Chunk(
        id="x", content="",
        metadata=ChunkMetadata(doc_id="d", ticker="MSFT", doc_type=DocType.TEN_K,
                               fiscal_year=2023, section_path="Item 7"),
    )
    assert c.context_header() == "MSFT · 10-K · FY2023 · Item 7"
