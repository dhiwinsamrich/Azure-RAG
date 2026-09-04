from __future__ import annotations

import pytest
from rag_core.schemas import BlockKind, DocType

from apps.ingest.pipeline import IngestPipeline, blocks_from_di, infer_metadata

DI_RESULT = {
    "doc_id": "MSFT-10K-FY23",
    "pages": [{"pageNumber": 1}, {"pageNumber": 2}],
    "paragraphs": [
        {"role": "title", "content": "Annual Report on Form 10-K",
         "boundingRegions": [{"pageNumber": 1}]},
        {"role": None, "content": "For the fiscal year ended June 30, 2023",
         "boundingRegions": [{"pageNumber": 1}]},
        {"role": "sectionHeading", "content": "Item 7. MD&A",
         "boundingRegions": [{"pageNumber": 2}]},
        {"role": None, "content": "Revenue increased 7%.",
         "boundingRegions": [{"pageNumber": 2}]},
    ],
    "tables": [{
        "rowCount": 2, "columnCount": 2,
        "boundingRegions": [{"pageNumber": 2}],
        "cells": [
            {"rowIndex": 0, "columnIndex": 0, "content": "Segment", "kind": "columnHeader"},
            {"rowIndex": 0, "columnIndex": 1, "content": "FY23", "kind": "columnHeader"},
            {"rowIndex": 1, "columnIndex": 0, "content": "Cloud"},
            {"rowIndex": 1, "columnIndex": 1, "content": "87,907"},
        ],
    }],
}


def test_di_paragraphs_become_headings_and_prose():
    doc = blocks_from_di(DI_RESULT)
    kinds = [b.kind for b in doc.blocks]
    assert BlockKind.HEADING in kinds and BlockKind.PARAGRAPH in kinds
    assert doc.page_count == 2


def test_di_table_cells_become_a_structured_table():
    table = next(b for b in blocks_from_di(DI_RESULT).blocks if b.kind is BlockKind.TABLE)
    assert table.header == ["Segment", "FY23"]
    assert table.rows == [["Cloud", "87,907"]]


def test_metadata_inferred_from_cover_page():
    meta = infer_metadata("MSFT-10K-FY23", "Annual Report on Form 10-K for the fiscal year ended June 30, 2023")
    assert meta.doc_type is DocType.TEN_K
    assert meta.fiscal_year == 2023
    assert meta.ticker == "MSFT"


class FakeParser:
    def __init__(self):
        self.calls = 0

    async def analyze(self, content):
        self.calls += 1
        return dict(DI_RESULT)


class FakeEmbedder:
    async def embed(self, texts):
        return [[0.1, 0.2] for _ in texts]


class FakeSearcher:
    def __init__(self):
        self.uploaded = []

    async def upload(self, documents):
        self.uploaded.extend(documents)
        return len(documents)


@pytest.fixture
def pipeline(tmp_path):
    return IngestPipeline(FakeParser(), FakeEmbedder(), FakeSearcher(), cache_dir=tmp_path)


async def test_ingest_produces_indexed_chunks(pipeline):
    result = await pipeline.ingest("MSFT-10K-FY23", b"pdf-bytes")
    assert not result.errors
    assert result.chunks > 0
    assert result.indexed == result.chunks
    assert not result.from_cache


async def test_second_run_uses_the_parsed_cache(pipeline):
    await pipeline.ingest("MSFT-10K-FY23", b"pdf-bytes")
    second = await pipeline.ingest("MSFT-10K-FY23", b"pdf-bytes")

    assert second.from_cache
    assert pipeline.parser.calls == 1, "parsing must not be repeated"


async def test_indexed_documents_omit_nothing_the_index_needs(pipeline):
    await pipeline.ingest("MSFT-10K-FY23", b"pdf-bytes")
    doc = pipeline.searcher.uploaded[0]
    for field in ("id", "content", "content_vector", "doc_id", "ticker",
                  "doc_type", "fiscal_year", "contains_table", "page_start"):
        assert field in doc


async def test_parse_failure_is_reported_not_raised(tmp_path):
    class Broken:
        async def analyze(self, content):
            raise RuntimeError("service unavailable")

    p = IngestPipeline(Broken(), FakeEmbedder(), FakeSearcher(), cache_dir=tmp_path)
    result = await p.ingest("D", b"x")
    assert result.errors and "parse failed" in result.errors[0]
    assert result.indexed == 0
