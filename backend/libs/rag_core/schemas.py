"""Data contracts shared by the API, the ingest job and the evaluator.

These models are the single definition of a chunk, a citation and a trace.
Everything downstream - the search index schema, the SSE payloads, the eval
store - is derived from them rather than restating them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DocType(StrEnum):
    TEN_K = "10-K"
    TEN_Q = "10-Q"
    MANAGER_LETTER = "manager-letter"
    PROSPECTUS = "prospectus"
    PRESS_RELEASE = "press-release"
    UNKNOWN = "unknown"


class QuestionType(StrEnum):
    SINGLE_FACT = "single-fact"
    MULTI_HOP = "multi-hop"
    TABLE = "table-dependent"
    UNANSWERABLE = "unanswerable"


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"


class Block(BaseModel):
    """One unit emitted by the layout parser, in document order."""

    kind: BlockKind
    text: str = ""
    level: int = 0
    page_start: int = 1
    page_end: int = 1

    # Table-only fields.
    header: list[str] | None = None
    rows: list[list[str]] | None = None

    @property
    def n_cols(self) -> int:
        if self.header:
            return len(self.header)
        if self.rows:
            return max(len(r) for r in self.rows)
        return 0


class ParsedDocument(BaseModel):
    doc_id: str
    blocks: list[Block] = Field(default_factory=list)
    page_count: int = 0


# --------------------------------------------------------------------------
# Chunks
# --------------------------------------------------------------------------

class ChunkMetadata(BaseModel):
    doc_id: str
    company: str = ""
    ticker: str = ""
    doc_type: DocType = DocType.UNKNOWN
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    section_path: str = ""
    page_start: int = 1
    page_end: int = 1
    chunk_index: int = 0
    contains_table: bool = False
    source_url: str = ""


class Chunk(BaseModel):
    id: str
    content: str
    metadata: ChunkMetadata
    token_count: int = 0

    def context_header(self) -> str:
        """The prefix that keeps a small chunk interpretable on its own.

        Without it, "revenue increased 12%" is unusable - whose revenue, when?
        """
        m = self.metadata
        doc_type = "" if m.doc_type is DocType.UNKNOWN else m.doc_type.value
        parts = [p for p in (m.company or m.ticker, doc_type, _period(m)) if p]
        if m.section_path:
            parts.append(m.section_path)
        return " · ".join(parts)


def _period(m: ChunkMetadata) -> str:
    if m.fiscal_year and m.fiscal_quarter:
        return f"FY{m.fiscal_year} Q{m.fiscal_quarter}"
    if m.fiscal_year:
        return f"FY{m.fiscal_year}"
    return ""


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------

class RetrievalConfig(BaseModel):
    """The ablation axis. Every trace and eval result references one of these.

    Comparing two retrieval strategies is then a group-by rather than a
    bookkeeping exercise.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str = ""
    chunk_size: int = 650
    chunk_overlap: int = 100
    top_k: int = 10
    rerank_top_n: int = 8
    use_bm25: bool = True
    use_vector: bool = True
    use_semantic_ranker: bool = True
    # Recorded per ablation arm so a result is always attributable to the
    # models that produced it - swapping provider is itself an ablation.
    embed_model: str = "gemini-embedding-001"
    embed_dims: int = 1536
    gen_model: str = "gemini-3.8-flash"
    prompt_version: str = "v1"

    def label(self) -> str:
        return self.name or self.id


class ScoredChunk(BaseModel):
    """A retrieval candidate carrying where it came from.

    Per-retriever ranks are kept so the debug UI can show exactly where a chunk
    gained or lost position, which is the fastest way to explain a bad answer.
    """

    chunk: Chunk
    bm25_rank: int | None = None
    vector_rank: int | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None

    @property
    def score(self) -> float:
        if self.rerank_score is not None:
            return self.rerank_score
        return self.rrf_score or 0.0


class QueryFilters(BaseModel):
    # Explicit scope chosen by the caller. Unlike the fields below it is never
    # inferred from the question - an unrelated document in the index answering
    # a financial query is a retrieval failure, not something to guess at.
    doc_ids: list[str] = Field(default_factory=list)

    companies: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)
    doc_types: list[str] = Field(default_factory=list)
    fiscal_years: list[int] = Field(default_factory=list)
    fiscal_quarters: list[int] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            (self.doc_ids, self.companies, self.tickers, self.doc_types,
             self.fiscal_years, self.fiscal_quarters)
        )


# --------------------------------------------------------------------------
# Generation and citations
# --------------------------------------------------------------------------

class Citation(BaseModel):
    chunk_id: str
    quoted_span: str


class CitationVerdict(BaseModel):
    chunk_id: str
    quoted_span: str
    valid: bool
    reason: Literal["ok", "unknown_chunk", "span_not_found"] = "ok"


class ModelAnswer(BaseModel):
    """Structured output requested from the model - never parsed out of prose."""

    answer: str
    citations: list[Citation] = Field(default_factory=list)
    refused: bool = False


class ValidatedAnswer(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    verdicts: list[CitationVerdict] = Field(default_factory=list)
    refused: bool = False

    @property
    def citation_validity(self) -> float:
        if not self.verdicts:
            return 1.0
        return sum(v.valid for v in self.verdicts) / len(self.verdicts)

    @property
    def failures(self) -> int:
        return sum(not v.valid for v in self.verdicts)


# --------------------------------------------------------------------------
# Tracing
# --------------------------------------------------------------------------

class StageTimings(BaseModel):
    filter_ms: float = 0.0
    retrieval_ms: float = 0.0
    rerank_ms: float = 0.0
    generation_ms: float = 0.0
    validation_ms: float = 0.0

    @property
    def total_ms(self) -> float:
        return (self.filter_ms + self.retrieval_ms + self.rerank_ms
                + self.generation_ms + self.validation_ms)


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    embedding_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens + self.embedding_tokens


class Trace(BaseModel):
    """One answered query. Offline eval, online eval, the debug UI and App
    Insights all read this same object."""

    id: str
    config_id: str
    query: str
    filters: QueryFilters = Field(default_factory=QueryFilters)
    retrieved: list[ScoredChunk] = Field(default_factory=list)
    answer: str = ""
    citations: list[Citation] = Field(default_factory=list)
    verdicts: list[CitationVerdict] = Field(default_factory=list)
    refused: bool = False
    timings: StageTimings = Field(default_factory=StageTimings)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    estimated_cost_usd: float = 0.0
    model_deployment: str = ""
    created_at: datetime = Field(default_factory=_utcnow)

    def contexts(self) -> list[str]:
        return [s.chunk.content for s in self.retrieved]

    def retrieved_ids(self) -> list[str]:
        return [s.chunk.id for s in self.retrieved]


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

class GoldenQuestion(BaseModel):
    id: str
    question: str
    gold_answer: str = ""
    gold_chunk_ids: list[str] = Field(default_factory=list)
    q_type: QuestionType = QuestionType.SINGLE_FACT
    answerable: bool = True
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    provenance: Literal["human", "synthetic"] = "human"
    expected_fiscal_year: int | None = None
    expected_values: list[str] = Field(default_factory=list)


class MetricValue(BaseModel):
    metric_name: str
    value: float | None = None
    reason: str = ""
    judge_tokens: int = 0


class EvalResult(BaseModel):
    question_id: str
    trace_id: str = ""
    metrics: list[MetricValue] = Field(default_factory=list)

    def get(self, name: str) -> float | None:
        for m in self.metrics:
            if m.metric_name == name:
                return m.value
        return None


class EvalRun(BaseModel):
    id: str
    config_id: str
    question_set: str = "golden"
    metric_set: list[str] = Field(default_factory=list)
    judge_model: str = ""
    trigger: Literal["manual", "nightly", "ci-gate", "online"] = "manual"
    started_at: datetime = Field(default_factory=_utcnow)
    status: Literal["running", "complete", "failed"] = "running"
    results: list[EvalResult] = Field(default_factory=list)

    def aggregate(self) -> dict[str, float]:
        """Mean per metric, ignoring questions where the metric is undefined."""
        buckets: dict[str, list[float]] = {}
        for r in self.results:
            for m in r.metrics:
                if m.value is not None:
                    buckets.setdefault(m.metric_name, []).append(m.value)
        return {k: sum(v) / len(v) for k, v in buckets.items() if v}

    def aggregate_by_type(
        self, questions: dict[str, GoldenQuestion]
    ) -> dict[str, dict[str, float]]:
        """Mean per metric per question type.

        The headline mean routinely hides a whole segment - table-dependent
        questions are usually the worst and the most interesting.
        """
        buckets: dict[str, dict[str, list[float]]] = {}
        for r in self.results:
            q = questions.get(r.question_id)
            if q is None:
                continue
            seg = buckets.setdefault(q.q_type.value, {})
            for m in r.metrics:
                if m.value is not None:
                    seg.setdefault(m.metric_name, []).append(m.value)
        return {
            t: {k: sum(v) / len(v) for k, v in metrics.items() if v}
            for t, metrics in buckets.items()
        }


class GateThreshold(BaseModel):
    metric: str
    min_value: float | None = None
    max_drop_vs_baseline: float | None = None


class GateOutcome(BaseModel):
    passed: bool
    failures: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
