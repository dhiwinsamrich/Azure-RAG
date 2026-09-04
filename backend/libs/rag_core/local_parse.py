"""A local stand-in for Azure AI Document Intelligence.

Document Intelligence's free tier (F0) processes only the FIRST TWO PAGES of a
multi-page document, which makes it useless for filings - you would index the
cover page and nothing else. So the zero-cost path parses text and markdown
locally instead.

What this gives up versus `prebuilt-layout`:
  * No OCR. Scanned PDFs need the real service.
  * No bounding regions, so a citation resolves to a page number but not to a
    highlight box on the page image.
  * Page numbers come from explicit `<!-- page: N -->` markers or form feeds,
    not from real layout analysis.

What it keeps: heading hierarchy, paragraph structure, and markdown pipe
tables parsed into real `Block` tables - which is what the chunker and the
cross-page table reconciler actually consume.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_PAGE_MARKER = re.compile(r"^\s*<!--\s*page:\s*(\d+)\s*-->\s*$", re.IGNORECASE)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
# A horizontal rule is a visual separator, not text. Left in, it becomes a
# paragraph and then a chunk whose entire body is "---".
_THEMATIC_BREAK = re.compile(r"^\s*([-*_])(?:[ \t]*\1){2,}[ \t]*$")

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt"}


def _split_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def parse_text(text: str, doc_id: str = "") -> dict[str, Any]:
    """Parse markdown/plain text into the same dict shape the ingest pipeline
    expects from Document Intelligence, so downstream code is unchanged."""
    paragraphs: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []

    page = 1
    max_page = 1
    buffer: list[str] = []
    lines = text.replace("\f", "\n<!-- page-break -->\n").splitlines()

    def flush_paragraph() -> None:
        nonlocal buffer
        body = " ".join(x.strip() for x in buffer).strip()
        if body:
            paragraphs.append({
                "role": None, "content": body,
                "boundingRegions": [{"pageNumber": page}],
            })
        buffer = []

    i = 0
    while i < len(lines):
        line = lines[i]

        m = _PAGE_MARKER.match(line)
        if m:
            flush_paragraph()
            page = int(m.group(1))
            max_page = max(max_page, page)
            i += 1
            continue

        if line.strip() == "<!-- page-break -->":
            flush_paragraph()
            page += 1
            max_page = max(max_page, page)
            i += 1
            continue

        m = _HEADING.match(line)
        if m:
            flush_paragraph()
            paragraphs.append({
                "role": "title" if len(m.group(1)) == 1 else "sectionHeading",
                "content": m.group(2).strip(),
                "boundingRegions": [{"pageNumber": page}],
            })
            i += 1
            continue

        if _TABLE_ROW.match(line):
            flush_paragraph()
            block_lines = []
            while i < len(lines) and _TABLE_ROW.match(lines[i]):
                block_lines.append(lines[i])
                i += 1
            tables.append(_table_from_markdown(block_lines, page))
            continue

        if _THEMATIC_BREAK.match(line):
            flush_paragraph()
            i += 1
            continue

        if not line.strip():
            flush_paragraph()
        else:
            buffer.append(line)
        i += 1

    flush_paragraph()

    return {
        "doc_id": doc_id,
        "pages": [{"pageNumber": p} for p in range(1, max_page + 1)],
        "paragraphs": paragraphs,
        "tables": tables,
    }


def _table_from_markdown(lines: list[str], page: int) -> dict[str, Any]:
    rows = [_split_row(x) for x in lines if not _TABLE_SEP.match(x)]
    if not rows:
        return {"rowCount": 0, "columnCount": 0, "cells": [],
                "boundingRegions": [{"pageNumber": page}]}

    n_cols = max(len(r) for r in rows)
    cells = []
    for r_i, row in enumerate(rows):
        for c_i in range(n_cols):
            cells.append({
                "rowIndex": r_i,
                "columnIndex": c_i,
                "content": row[c_i] if c_i < len(row) else "",
                # The first row of a markdown table is its header.
                "kind": "columnHeader" if r_i == 0 else "content",
            })
    return {
        "rowCount": len(rows), "columnCount": n_cols, "cells": cells,
        "boundingRegions": [{"pageNumber": page}],
    }


class LocalParser:
    """Satisfies the same `analyze(content: bytes)` contract as
    `DocumentIntelligenceParser`, so the ingest pipeline is untouched."""

    async def analyze(self, content: bytes) -> dict[str, Any]:
        return parse_text(content.decode("utf-8", errors="replace"))


def is_supported(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_SUFFIXES
