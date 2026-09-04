"""Table handling: cross-page reconciliation and markdown rendering.

Document Intelligence returns a table that spans a page break as two separate
tables. Left alone, every financial statement that runs over a page boundary is
split mid-figure, so the halves retrieve separately and neither answers the
question. This module stitches them back together.
"""

from __future__ import annotations

import re

from .schemas import Block, BlockKind

_WS = re.compile(r"\s+")


def norm_cell(s: str) -> str:
    return _WS.sub(" ", (s or "").strip()).lower()


def headers_match(a: list[str] | None, b: list[str] | None) -> bool:
    if not a or not b or len(a) != len(b):
        return False
    return [norm_cell(x) for x in a] == [norm_cell(x) for x in b]


def looks_like_continuation(prev: Block, nxt: Block) -> bool:
    """Decide whether `nxt` continues the table `prev`.

    Two accepted shapes, both conservative - a false merge corrupts a financial
    statement, so we only join on strong evidence:

    1. The continuation repeats the header row (common in filings).
    2. The continuation has no header at all and the column count matches.
    """
    if prev.kind is not BlockKind.TABLE or nxt.kind is not BlockKind.TABLE:
        return False
    if nxt.page_start not in (prev.page_end, prev.page_end + 1):
        return False
    if prev.n_cols == 0 or prev.n_cols != nxt.n_cols:
        return False
    if nxt.header and prev.header:
        return headers_match(prev.header, nxt.header)
    return not nxt.header


def merge_tables(prev: Block, nxt: Block) -> Block:
    rows = list(prev.rows or [])
    nxt_rows = list(nxt.rows or [])
    # A repeated header row arrives as data on the continuation page; drop it.
    if prev.header and nxt_rows and headers_match(prev.header, nxt_rows[0]):
        nxt_rows = nxt_rows[1:]
    rows.extend(nxt_rows)
    return Block(
        kind=BlockKind.TABLE,
        text="",
        header=prev.header,
        rows=rows,
        page_start=prev.page_start,
        page_end=max(prev.page_end, nxt.page_end),
    )


def reconcile(blocks: list[Block]) -> list[Block]:
    """Merge page-split tables, preserving document order of everything else.

    A continuation may be separated from its head only by whitespace-ish blocks
    (page furniture); anything with real text between them blocks the merge.
    """
    out: list[Block] = []
    pending_gap: list[Block] = []

    for b in blocks:
        if out and b.kind is BlockKind.TABLE and looks_like_continuation(out[-1], b):
            out[-1] = merge_tables(out[-1], b)
            pending_gap.clear()
            continue

        if out and out[-1].kind is BlockKind.TABLE and b.kind is not BlockKind.TABLE:
            # Hold trivial blocks so a header/footer does not break a merge.
            if not b.text.strip():
                pending_gap.append(b)
                continue

        out.extend(pending_gap)
        pending_gap.clear()
        out.append(b)

    out.extend(pending_gap)
    return out


def to_markdown(block: Block) -> str:
    """Render a table as a pipe table - the form LLMs read most reliably."""
    if block.kind is not BlockKind.TABLE:
        return block.text
    header = block.header or []
    rows = block.rows or []
    if not header and rows:
        header, rows = rows[0], rows[1:]
    if not header:
        return ""
    width = len(header)

    def line(cells: list[str]) -> str:
        padded = list(cells) + [""] * (width - len(cells))
        return "| " + " | ".join((c or "").strip() for c in padded[:width]) + " |"

    lines = [line(header), "|" + "|".join([" --- "] * width) + "|"]
    lines.extend(line(r) for r in rows)
    return "\n".join(lines)


def block_text(block: Block) -> str:
    return to_markdown(block) if block.kind is BlockKind.TABLE else block.text
