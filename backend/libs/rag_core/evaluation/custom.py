"""Custom evaluators - the domain-specific half of the metric suite.

Every metric here is deterministic and free: no LLM judge, no embedding call.
That is what makes them usable in the CI gate and on sampled production
traffic, where the RAGAS LLM metrics would be too slow and too expensive.
"""

from __future__ import annotations

from ..citations import citation_validity as _citation_validity
from ..numerics import figures_match, period_matches
from ..schemas import GoldenQuestion, MetricValue, Trace

# Names are the registry keys the dashboard pivots on; keep them stable.
CITATION_VALIDITY = "citation_validity"
CITATION_PRECISION = "citation_precision"
CITATION_RECALL = "citation_recall"
NUMERIC_EXACTNESS = "numeric_exactness"
FISCAL_PERIOD = "fiscal_period_correctness"
REFUSAL_CORRECT = "refusal_correct"
CONTEXT_HIT_RATE = "context_hit_rate"
MRR = "mrr"

ALL_METRICS = [
    CITATION_VALIDITY, CITATION_PRECISION, CITATION_RECALL,
    NUMERIC_EXACTNESS, FISCAL_PERIOD, REFUSAL_CORRECT,
    CONTEXT_HIT_RATE, MRR,
]


def citation_validity(trace: Trace) -> MetricValue:
    if not trace.verdicts:
        return MetricValue(
            metric_name=CITATION_VALIDITY,
            value=1.0 if trace.refused else None,
            reason="refusal, no citations expected" if trace.refused else "no citations returned",
        )
    bad = [v for v in trace.verdicts if not v.valid]
    return MetricValue(
        metric_name=CITATION_VALIDITY,
        value=_citation_validity(trace.verdicts),
        reason="; ".join(f"{v.chunk_id}: {v.reason}" for v in bad) or "all citations verified",
    )


def citation_precision_recall(
    trace: Trace, question: GoldenQuestion
) -> list[MetricValue]:
    """Cited-the-right-thing, as distinct from cited-something-real."""
    gold = set(question.gold_chunk_ids)
    cited = {c.chunk_id for c in trace.citations}
    if not gold:
        return []
    hit = cited & gold
    precision = len(hit) / len(cited) if cited else 0.0
    recall = len(hit) / len(gold)
    reason = f"cited {sorted(cited) or '-'} / gold {sorted(gold)}"
    return [
        MetricValue(metric_name=CITATION_PRECISION, value=precision, reason=reason),
        MetricValue(metric_name=CITATION_RECALL, value=recall, reason=reason),
    ]


def numeric_exactness(trace: Trace, question: GoldenQuestion) -> MetricValue:
    """Are the gold figures present at the right scale?

    Skipped when the gold answer carries no figures - scoring 0 for a
    qualitative question would be noise, not signal.
    """
    expected = " ".join([question.gold_answer, *question.expected_values]).strip()
    from ..numerics import parse_figures

    if not parse_figures(expected):
        return MetricValue(
            metric_name=NUMERIC_EXACTNESS, value=None, reason="no figures in gold answer"
        )
    ok = figures_match(expected, trace.answer)
    return MetricValue(
        metric_name=NUMERIC_EXACTNESS,
        value=1.0 if ok else 0.0,
        reason="figures match at correct scale" if ok else "figure missing or wrong scale",
    )


def fiscal_period_correctness(trace: Trace, question: GoldenQuestion) -> MetricValue:
    if question.expected_fiscal_year is None:
        return MetricValue(metric_name=FISCAL_PERIOD, value=None, reason="no period expected")
    ok = period_matches(question.expected_fiscal_year, trace.answer)
    return MetricValue(
        metric_name=FISCAL_PERIOD,
        value=1.0 if ok else 0.0,
        reason=f"expected FY{question.expected_fiscal_year}",
    )


def refusal_correct(trace: Trace, question: GoldenQuestion) -> MetricValue:
    """Both directions matter.

    A system that refuses everything scores 1.0 on the unanswerable subset and
    is useless, so the answerable subset is scored with the same metric and the
    aggregate reports false refusals separately.
    """
    should_refuse = not question.answerable
    ok = trace.refused == should_refuse
    if should_refuse:
        reason = "correctly refused" if ok else "answered an unanswerable question"
    else:
        reason = "correctly answered" if ok else "false refusal"
    return MetricValue(metric_name=REFUSAL_CORRECT, value=1.0 if ok else 0.0, reason=reason)


def retrieval_metrics(trace: Trace, question: GoldenQuestion) -> list[MetricValue]:
    """Hit-rate@k and MRR against the recorded gold chunks - free, and the
    fastest tripwire for a chunking or indexing regression."""
    gold = set(question.gold_chunk_ids)
    if not gold:
        return []
    ids = trace.retrieved_ids()
    hit = 1.0 if gold & set(ids) else 0.0
    rr = 0.0
    for i, cid in enumerate(ids, start=1):
        if cid in gold:
            rr = 1.0 / i
            break
    return [
        MetricValue(metric_name=CONTEXT_HIT_RATE, value=hit,
                    reason=f"{len(gold & set(ids))}/{len(gold)} gold chunks retrieved"),
        MetricValue(metric_name=MRR, value=rr,
                    reason="first gold chunk at rank %s" % (int(1 / rr) if rr else "none")),
    ]


def evaluate(trace: Trace, question: GoldenQuestion) -> list[MetricValue]:
    """Run the full deterministic suite for one question."""
    out: list[MetricValue] = [
        citation_validity(trace),
        numeric_exactness(trace, question),
        fiscal_period_correctness(trace, question),
        refusal_correct(trace, question),
    ]
    out.extend(citation_precision_recall(trace, question))
    out.extend(retrieval_metrics(trace, question))
    return out


def false_refusal_rate(traces: dict[str, Trace], questions: list[GoldenQuestion]) -> float:
    """Share of answerable questions the system refused."""
    answerable = [q for q in questions if q.answerable and q.id in traces]
    if not answerable:
        return 0.0
    return sum(traces[q.id].refused for q in answerable) / len(answerable)
