from __future__ import annotations

from rag_core.citations import normalize, validate_answer
from rag_core.schemas import Citation, ModelAnswer


def answer(*cits: Citation, refused: bool = False) -> ModelAnswer:
    return ModelAnswer(answer="Gross margin rose.", citations=list(cits), refused=refused)


def test_valid_citation_passes(context_chunks):
    a = answer(Citation(chunk_id="MSFT-10K-FY23::0001", quoted_span="Gross margin was 69.8%"))
    v = validate_answer(a, context_chunks)

    assert v.verdicts[0].valid
    assert v.citation_validity == 1.0
    assert len(v.citations) == 1


def test_fabricated_chunk_id_is_rejected(context_chunks):
    a = answer(Citation(chunk_id="DOES-NOT-EXIST::9999", quoted_span="Gross margin was 69.8%"))
    v = validate_answer(a, context_chunks)

    assert not v.verdicts[0].valid
    assert v.verdicts[0].reason == "unknown_chunk"
    assert v.citations == []  # dropped from the rendered answer


def test_span_not_present_in_the_cited_chunk_is_rejected(context_chunks):
    a = answer(Citation(chunk_id="MSFT-10K-FY23::0001",
                        quoted_span="Gross margin was 72.1% in fiscal 2023"))
    v = validate_answer(a, context_chunks)

    assert not v.verdicts[0].valid
    assert v.verdicts[0].reason == "span_not_found"
    assert v.failures == 1


def test_span_matching_tolerates_punctuation_and_whitespace(context_chunks):
    a = answer(Citation(
        chunk_id="MSFT-10K-FY23::0001",
        quoted_span="  gross   margin was 69.8% in fiscal year 2023,\ncompared with 68.4% ",
    ))
    assert validate_answer(a, context_chunks).verdicts[0].valid


def test_span_that_skips_source_text_is_rejected(context_chunks):
    # "A, C" quoted from a source that reads "A, B, C" is not a real quote,
    # and eliding the qualifier is exactly how a citation misleads.
    a = answer(Citation(
        chunk_id="MSFT-10K-FY23::0001",
        quoted_span="Gross margin was 69.8%, compared with 68.4%",
    ))
    v = validate_answer(a, context_chunks)
    assert not v.verdicts[0].valid
    assert v.verdicts[0].reason == "span_not_found"


def test_span_matching_tolerates_thousands_separators(context_chunks):
    a = answer(Citation(chunk_id="MSFT-10K-FY23::0002",
                        quoted_span="Intelligent Cloud revenue was $87907 million"))
    assert validate_answer(a, context_chunks).verdicts[0].valid


def test_trivially_short_span_is_not_accepted_as_evidence(context_chunks):
    a = answer(Citation(chunk_id="MSFT-10K-FY23::0001", quoted_span="was"))
    v = validate_answer(a, context_chunks)
    assert not v.verdicts[0].valid


def test_mixed_validity_scores_partially(context_chunks):
    a = answer(
        Citation(chunk_id="MSFT-10K-FY23::0001", quoted_span="Gross margin was 69.8%"),
        Citation(chunk_id="MSFT-10K-FY23::0002", quoted_span="revenue was $12 million"),
    )
    v = validate_answer(a, context_chunks)
    assert v.citation_validity == 0.5
    assert len(v.citations) == 1


def test_refusal_carries_no_citations(context_chunks):
    v = validate_answer(answer(refused=True), context_chunks)
    assert v.refused
    assert v.citation_validity == 1.0


def test_normalize_folds_smart_quotes_and_dashes():
    assert normalize("“Revenue”—up") == normalize('"revenue"-up')


# --------------------------------------------------------------------------
# Inline marker renumbering
# --------------------------------------------------------------------------

def test_markers_are_renumbered_to_match_the_citation_list(context_chunks):
    # The model cites passage [2] of the context; it is the only surviving
    # citation, so the list renders it as [1] and the prose must agree.
    a = ModelAnswer(
        answer="Cloud revenue grew [2].",
        citations=[Citation(chunk_id="MSFT-10K-FY23::0002",
                            quoted_span="Intelligent Cloud revenue was $87,907 million")],
    )
    v = validate_answer(a, context_chunks)
    assert v.answer == "Cloud revenue grew [1]."


def test_two_markers_on_the_same_chunk_share_one_number(context_chunks):
    span = "Gross margin was 69.8%"
    a = ModelAnswer(
        answer="Margin rose [1]. Mix drove it [1].",
        citations=[
            Citation(chunk_id="MSFT-10K-FY23::0001", quoted_span=span),
            Citation(chunk_id="MSFT-10K-FY23::0001", quoted_span="compared with 68.4%"),
        ],
    )
    v = validate_answer(a, context_chunks)
    assert v.answer == "Margin rose [1]. Mix drove it [1]."


def test_marker_for_an_uncited_passage_is_dropped(context_chunks):
    # [2] was never cited, so the number would point at nothing.
    a = ModelAnswer(
        answer="Margin rose [1] and revenue grew [2].",
        citations=[Citation(chunk_id="MSFT-10K-FY23::0001",
                            quoted_span="Gross margin was 69.8%")],
    )
    v = validate_answer(a, context_chunks)
    assert v.answer == "Margin rose [1] and revenue grew."


def test_marker_for_a_failed_citation_is_dropped(context_chunks):
    a = ModelAnswer(
        answer="Margin was 88% [1].",
        citations=[Citation(chunk_id="MSFT-10K-FY23::0001", quoted_span="margin was 88%")],
    )
    v = validate_answer(a, context_chunks)
    assert v.citations == []
    assert v.answer == "Margin was 88%."


def test_out_of_range_marker_is_dropped(context_chunks):
    a = ModelAnswer(answer="Something [9].", citations=[])
    assert validate_answer(a, context_chunks).answer == "Something."
