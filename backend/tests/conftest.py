from __future__ import annotations

import pytest
from rag_core.schemas import (
    Block,
    BlockKind,
    Chunk,
    ChunkMetadata,
    Citation,
    DocType,
    GoldenQuestion,
    ParsedDocument,
    QuestionType,
    ScoredChunk,
    Trace,
)


@pytest.fixture
def meta() -> ChunkMetadata:
    return ChunkMetadata(
        doc_id="MSFT-10K-FY23",
        company="Microsoft Corporation",
        ticker="MSFT",
        doc_type=DocType.TEN_K,
        fiscal_year=2023,
        source_url="https://example.test/msft-10k-fy23.pdf",
    )


def heading(text: str, level: int = 1, page: int = 1) -> Block:
    return Block(kind=BlockKind.HEADING, text=text, level=level,
                 page_start=page, page_end=page)


def para(text: str, page: int = 1) -> Block:
    return Block(kind=BlockKind.PARAGRAPH, text=text, page_start=page, page_end=page)


def table(header, rows, page_start=1, page_end=1) -> Block:
    return Block(kind=BlockKind.TABLE, header=header, rows=rows,
                 page_start=page_start, page_end=page_end)


@pytest.fixture
def sample_doc() -> ParsedDocument:
    return ParsedDocument(
        doc_id="MSFT-10K-FY23",
        page_count=3,
        blocks=[
            heading("Item 7. Management's Discussion and Analysis", 1, 1),
            para("Revenue increased 12% driven by cloud services.", 1),
            heading("Segment Results", 2, 2),
            para("Intelligent Cloud revenue grew 17%.", 2),
            table(
                ["Segment", "FY23", "FY22"],
                [["Productivity", "69,274", "63,364"],
                 ["Intelligent Cloud", "87,907", "74,965"]],
                page_start=2, page_end=2,
            ),
        ],
    )


def make_chunk(chunk_id: str, content: str, meta: ChunkMetadata) -> Chunk:
    return Chunk(id=chunk_id, content=content, metadata=meta)


@pytest.fixture
def context_chunks(meta: ChunkMetadata) -> list[Chunk]:
    return [
        make_chunk(
            "MSFT-10K-FY23::0001",
            "Gross margin was 69.8% in fiscal year 2023, compared with 68.4% in fiscal year 2022.",
            meta,
        ),
        make_chunk(
            "MSFT-10K-FY23::0002",
            "Intelligent Cloud revenue was $87,907 million in FY23.",
            meta,
        ),
    ]


def make_trace(
    answer: str = "",
    citations: list[Citation] | None = None,
    refused: bool = False,
    retrieved: list[Chunk] | None = None,
    config_id: str = "hybrid_semantic",
) -> Trace:
    return Trace(
        id="trace-1",
        config_id=config_id,
        query="q",
        answer=answer,
        citations=citations or [],
        refused=refused,
        retrieved=[ScoredChunk(chunk=c, rrf_score=1.0) for c in (retrieved or [])],
    )


@pytest.fixture
def question() -> GoldenQuestion:
    return GoldenQuestion(
        id="Q-041",
        question="How did gross margin change between FY22 and FY23?",
        gold_answer="Gross margin rose from 68.4% in FY22 to 69.8% in FY23, up 140 basis points.",
        gold_chunk_ids=["MSFT-10K-FY23::0001"],
        q_type=QuestionType.MULTI_HOP,
        answerable=True,
        expected_fiscal_year=2023,
    )
