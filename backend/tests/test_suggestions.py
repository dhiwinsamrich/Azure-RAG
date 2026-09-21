"""Starter questions only reference what the document actually contains."""

from __future__ import annotations

from rag_core.suggestions import DocText, suggest

TENK = """
Northwind Traders, Inc. (NASDAQ: NWND)

Total revenue was $211,915 million in fiscal year 2023 versus fiscal year 2022.
Gross margin was 69.8%. Total assets were $411,976 million.
"""

TENQ = """
Meridian Health Systems, Inc. (NYSE: MRDN)

Total revenue was $684 million for Q2 fiscal year 2024 versus Q2 fiscal year 2023.
Net income was $49 million.
"""


def test_only_topics_present_in_the_text_are_suggested():
    qs = suggest([DocText("A", TENK)])
    assert any("total revenue" in q for q in qs)
    assert any("gross margin" in q for q in qs)
    assert not any("segment" in q or "risk factors" in q or "net income" in q for q in qs)


def test_quarterly_filings_use_quarter_periods():
    qs = suggest([DocText("B", TENQ)])
    assert "What was total revenue in Q2 FY24?" in qs


def test_one_unanswerable_question_is_appended():
    assert suggest([DocText("A", TENK)])[-1] == "What is the revenue guidance for FY2026?"


def test_multiple_documents_are_named_and_interleaved():
    qs = suggest([DocText("A", TENK), DocText("B", TENQ)])
    assert qs[0].startswith("What was Northwind Traders' total revenue")
    assert "Meridian Health Systems' total revenue" in qs[1]


def test_no_documents_no_suggestions():
    assert suggest([]) == []
    assert suggest([DocText("X", "unrelated recipe text")]) == []
