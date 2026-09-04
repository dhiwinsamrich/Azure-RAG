"""Ingestion: blob -> Document Intelligence -> chunk -> embed -> index.

Two properties matter more than throughput:

  * Resumable. Parsing is the slow, billed, non-deterministic step, so its
    output is persisted to the parsed cache BEFORE chunking. A failure halfway
    through a 200-document corpus resumes rather than restarting, and a chunker
    change re-embeds from cache without re-parsing anything.
  * Idempotent. Documents are keyed by a deterministic chunk id and uploaded
    with merge-or-upload, so re-running over the same corpus is a no-op.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rag_core.chunking import LayoutChunker
from rag_core.config import Settings, get_settings
from rag_core.indexing import chunk_to_document
from rag_core.schemas import (
    Block,
    BlockKind,
    Chunk,
    ChunkMetadata,
    DocType,
    ParsedDocument,
)

# --------------------------------------------------------------------------
# Document Intelligence result -> our block model
# --------------------------------------------------------------------------

_HEADING_ROLES = {"title": 1, "sectionHeading": 2}


def blocks_from_di(result: dict[str, Any]) -> ParsedDocument:
    """Translate a prebuilt-layout analyze result into ordered blocks.

    Tables are read from the structured `tables` collection rather than the
    markdown body: cells carry row/column indices and spans, which is what lets
    a page-split table be reconciled later.
    """
    doc_id = result.get("doc_id", "")
    blocks: list[Block] = []

    for p in result.get("paragraphs", []) or []:
        role = p.get("role")
        page = _first_page(p) or 1
        if role in _HEADING_ROLES:
            blocks.append(Block(kind=BlockKind.HEADING, text=p.get("content", ""),
                                level=_HEADING_ROLES[role], page_start=page, page_end=page))
        elif role in (None, "footnote"):
            text = (p.get("content") or "").strip()
            if text:
                blocks.append(Block(kind=BlockKind.PARAGRAPH, text=text,
                                    page_start=page, page_end=page))

    for t in result.get("tables", []) or []:
        blocks.append(_table_block(t))

    blocks.sort(key=lambda b: (b.page_start,))
    return ParsedDocument(
        doc_id=doc_id, blocks=blocks, page_count=len(result.get("pages", []) or [])
    )


def _first_page(node: dict[str, Any]) -> int | None:
    for region in node.get("boundingRegions", []) or []:
        if "pageNumber" in region:
            return int(region["pageNumber"])
    return None


def _table_block(t: dict[str, Any]) -> Block:
    n_cols = int(t.get("columnCount", 0) or 0)
    n_rows = int(t.get("rowCount", 0) or 0)
    grid = [["" for _ in range(n_cols)] for _ in range(n_rows)]
    header: list[str] | None = None

    for cell in t.get("cells", []) or []:
        r, c = int(cell.get("rowIndex", 0)), int(cell.get("columnIndex", 0))
        if 0 <= r < n_rows and 0 <= c < n_cols:
            grid[r][c] = (cell.get("content") or "").strip()
        if cell.get("kind") == "columnHeader" and r == 0:
            header = header or ["" for _ in range(n_cols)]
            if 0 <= c < n_cols:
                header[c] = (cell.get("content") or "").strip()

    if header is not None:
        # Header cells were flagged explicitly; row 0 is that header, so it
        # must not also be emitted as data.
        rows = grid[1:]
    elif grid:
        header, rows = grid[0], grid[1:]
    else:
        rows = grid

    pages = [int(r["pageNumber"]) for r in (t.get("boundingRegions") or [])
             if "pageNumber" in r] or [1]
    return Block(kind=BlockKind.TABLE, header=header, rows=rows,
                 page_start=min(pages), page_end=max(pages))


# --------------------------------------------------------------------------
# Metadata inference
# --------------------------------------------------------------------------

_FILING_MARKER = re.compile(r"(10-?[KQ]|FY\d{2,4}|Q[1-4])", re.I)

_DOC_TYPE_PATTERNS = [
    (re.compile(r"\b10-?K\b", re.I), DocType.TEN_K),
    (re.compile(r"\b10-?Q\b", re.I), DocType.TEN_Q),
    (re.compile(r"shareholder|chairman'?s letter", re.I), DocType.MANAGER_LETTER),
    (re.compile(r"prospectus", re.I), DocType.PROSPECTUS),
    (re.compile(r"press release", re.I), DocType.PRESS_RELEASE),
]


def infer_metadata(doc_id: str, first_page_text: str, source_url: str = "") -> ChunkMetadata:
    """Cheap first pass over the cover page.

    A few-shot LLM classifier replaces this in phase 9; the point of the
    comparison is accuracy AND cost per document, so keep the free path.
    """
    doc_type = DocType.UNKNOWN
    for pattern, dt in _DOC_TYPE_PATTERNS:
        if pattern.search(first_page_text) or pattern.search(doc_id):
            doc_type = dt
            break

    year = None
    m = re.search(r"(?:FY|fiscal year(?:\s+ended)?[^\d]{0,20})((?:19|20)\d{2})",
                  first_page_text, re.I) or re.search(r"FY(\d{2,4})", doc_id, re.I)
    if m:
        raw = m.group(1)
        year = int(raw) if len(raw) == 4 else 2000 + int(raw)

    # Only read a ticker prefix when the rest of the id looks like a filing.
    # Without this guard "AI_ML_Engineer_Resume" yields the ticker "AI".
    ticker = ""
    if _FILING_MARKER.search(doc_id):
        tm = re.match(r"^([A-Z]{1,5})[-_]", doc_id)
        if tm:
            ticker = tm.group(1)

    return ChunkMetadata(
        doc_id=doc_id, ticker=ticker, doc_type=doc_type,
        fiscal_year=year, source_url=source_url,
    )


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

@dataclass
class IngestResult:
    doc_id: str
    chunks: int = 0
    indexed: int = 0
    from_cache: bool = False
    errors: list[str] = field(default_factory=list)


class IngestPipeline:
    def __init__(
        self,
        parser,
        embedder,
        searcher,
        cache_dir: str | Path = ".parsed_cache",
        settings: Settings | None = None,
    ) -> None:
        self.parser = parser
        self.embedder = embedder
        self.searcher = searcher
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.s = settings or get_settings()
        self.chunker = LayoutChunker()

    def cache_path(self, doc_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", doc_id)
        return self.cache / f"{safe}.json"

    async def parse(self, doc_id: str, content: bytes) -> tuple[dict[str, Any], bool]:
        """Parse, or return the cached result. The cache is what makes a
        re-index minutes rather than hours."""
        path = self.cache_path(doc_id)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")), True
        result = await self.parser.analyze(content)
        result["doc_id"] = doc_id
        path.write_text(json.dumps(result), encoding="utf-8")
        return result, False

    def to_chunks(self, result: dict[str, Any], source_url: str = "") -> list[Chunk]:
        parsed = blocks_from_di(result)
        first_text = " ".join(
            b.text for b in parsed.blocks[:12] if b.kind is not BlockKind.TABLE
        )
        meta = infer_metadata(parsed.doc_id, first_text, source_url)
        return self.chunker.chunk(parsed, meta)

    async def ingest(self, doc_id: str, content: bytes, source_url: str = "") -> IngestResult:
        out = IngestResult(doc_id=doc_id)
        try:
            result, cached = await self.parse(doc_id, content)
            out.from_cache = cached
        except Exception as exc:  # noqa: BLE001
            out.errors.append(f"parse failed: {exc}")
            return out

        chunks = self.to_chunks(result, source_url)
        out.chunks = len(chunks)
        if not chunks:
            return out

        try:
            vectors = await self.embedder.embed([c.content for c in chunks])
            documents = [
                chunk_to_document(c, v) for c, v in zip(chunks, vectors, strict=True)
            ]
            out.indexed = await self.searcher.upload(documents)
        except Exception as exc:  # noqa: BLE001
            out.errors.append(f"index failed: {exc}")
        return out
