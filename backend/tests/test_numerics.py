from __future__ import annotations

import pytest
from rag_core.numerics import (
    close_enough,
    extract_years,
    figures_match,
    parse_figures,
    period_matches,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$211.9 billion", 211_900_000_000),
        ("211,915 million", 211_915_000_000),
        ("$1.2B", 1_200_000_000),
        ("69,274", 69_274),
        ("1.5 trillion", 1_500_000_000_000),
        ("$450k", 450_000),
    ],
)
def test_scale_words_are_normalised(text, expected):
    figs = parse_figures(text)
    assert figs and close_enough(figs[0].value, expected)


def test_accounting_parentheses_are_negative():
    figs = parse_figures("Operating loss of (1,234) million")
    assert figs[0].value == pytest.approx(-1_234_000_000)


def test_percent_and_bps_are_distinct_units():
    pct = parse_figures("gross margin of 69.8%")[0]
    bps = parse_figures("up 140 basis points")[0]

    assert pct.unit == "percent" and pct.value == pytest.approx(69.8)
    assert bps.unit == "bps" and bps.value == pytest.approx(140)
    assert bps.as_percent() == pytest.approx(1.4)


def test_percent_is_not_double_counted_as_an_absolute():
    figs = parse_figures("margin was 69.8%")
    assert len(figs) == 1


def test_same_value_at_different_scales_matches():
    # This is the whole point: billions vs millions, same number.
    assert figures_match("$211.9 billion", "revenue of 211,900 million")


def test_wrong_scale_is_caught():
    # The 1000x error that scores well on embedding similarity.
    assert not figures_match("$211.9 billion", "revenue of $211.9 million")


def test_missing_figure_is_caught():
    assert not figures_match("68.4% and 69.8%", "margin improved to 69.8%")


def test_extra_figures_in_the_answer_are_allowed():
    assert figures_match("69.8%", "margin was 69.8%, up from 68.4%")


def test_qualitative_gold_answer_passes_trivially():
    assert figures_match("Margins improved.", "Margins improved on mix shift.")


def test_tolerance_accepts_rounding():
    assert figures_match("$211.9 billion", "about $211.95 billion")
    assert not figures_match("$211.9 billion", "about $260 billion")


@pytest.mark.parametrize(
    "text,year",
    [("FY23", 2023), ("fiscal year 2022", 2022), ("FY2024", 2024), ("in 2021", 2021)],
)
def test_fiscal_year_forms(text, year):
    assert year in extract_years(text)


def test_period_matching_catches_the_right_company_wrong_year_error():
    assert period_matches(2023, "In FY23 gross margin was 69.8%.")
    assert not period_matches(2023, "In FY22 gross margin was 68.4%.")
    assert period_matches(None, "no period mentioned")


def test_fiscal_period_tokens_are_not_parsed_as_figures():
    # "FY22" must not yield the figure 22, or every gold answer naming a
    # period becomes impossible to match.
    figs = parse_figures("Gross margin rose from 68.4% in FY22 to 69.8% in FY23.")
    assert [f.unit for f in figs] == ["percent", "percent"]


def test_bare_calendar_years_are_not_amounts():
    assert parse_figures("revenue grew in 2023") == []
    # ...but a real amount at that magnitude still parses.
    assert parse_figures("$2,023 million")[0].value == pytest.approx(2_023_000_000)


def test_gold_answer_with_periods_matches_an_answer_without_them():
    gold = "Gross margin rose from 68.4% in FY22 to 69.8% in FY23, up 140 basis points."
    assert figures_match(gold, "Margin rose from 68.4% to 69.8%, up 140 bps.")
