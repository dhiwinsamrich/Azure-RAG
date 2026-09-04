"""Core library shared by the API, the ingest job and the evaluator.

Pure logic only - nothing in this package's top level imports an Azure SDK, so
the test suite runs with no cloud account. Azure clients live in `clients.py`
and are imported by the apps, not by the algorithms.
"""

from .schemas import (  # noqa: F401
    Block,
    BlockKind,
    Chunk,
    ChunkMetadata,
    Citation,
    CitationVerdict,
    DocType,
    EvalResult,
    EvalRun,
    GoldenQuestion,
    MetricValue,
    ModelAnswer,
    ParsedDocument,
    QueryFilters,
    QuestionType,
    RetrievalConfig,
    ScoredChunk,
    Trace,
    ValidatedAnswer,
)

__all__ = [n for n in dir() if not n.startswith("_")]
