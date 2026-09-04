"""Is this document actually a financial filing?

The corpus is meant to be financial documents. An unrelated document in the
index is not merely clutter: it competes for every query, and a large one
crowds out the filings entirely (a 92-chunk resume guide out-ranked two 10-Ks
on the query "revenue").

The check is deliberately deterministic and free - no model call - and it
scores CATEGORIES of evidence rather than counting keywords, so a document
cannot pass by repeating one term. It reports what it matched and what it
missed, because a heuristic that rejects without explaining is unusable.

This is the cheap baseline the build plan calls for. The LLM classifier and a
fine-tuned encoder come later; the point of that phase is comparing all three
on accuracy AND cost per document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Each category is a distinct kind of evidence. Requiring several forces a
# document to look financial in more than one way.
SIGNALS: dict[str, list[str]] = {
    "filing type": [
        r"\bform\s+10-?[kq]\b", r"\b10-?[kq]\b", r"\bannual report\b",
        r"\bquarterly report\b", r"\bprospectus\b", r"\bform\s+8-?k\b",
        r"\bform\s+s-1\b", r"\bshareholder letter\b", r"\bproxy statement\b",
    ],
    "financial statements": [
        r"\bbalance sheets?\b", r"\bincome statements?\b",
        r"\bstatements? of operations\b", r"\bcash flows?\b",
        r"\bstockholders'? equity\b", r"\bshareholders'? equity\b",
        r"\bstatements? of financial position\b",
    ],
    "financial metrics": [
        r"\brevenues?\b", r"\bgross margin\b", r"\boperating income\b",
        r"\bnet income\b", r"\bearnings per share\b", r"\bebitda\b",
        r"\bcost of (?:goods sold|revenue)\b", r"\btotal assets\b",
        r"\btotal liabilities\b", r"\boperating expenses?\b",
    ],
    "fiscal period": [
        r"\bfiscal year\b", r"\bFY\s?\d{2,4}\b", r"\bQ[1-4]\s?\d{0,4}\b",
        r"\b(?:year|quarter) ended\b", r"\bthree months ended\b",
    ],
    "monetary amounts": [
        r"\$\s?\d", r"\b\d{1,3}(?:,\d{3})+\b",
        r"\b(?:in )?(?:millions|billions|thousands)\b",
        r"\bbasis points\b", r"\bbps\b",
    ],
    "regulatory": [
        r"\bsecurities and exchange commission\b", r"\bSEC\b", r"\bEDGAR\b",
        r"\bGAAP\b", r"\bIFRS\b", r"\bauditor'?s? report\b",
        r"\bmanagement'?s discussion\b",
    ],
}

_COMPILED = {
    name: [re.compile(p, re.IGNORECASE) for p in patterns]
    for name, patterns in SIGNALS.items()
}

# A document must be long enough for absence of evidence to mean anything.
MIN_CHARS = 200
DEFAULT_MIN_CATEGORIES = 3


@dataclass
class FinancialRelevance:
    accepted: bool
    score: float                       # matched categories / total categories
    matched: dict[str, list[str]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def matched_categories(self) -> list[str]:
        return sorted(self.matched)

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "score": round(self.score, 3),
            "matched": {k: v[:4] for k, v in self.matched.items()},
            "matched_categories": self.matched_categories,
            "missing_categories": self.missing,
            "reason": self.reason,
        }


def assess(
    text: str, doc_id: str = "", min_categories: int = DEFAULT_MIN_CATEGORIES
) -> FinancialRelevance:
    """Score a document on how much financial evidence it carries.

    Only the text is judged; the filename is appended because filings are
    routinely named `MSFT-10K-FY23` and that is real evidence, but a filename
    alone can never carry a document over the bar.
    """
    body = f"{doc_id}\n{text or ''}"

    if len(body.strip()) < MIN_CHARS:
        return FinancialRelevance(
            accepted=False, score=0.0, missing=sorted(SIGNALS),
            reason=(
                f"Document is too short to assess ({len(body.strip())} characters; "
                f"at least {MIN_CHARS} needed)."
            ),
        )

    matched: dict[str, list[str]] = {}
    for name, patterns in _COMPILED.items():
        hits: list[str] = []
        for p in patterns:
            found = p.search(body)
            if found:
                hits.append(found.group(0).strip())
        if hits:
            # De-duplicate case variants while keeping order.
            seen: dict[str, None] = {}
            for h in hits:
                seen.setdefault(h.lower(), None)
            matched[name] = list(seen)

    missing = sorted(set(SIGNALS) - set(matched))
    score = len(matched) / len(SIGNALS)
    accepted = len(matched) >= min_categories

    if accepted:
        reason = (
            f"Matched {len(matched)} of {len(SIGNALS)} evidence categories: "
            f"{', '.join(sorted(matched))}."
        )
    else:
        reason = (
            f"Only {len(matched)} of {len(SIGNALS)} evidence categories matched "
            f"({', '.join(sorted(matched)) or 'none'}); at least {min_categories} "
            f"are required. Missing: {', '.join(missing)}."
        )

    return FinancialRelevance(
        accepted=accepted, score=score, matched=matched, missing=missing, reason=reason
    )


def sample_text(parsed: dict, limit: int = 6000) -> str:
    """Text to judge, taken from a parsed document.

    Paragraphs and table cells both count - a filing that is mostly tables is
    still a filing.
    """
    parts: list[str] = []
    for p in parsed.get("paragraphs", []) or []:
        parts.append(str(p.get("content", "")))
        if sum(len(x) for x in parts) > limit:
            break
    for t in (parsed.get("tables", []) or [])[:8]:
        for cell in (t.get("cells", []) or [])[:60]:
            parts.append(str(cell.get("content", "")))
    return "\n".join(parts)[:limit]
