"""Starter questions drawn from what the active documents actually contain.

Deterministic and free: a question is only offered when the document's own text
carries the evidence to answer it, so a suggestion never sends someone to a
guaranteed "not found". One deliberately unanswerable question is appended so
the refusal behaviour is easy to try.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_COMPANY = re.compile(
    r"^\s*([A-Z][A-Za-z0-9&.' -]+?)(?:,?\s+(?:Inc|Corp|Corporation|Ltd|LLC|Co|Company|Group|Holdings)\.?)\s*\(",
    re.MULTILINE,
)
_QUARTER = re.compile(r"\bQ([1-4])\s+(?:fiscal\s+year\s+|FY\s?)(\d{4})", re.IGNORECASE)
_FISCAL_YEAR = re.compile(r"\bfiscal\s+year\s+(\d{4})", re.IGNORECASE)


@dataclass
class DocText:
    doc_id: str
    text: str
    fiscal_year: int | None = None
    doc_type: str = ""


def _label(doc: DocText) -> str:
    m = _COMPANY.search(doc.text[:2000])
    return m.group(1).strip() if m else ""


def _period(doc: DocText) -> tuple[str, str, int | None]:
    """(current, prior, fiscal year) as short labels, e.g. ("Q2 FY24", "Q2 FY23", 2024)."""
    q = _QUARTER.search(doc.text)
    years = [int(y) for y in _FISCAL_YEAR.findall(doc.text)]
    fy = doc.fiscal_year or (max(years) if years else None)
    if q:
        quarter, year = q.group(1), int(q.group(2))
        return f"Q{quarter} FY{year % 100:02d}", f"Q{quarter} FY{(year - 1) % 100:02d}", year
    if fy:
        return f"FY{fy % 100:02d}", f"FY{(fy - 1) % 100:02d}", fy
    return "", "", None


def _candidates(doc: DocText, name: str) -> list[str]:
    t = doc.text.lower()
    cur, prev, _ = _period(doc)
    when = f" in {cur}" if cur else ""
    who = (f"{name}' " if name.endswith("s") else f"{name}'s ") if name else ""
    at = f" at {name}" if name else ""

    out: list[str] = []
    if "revenue" in t and "$" in t:
        out.append(f"What was {who}total revenue{when}?")
    if "gross margin" in t:
        out.append(
            f"How did {who}gross margin change between {prev} and {cur}?"
            if cur
            else f"What was {who}gross margin?"
        )
    if "segment" in t and "operating income" in t:
        out.append(f"Which segment{at} had the largest operating income{when}?")
    if "total assets" in t:
        out.append(f"What were {who}total assets at the end of {cur}?" if cur else f"What were {who}total assets?")
    if "net income" in t:
        out.append(f"What was {who}net income{when}?")
    if "operating activities" in t:
        out.append(f"How much cash did operating activities provide{at}{when}?")
    if "risk factors" in t:
        out.append(f"What are the main risk factors{at}?")
    return out


def suggest(docs: list[DocText], answerable: int = 3) -> list[str]:
    """Round-robin across the active documents so each is represented."""
    if not docs:
        return []

    multi = len(docs) > 1
    pools = []
    for d in docs:
        name = (_label(d) or d.doc_id) if multi else ""
        pools.append(_candidates(d, name))

    picked: list[str] = []
    i = 0
    while len(picked) < answerable and any(pools):
        pool = pools[i % len(pools)]
        if pool:
            picked.append(pool.pop(0))
        i += 1

    years = [y for _, _, y in (_period(d) for d in docs) if y]
    if picked and years:
        picked.append(f"What is the revenue guidance for FY{max(years) + 3}?")

    return list(dict.fromkeys(picked))

