from __future__ import annotations

from rag_core.evaluation.custom import (
    CITATION_PRECISION,
    CITATION_RECALL,
    CONTEXT_HIT_RATE,
    FISCAL_PERIOD,
    MRR,
    NUMERIC_EXACTNESS,
    REFUSAL_CORRECT,
    evaluate,
    false_refusal_rate,
)
from rag_core.evaluation.gate import evaluate_gate
from rag_core.schemas import (
    Citation,
    CitationVerdict,
    EvalResult,
    EvalRun,
    GateThreshold,
    GoldenQuestion,
    MetricValue,
    QuestionType,
)

from .conftest import make_trace


def by_name(metrics, name):
    return next(m for m in metrics if m.metric_name == name)


def test_numeric_exactness_catches_a_scale_error(question):
    trace = make_trace(answer="Gross margin rose from 68.4% to 69.8%, up 140 bps.")
    assert by_name(evaluate(trace, question), NUMERIC_EXACTNESS).value == 1.0

    wrong = make_trace(answer="Gross margin rose from 68.4% to 72.0%.")
    assert by_name(evaluate(wrong, question), NUMERIC_EXACTNESS).value == 0.0


def test_numeric_exactness_is_skipped_for_qualitative_questions():
    q = GoldenQuestion(id="q", question="Why did margin move?",
                       gold_answer="Because of segment mix.")
    trace = make_trace(answer="Segment mix shifted toward cloud.")
    assert by_name(evaluate(trace, q), NUMERIC_EXACTNESS).value is None


def test_fiscal_period_catches_right_metric_wrong_year(question):
    good = make_trace(answer="In FY2023 gross margin was 69.8%.")
    bad = make_trace(answer="In FY2021 gross margin was 67.0%.")
    assert by_name(evaluate(good, question), FISCAL_PERIOD).value == 1.0
    assert by_name(evaluate(bad, question), FISCAL_PERIOD).value == 0.0


def test_refusal_scoring_runs_in_both_directions():
    unanswerable = GoldenQuestion(
        id="u", question="What is the CEO's home address?",
        answerable=False, q_type=QuestionType.UNANSWERABLE,
    )
    assert by_name(evaluate(make_trace(refused=True), unanswerable), REFUSAL_CORRECT).value == 1.0
    assert by_name(evaluate(make_trace(answer="123 Main St"), unanswerable),
                   REFUSAL_CORRECT).value == 0.0

    answerable = GoldenQuestion(id="a", question="Revenue?", gold_answer="x", answerable=True)
    m = by_name(evaluate(make_trace(refused=True), answerable), REFUSAL_CORRECT)
    assert m.value == 0.0 and m.reason == "false refusal"


def test_false_refusal_rate_ignores_unanswerable_questions():
    qs = [
        GoldenQuestion(id="a", question="q", answerable=True),
        GoldenQuestion(id="b", question="q", answerable=True),
        GoldenQuestion(id="c", question="q", answerable=False),
    ]
    traces = {
        "a": make_trace(refused=True),
        "b": make_trace(answer="ok"),
        "c": make_trace(refused=True),
    }
    assert false_refusal_rate(traces, qs) == 0.5


def test_citation_precision_and_recall_against_gold_chunks(question, context_chunks):
    trace = make_trace(
        answer="Margin rose.",
        citations=[
            Citation(chunk_id="MSFT-10K-FY23::0001", quoted_span="Gross margin was 69.8%"),
            Citation(chunk_id="MSFT-10K-FY23::0002", quoted_span="revenue"),
        ],
        retrieved=context_chunks,
    )
    metrics = evaluate(trace, question)
    assert by_name(metrics, CITATION_PRECISION).value == 0.5
    assert by_name(metrics, CITATION_RECALL).value == 1.0


def test_retrieval_metrics_report_hit_rate_and_mrr(question, context_chunks):
    # Gold chunk is second in the retrieved list.
    trace = make_trace(retrieved=list(reversed(context_chunks)))
    metrics = evaluate(trace, question)
    assert by_name(metrics, CONTEXT_HIT_RATE).value == 1.0
    assert by_name(metrics, MRR).value == 0.5


def test_retrieval_metrics_report_a_miss(question):
    assert by_name(evaluate(make_trace(), question), CONTEXT_HIT_RATE).value == 0.0


def test_citation_validity_is_none_when_an_answer_cites_nothing(question):
    trace = make_trace(answer="Margin rose.")
    m = by_name(evaluate(trace, question), "citation_validity")
    assert m.value is None


def test_citation_validity_counts_invalid_verdicts(question):
    trace = make_trace(answer="x")
    trace.verdicts = [
        CitationVerdict(chunk_id="a", quoted_span="s", valid=True),
        CitationVerdict(chunk_id="b", quoted_span="s", valid=False, reason="span_not_found"),
    ]
    m = by_name(evaluate(trace, question), "citation_validity")
    assert m.value == 0.5
    assert "span_not_found" in m.reason


# --------------------------------------------------------------------------
# Aggregation and the CI gate
# --------------------------------------------------------------------------

def run_with(values: dict[str, list[float]], q_types: list[QuestionType]) -> EvalRun:
    results = []
    for i, _qt in enumerate(q_types):
        results.append(EvalResult(
            question_id=f"q{i}",
            metrics=[MetricValue(metric_name=k, value=v[i]) for k, v in values.items()],
        ))
    return EvalRun(id="r1", config_id="hybrid_semantic", results=results)


def test_aggregate_by_type_exposes_a_failing_segment():
    run = run_with(
        {"faithfulness": [0.97, 0.97, 0.60, 0.62]},
        [QuestionType.SINGLE_FACT, QuestionType.SINGLE_FACT,
         QuestionType.TABLE, QuestionType.TABLE],
    )
    questions = {
        "q0": GoldenQuestion(id="q0", question="", q_type=QuestionType.SINGLE_FACT),
        "q1": GoldenQuestion(id="q1", question="", q_type=QuestionType.SINGLE_FACT),
        "q2": GoldenQuestion(id="q2", question="", q_type=QuestionType.TABLE),
        "q3": GoldenQuestion(id="q3", question="", q_type=QuestionType.TABLE),
    }
    overall = run.aggregate()["faithfulness"]
    by_type = run.aggregate_by_type(questions)

    assert 0.78 < overall < 0.80          # looks acceptable
    assert by_type["table-dependent"]["faithfulness"] == 0.61  # is not


def test_aggregate_ignores_undefined_metric_values():
    run = EvalRun(id="r", config_id="c", results=[
        EvalResult(question_id="a", metrics=[MetricValue(metric_name="m", value=1.0)]),
        EvalResult(question_id="b", metrics=[MetricValue(metric_name="m", value=None)]),
    ])
    assert run.aggregate()["m"] == 1.0


def test_gate_passes_when_all_floors_are_met():
    run = run_with({"faithfulness": [0.9, 0.92]}, [QuestionType.SINGLE_FACT] * 2)
    outcome = evaluate_gate(run, [GateThreshold(metric="faithfulness", min_value=0.85)])
    assert outcome.passed and not outcome.failures


def test_gate_fails_below_the_floor():
    run = run_with({"faithfulness": [0.7, 0.72]}, [QuestionType.SINGLE_FACT] * 2)
    outcome = evaluate_gate(run, [GateThreshold(metric="faithfulness", min_value=0.85)])
    assert not outcome.passed
    assert "floor" in outcome.failures[0]


def test_gate_fails_on_a_regression_against_baseline():
    run = run_with({"context_recall": [0.80, 0.80]}, [QuestionType.SINGLE_FACT] * 2)
    outcome = evaluate_gate(
        run,
        [GateThreshold(metric="context_recall", max_drop_vs_baseline=0.03)],
        baseline={"context_recall": 0.87},
    )
    assert not outcome.passed
    assert "dropped" in outcome.failures[0]


def test_gate_reports_a_metric_the_run_never_produced():
    run = run_with({"faithfulness": [0.9]}, [QuestionType.SINGLE_FACT])
    outcome = evaluate_gate(run, [GateThreshold(metric="citation_validity", min_value=0.95)])
    assert not outcome.passed
    assert "not produced" in outcome.failures[0]
