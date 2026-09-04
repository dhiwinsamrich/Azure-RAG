"""Programmatic citation validation.

The model returns {answer, citations:[{chunk_id, quoted_span}]}. Two checks,
both cheap and both deterministic:

  1. The cited chunk_id was actually in the context set we sent.
  2. The quoted span really occurs in that chunk.

Anything failing is dropped from the rendered answer and counted. This is
hallucination detection that costs microseconds and needs no model call - the
difference between trusting the model and verifying it.
"""

from __future__ import annotations

import re
import unicodedata

from .schemas import Chunk, Citation, CitationVerdict, ModelAnswer, ValidatedAnswer

_WS = re.compile(r"\s+")

# Models routinely re-type a quote with different punctuation than the source.
_PUNCT_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ",
}

_MIN_SPAN_CHARS = 8


def normalize(text: str) -> str:
    """Fold the differences that do not change meaning.

    Unicode form, smart punctuation, whitespace and case. Thousands separators
    are removed so "$1,234" and "$1234" compare equal - a real match that a
    naive substring check would reject.
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = "".join(_PUNCT_MAP.get(ch, ch) for ch in t)
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)
    t = _WS.sub(" ", t)
    return t.strip().lower()


def validate_citation(
    citation: Citation, context_by_id: dict[str, str]
) -> CitationVerdict:
    source = context_by_id.get(citation.chunk_id)
    if source is None:
        return CitationVerdict(
            chunk_id=citation.chunk_id,
            quoted_span=citation.quoted_span,
            valid=False,
            reason="unknown_chunk",
        )

    span = normalize(citation.quoted_span)
    # Too short to be evidence of anything; treat as unsupported.
    if len(span) < _MIN_SPAN_CHARS:
        return CitationVerdict(
            chunk_id=citation.chunk_id,
            quoted_span=citation.quoted_span,
            valid=False,
            reason="span_not_found",
        )

    ok = span in normalize(source)
    return CitationVerdict(
        chunk_id=citation.chunk_id,
        quoted_span=citation.quoted_span,
        valid=ok,
        reason="ok" if ok else "span_not_found",
    )


def validate_answer(answer: ModelAnswer, context: list[Chunk]) -> ValidatedAnswer:
    by_id = {c.id: c.content for c in context}
    verdicts = [validate_citation(c, by_id) for c in answer.citations]
    kept = [c for c, v in zip(answer.citations, verdicts, strict=True) if v.valid]
    return ValidatedAnswer(
        answer=renumber_markers(answer.answer, context, kept),
        citations=kept,
        verdicts=verdicts,
        refused=answer.refused,
    )


def citation_validity(verdicts: list[CitationVerdict]) -> float:
    """Share of citations that survived validation.

    An answer with no citations scores 1.0 only when it is a refusal; callers
    that need the refusal distinction should check `ValidatedAnswer.refused`.
    """
    if not verdicts:
        return 1.0
    return sum(v.valid for v in verdicts) / len(verdicts)


_MARKER = re.compile(r"\[(\d{1,2})\]")


def renumber_markers(
    answer: str, context: list[Chunk], citations: list[Citation]
) -> str:
    """Rewrite inline [n] markers so they match the rendered citation list.

    The prompt numbers every retrieved passage 1..N, so the model writes the
    passage's position - it may cite passage [3] of 8. The UI, however, lists
    only the citations that survived validation, renumbered from 1. Left alone
    the answer reads "[3]" beside a list containing just [1] and [2].

    This maps each marker through position -> chunk_id -> citation index, and
    drops markers whose passage was never cited or whose citation failed
    validation - a marker pointing at nothing is worse than no marker.
    """
    if not answer:
        return answer

    position_to_chunk = {i: c.id for i, c in enumerate(context, start=1)}
    # First citation wins when several quote the same chunk.
    chunk_to_index: dict[str, int] = {}
    for i, c in enumerate(citations, start=1):
        chunk_to_index.setdefault(c.chunk_id, i)

    def replace(m: re.Match[str]) -> str:
        chunk_id = position_to_chunk.get(int(m.group(1)))
        if chunk_id is None:
            return ""
        index = chunk_to_index.get(chunk_id)
        return f"[{index}]" if index else ""

    out = _MARKER.sub(replace, answer)
    # Removing a marker can leave " ." or doubled spaces behind.
    out = re.sub(r"\s+([.,;:])", r"\1", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()
