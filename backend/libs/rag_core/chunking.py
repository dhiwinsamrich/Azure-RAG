"""Layout-aware chunking.

The decision that drives retrieval quality more than any other. Fixed-size
character chunking flattens a balance sheet into soup and splits answers across
boundaries; this splits on the document's own structure instead.

Rules, in priority order:
  1. Split on section headings, not character counts.
  2. Never split a table. An oversized table becomes its own chunk.
  3. Oversized prose splits on paragraph boundaries, with overlap.
  4. Every chunk carries a context header naming company, doc type, period
     and section path.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from .schemas import Block, BlockKind, Chunk, ChunkMetadata, ParsedDocument
from .tables import block_text, reconcile

TokenCounter = Callable[[str], int]

_WORD = re.compile(r"\S+")
_HAS_CONTENT = re.compile(r"[A-Za-z0-9]")


def approx_tokens(text: str) -> int:
    """Cheap token estimate: ~4 chars/token, floored by the word count.

    Deliberately dependency-free so chunking stays testable offline. Swap in
    tiktoken via the `count_tokens` argument when exactness matters.
    """
    if not text:
        return 0
    words = len(_WORD.findall(text))
    return max(words, (len(text) + 3) // 4)


def _split_paragraphs(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


class LayoutChunker:
    def __init__(
        self,
        target_tokens: int = 650,
        overlap_tokens: int = 100,
        max_tokens: int | None = None,
        count_tokens: TokenCounter = approx_tokens,
    ) -> None:
        if overlap_tokens >= target_tokens:
            raise ValueError("overlap_tokens must be smaller than target_tokens")
        self.target = target_tokens
        self.overlap = overlap_tokens
        # The semantic ranker only reads ~2000 tokens of the content field, so a
        # chunk above that is silently truncated at rank time.
        self.max_tokens = max_tokens or 2000
        self.count = count_tokens

    # -- public ----------------------------------------------------------
    def chunk(self, doc: ParsedDocument, meta: ChunkMetadata) -> list[Chunk]:
        blocks = reconcile(doc.blocks)
        chunks: list[Chunk] = []
        heading_stack: list[tuple[int, str]] = []
        buffer: list[Block] = []

        def flush() -> None:
            if buffer:
                chunks.extend(self._emit(buffer, heading_stack, meta, len(chunks)))
                buffer.clear()

        for b in blocks:
            if b.kind is BlockKind.HEADING:
                flush()
                while heading_stack and heading_stack[-1][0] >= b.level:
                    heading_stack.pop()
                heading_stack.append((b.level, b.text.strip()))
                continue

            if b.kind is BlockKind.TABLE:
                # Rule 2: a table is atomic. Emit the prose before it, then the
                # table on its own, so nothing can split it.
                flush()
                chunks.extend(self._emit([b], heading_stack, meta, len(chunks)))
                continue

            buffer.append(b)
            if self.count(self._join(buffer)) >= self.target:
                flush()

        flush()
        return chunks

    # -- internals -------------------------------------------------------
    @staticmethod
    def _join(blocks: list[Block]) -> str:
        return "\n\n".join(t for t in (block_text(b) for b in blocks) if t)

    @staticmethod
    def _section_path(stack: list[tuple[int, str]]) -> str:
        return " > ".join(t for _, t in stack if t)

    def _emit(
        self,
        blocks: list[Block],
        stack: list[tuple[int, str]],
        meta: ChunkMetadata,
        start_index: int,
    ) -> list[Chunk]:
        if not blocks:
            return []
        body = self._join(blocks)
        if not body.strip():
            return []

        section_path = self._section_path(stack)
        contains_table = any(b.kind is BlockKind.TABLE for b in blocks)
        page_start = min(b.page_start for b in blocks)
        page_end = max(b.page_end for b in blocks)

        if contains_table or self.count(body) <= self.target:
            pieces = [body]
        else:
            pieces = self._split_prose(body)

        # Punctuation-only fragments (rules, stray separators) are never worth
        # an index entry, an embedding call, or a slot in the context window.
        pieces = [p for p in pieces if _HAS_CONTENT.search(p)]

        out: list[Chunk] = []
        for i, piece in enumerate(pieces):
            m = meta.model_copy(update={
                "section_path": section_path,
                "page_start": page_start,
                "page_end": page_end,
                "chunk_index": start_index + i,
                "contains_table": contains_table,
            })
            chunk = Chunk(
                id=f"{m.doc_id}::{m.chunk_index:04d}",
                content="",
                metadata=m,
            )
            # Rule 4: the header goes into the indexed text, not just metadata,
            # so BM25 and the embedding both see the referent.
            header = chunk.context_header()
            chunk.content = f"[{header}]\n\n{piece}" if header else piece
            chunk.token_count = self.count(chunk.content)
            out.append(chunk)
        return out

    def _split_prose(self, text: str) -> list[str]:
        """Rule 3: split on paragraph boundaries with a trailing overlap."""
        paras = _split_paragraphs(text)
        pieces: list[str] = []
        current: list[str] = []

        for p in paras:
            candidate = current + [p]
            if current and self.count("\n\n".join(candidate)) > self.target:
                pieces.append("\n\n".join(current))
                current = self._overlap_tail(current) + [p]
            else:
                current = candidate

        if current:
            pieces.append("\n\n".join(current))

        # A single paragraph can still exceed the ranker's read window.
        out: list[str] = []
        for piece in pieces:
            out.extend(self._hard_split(piece) if self.count(piece) > self.max_tokens
                       else [piece])
        return out

    def _overlap_tail(self, paras: list[str]) -> list[str]:
        tail: list[str] = []
        for p in reversed(paras):
            if self.count("\n\n".join([p, *tail])) > self.overlap:
                break
            tail.insert(0, p)
        return tail

    def _hard_split(self, text: str) -> list[str]:
        words = text.split()
        if not words:
            return []
        # Convert the token budget to words using the ratio this text exhibits.
        ratio = max(self.count(text) / len(words), 1e-6)
        per_chunk = max(int(self.max_tokens / ratio), 1)
        return [" ".join(words[i:i + per_chunk]) for i in range(0, len(words), per_chunk)]
