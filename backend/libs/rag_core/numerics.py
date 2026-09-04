"""Financial figure parsing and comparison.

The failure mode that matters most in this domain and that no generic RAG
metric measures: the model reports the right number at the wrong scale.
"$211.9 billion" against a gold answer of "$211,915 million" is correct;
"$211.9 million" is off by a factor of 1000 - and both score nearly identically
on embedding similarity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SCALES: dict[str, float] = {
    "hundred": 1e2,
    "thousand": 1e3, "k": 1e3,
    "million": 1e6, "m": 1e6, "mm": 1e6, "mn": 1e6,
    "billion": 1e9, "b": 1e9, "bn": 1e9,
    "trillion": 1e12, "t": 1e12, "tn": 1e12,
}

# The lookbehind stops a number being pulled out of the middle of a token:
# without it "FY22" yields the figure 22, and every fiscal-period reference in
# a gold answer becomes a phantom figure the answer has to match.
_NUM = r"(?<![A-Za-z0-9.,])\(?-?\$?\s*\d[\d,]*(?:\.\d+)?\)?"
_SCALE = "|".join(sorted(SCALES, key=len, reverse=True))

_FIGURE = re.compile(
    rf"(?P<num>{_NUM})\s*(?P<scale>{_SCALE})?\b",
    re.IGNORECASE,
)
# "%" is not a word character, so a trailing \b after it never matches; the
# word boundary has to apply only to the spelled-out alternatives.
_PERCENT = re.compile(
    rf"(?P<num>{_NUM})\s*(?:%|(?:percent|percentage points?|pp)\b)", re.IGNORECASE
)
_BPS = re.compile(rf"(?P<num>{_NUM})\s*(?:bps|basis points?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Figure:
    value: float
    unit: str  # "absolute" | "percent" | "bps"
    raw: str

    def as_percent(self) -> float | None:
        if self.unit == "percent":
            return self.value
        if self.unit == "bps":
            return self.value / 100.0
        return None


def _to_float(raw: str) -> float | None:
    s = raw.strip()
    negative = s.startswith("(") and s.endswith(")")  # accounting negatives
    s = s.strip("()").replace("$", "").replace(",", "").strip()
    if not s or s in {"-", "."}:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if negative else v


def parse_figures(text: str) -> list[Figure]:
    """Extract every figure from a piece of text, scale-normalised.

    Percent and basis-point figures are matched first so they are not also
    picked up as bare absolutes.
    """
    if not text:
        return []

    out: list[Figure] = []
    consumed: list[tuple[int, int]] = []

    for pattern, unit in ((_BPS, "bps"), (_PERCENT, "percent")):
        for m in pattern.finditer(text):
            v = _to_float(m.group("num"))
            if v is not None:
                out.append(Figure(v, unit, m.group(0).strip()))
                consumed.append(m.span())

    def overlaps(span: tuple[int, int]) -> bool:
        return any(span[0] < e and s < span[1] for s, e in consumed)

    for m in _FIGURE.finditer(text):
        if overlaps(m.span()):
            continue
        v = _to_float(m.group("num"))
        if v is None:
            continue
        scale = (m.group("scale") or "").lower()
        if scale:
            v *= SCALES[scale]
        elif _looks_like_year(m.group("num")):
            # A bare four-digit number in the calendar range is a year, not an
            # amount. Treating "2023" as a figure makes every gold answer that
            # names a period impossible to match.
            continue
        out.append(Figure(v, "absolute", m.group(0).strip()))

    return out


def _looks_like_year(raw: str) -> bool:
    s = raw.strip().replace("$", "").strip()
    return s.isdigit() and len(s) == 4 and 1900 <= int(s) <= 2099


def close_enough(a: float, b: float, rel_tol: float = 0.005, abs_tol: float = 1e-9) -> bool:
    if a == b:
        return True
    denom = max(abs(a), abs(b))
    if denom == 0:
        return abs(a - b) <= abs_tol
    return abs(a - b) / denom <= rel_tol


def figures_match(expected: str, actual: str, rel_tol: float = 0.005) -> bool:
    """True when every figure in `expected` appears in `actual`.

    Direction matters: the answer may legitimately mention figures the gold
    answer omits, but every gold figure must be present and at the right scale.
    """
    want = parse_figures(expected)
    if not want:
        return True
    have = parse_figures(actual)
    for w in want:
        if not any(
            h.unit == w.unit and close_enough(w.value, h.value, rel_tol) for h in have
        ):
            return False
    return True


# --------------------------------------------------------------------------
# Fiscal period
# --------------------------------------------------------------------------

_FY = re.compile(r"\b(?:FY|fiscal(?:\s+year)?\s*)[\s']*((?:19|20)\d{2}|\d{2})\b", re.IGNORECASE)
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_QUARTER = re.compile(r"\bQ([1-4])\b", re.IGNORECASE)


def extract_years(text: str) -> set[int]:
    years: set[int] = set()
    for m in _FY.finditer(text or ""):
        raw = m.group(1)
        years.add(int(raw) if len(raw) == 4 else 2000 + int(raw))
    for m in _YEAR.finditer(text or ""):
        years.add(int(m.group(1)))
    return years


def extract_quarters(text: str) -> set[int]:
    return {int(m.group(1)) for m in _QUARTER.finditer(text or "")}


def period_matches(expected_year: int | None, answer: str) -> bool:
    """Did the answer talk about the period that was asked about?

    This is exactly the error vector-only retrieval produces: right company,
    right metric, wrong year.
    """
    if expected_year is None:
        return True
    return expected_year in extract_years(answer)
