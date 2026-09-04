from __future__ import annotations

from rag_core.chunking import LayoutChunker, approx_tokens
from rag_core.schemas import ChunkMetadata, ParsedDocument

from .conftest import heading, para, table


def test_chunks_carry_context_header_and_metadata(sample_doc, meta):
    chunks = LayoutChunker(target_tokens=200).chunk(sample_doc, meta)

    assert chunks
    first = chunks[0]
    assert first.content.startswith("[Microsoft Corporation · 10-K · FY2023")
    assert first.metadata.section_path.startswith("Item 7.")
    assert first.metadata.ticker == "MSFT"
    assert first.id == "MSFT-10K-FY23::0000"


def test_section_path_tracks_heading_hierarchy(sample_doc, meta):
    chunks = LayoutChunker(target_tokens=200).chunk(sample_doc, meta)
    paths = {c.metadata.section_path for c in chunks}
    assert any(p.endswith("Segment Results") and ">" in p for p in paths)


def test_table_is_never_split_even_when_over_target(meta):
    rows = [[f"Segment {i}", f"{i},000", f"{i},500"] for i in range(120)]
    doc = ParsedDocument(
        doc_id="D",
        blocks=[heading("Financials", 1, 1), table(["Segment", "FY23", "FY22"], rows, 1, 3)],
    )
    chunks = LayoutChunker(target_tokens=100, overlap_tokens=20).chunk(doc, meta)

    table_chunks = [c for c in chunks if c.metadata.contains_table]
    assert len(table_chunks) == 1
    assert "Segment 0" in table_chunks[0].content
    assert "Segment 119" in table_chunks[0].content


def test_table_chunk_keeps_its_section_heading_for_context(meta):
    doc = ParsedDocument(
        doc_id="D",
        blocks=[heading("Consolidated Balance Sheets", 1, 1),
                table(["Item", "FY23"], [["Total assets", "411,976"]], 1, 1)],
    )
    chunk = LayoutChunker().chunk(doc, meta)[0]
    assert "Consolidated Balance Sheets" in chunk.content
    assert chunk.metadata.contains_table is True


def test_long_prose_splits_on_paragraph_boundaries_with_overlap(meta):
    paras = [para(f"Paragraph {i}. " + "word " * 60, 1) for i in range(8)]
    doc = ParsedDocument(doc_id="D", blocks=[heading("Risk Factors", 1, 1), *paras])
    chunks = LayoutChunker(target_tokens=200, overlap_tokens=60).chunk(doc, meta)

    assert len(chunks) > 1
    # Overlap means some paragraph text is shared between neighbours.
    a = set(chunks[0].content.split("\n\n"))
    b = set(chunks[1].content.split("\n\n"))
    assert a & b, "expected overlapping paragraphs between adjacent chunks"


def test_no_chunk_exceeds_the_semantic_ranker_read_window(meta):
    # The ranker reads ~2000 tokens; anything above is silently truncated.
    giant = para("word " * 9000, 1)
    doc = ParsedDocument(doc_id="D", blocks=[heading("H", 1, 1), giant])
    chunker = LayoutChunker(target_tokens=600, overlap_tokens=80, max_tokens=2000)
    chunks = chunker.chunk(doc, meta)

    assert chunks
    assert all(approx_tokens(c.content) <= 2400 for c in chunks)


def test_chunk_indices_are_contiguous(sample_doc, meta):
    chunks = LayoutChunker(target_tokens=120).chunk(sample_doc, meta)
    assert [c.metadata.chunk_index for c in chunks] == list(range(len(chunks)))


def test_empty_document_yields_no_chunks(meta):
    assert LayoutChunker().chunk(ParsedDocument(doc_id="D", blocks=[]), meta) == []


def test_overlap_must_be_smaller_than_target():
    import pytest

    with pytest.raises(ValueError):
        LayoutChunker(target_tokens=100, overlap_tokens=100)


def test_context_header_without_period_or_company():
    from rag_core.schemas import Chunk

    c = Chunk(id="x", content="", metadata=ChunkMetadata(doc_id="d", section_path="Notes"))
    # An unknown doc type is the absence of information, so it is omitted
    # rather than printed as the literal word "unknown".
    assert c.context_header() == "Notes"
