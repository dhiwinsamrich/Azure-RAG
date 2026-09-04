"""Evaluation CLI.

The same entry point runs locally, in the nightly job and in the CI gate - only
the metric set and the question subset change. That is deliberate: a gate that
runs different code from the nightly run measures a different system.

    python -m apps.evaluator.cli run   --config hybrid_semantic
    python -m apps.evaluator.cli gate  --config hybrid_semantic --limit 20
    python -m apps.evaluator.cli compare --metric citation_validity
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from rag_core.config import EVALS_DIR, get_config, get_settings
from rag_core.evaluation.custom import evaluate as evaluate_custom
from rag_core.evaluation.custom import false_refusal_rate
from rag_core.evaluation.gate import evaluate_gate, load_thresholds
from rag_core.evaluation.ragas_runner import judge_name
from rag_core.pipeline import RagPipeline
from rag_core.schemas import EvalResult, EvalRun, GoldenQuestion, Trace
from rag_core.store import Store, load_golden_set


def build_pipeline() -> RagPipeline:
    from rag_core.clients import build_chat, build_embedder, build_searcher

    s = get_settings()
    return RagPipeline(
        searcher=build_searcher(s), embedder=build_embedder(s),
        chat=build_chat(s), settings=s,
    )


async def answer_all(
    pipeline: RagPipeline, questions: list[GoldenQuestion], config
) -> dict[str, Trace]:
    traces: dict[str, Trace] = {}
    for q in questions:
        traces[q.id] = await pipeline.answer(q.question, config)
    return traces


def score(
    traces: dict[str, Trace],
    questions: list[GoldenQuestion],
    with_ragas: bool,
    metric_names: list[str] | None,
) -> list[EvalResult]:
    results: list[EvalResult] = []
    ragas_scores: dict[str, list] = {}

    if with_ragas:
        from rag_core.evaluation.ragas_runner import NIGHTLY_METRICS, run_ragas

        ragas_scores = run_ragas(
            traces, questions, metric_names or NIGHTLY_METRICS, get_settings()
        )

    for q in questions:
        t = traces.get(q.id)
        if t is None:
            continue
        metrics = evaluate_custom(t, q)
        metrics.extend(ragas_scores.get(q.id, []))
        results.append(EvalResult(question_id=q.id, trace_id=t.id, metrics=metrics))
    return results


def cmd_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    store = Store(args.db)
    config = get_config(args.config)

    questions = load_golden_set(args.golden_set)
    if args.limit:
        questions = questions[: args.limit]
    store.save_questions(questions)

    pipeline = build_pipeline()
    traces = asyncio.run(answer_all(pipeline, questions, config))
    for t in traces.values():
        store.save_trace(t)

    run = EvalRun(
        id=args.run_id or f"run-{uuid.uuid4().hex[:8]}",
        config_id=config.id,
        judge_model=judge_name(settings) if args.ragas else "",
        trigger=args.trigger,
        metric_set=args.metrics.split(",") if args.metrics else [],
        results=score(traces, questions, args.ragas,
                      args.metrics.split(",") if args.metrics else None),
        status="complete",
    )
    store.save_run(run)

    agg = run.aggregate()
    print(f"run {run.id}  config={config.id}  n={len(run.results)}")
    for k in sorted(agg):
        print(f"  {k:<32} {agg[k]:.3f}")
    print(f"  {'false_refusal_rate':<32} {false_refusal_rate(traces, questions):.3f}")

    by_type = run.aggregate_by_type({q.id: q for q in questions})
    if by_type:
        print("\nby question type:")
        for qt in sorted(by_type):
            parts = " ".join(f"{k}={v:.2f}" for k, v in sorted(by_type[qt].items()))
            print(f"  {qt:<18} {parts}")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    """CI gate: deterministic metrics only, compared to the stored baseline."""
    store = Store(args.db)
    config = get_config(args.config)
    questions = load_golden_set(args.golden_set)[: args.limit]
    store.save_questions(questions)

    baseline = store.baseline(config.id)
    traces = asyncio.run(answer_all(build_pipeline(), questions, config))
    run = EvalRun(
        id=f"gate-{uuid.uuid4().hex[:8]}", config_id=config.id, trigger="ci-gate",
        results=score(traces, questions, with_ragas=False, metric_names=None),
        status="complete",
    )
    store.save_run(run)

    outcome = evaluate_gate(run, load_thresholds(args.thresholds), baseline)
    print(json.dumps(outcome.model_dump(), indent=2))
    if not outcome.passed:
        print("\nQUALITY GATE FAILED", file=sys.stderr)
        for f in outcome.failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("\nquality gate passed")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    store = Store(args.db)
    rows = store.compare(args.metric)
    print(f"{args.metric}:")
    for r in rows:
        print(f"  {r['config_id']:<28} {r['value']:.3f}  (n={r['n']})")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    """Load the golden set into the store without running anything."""
    store = Store(args.db)
    questions = load_golden_set(args.golden_set)
    store.save_questions(questions)
    print(f"seeded {len(questions)} questions into {args.db}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rag-eval")
    p.add_argument("--db", default="azure_rag.db")
    p.add_argument("--golden-set", default=str(EVALS_DIR / "golden_set.yaml"))
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="full evaluation run")
    r.add_argument("--config", default="hybrid_semantic")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--ragas", action="store_true", help="include the LLM-judge suite")
    r.add_argument("--metrics", default="")
    r.add_argument("--trigger", default="manual",
                   choices=["manual", "nightly", "ci-gate", "online"])
    r.add_argument("--run-id", default="")
    r.set_defaults(func=cmd_run)

    g = sub.add_parser("gate", help="CI quality gate")
    g.add_argument("--config", default="hybrid_semantic")
    g.add_argument("--limit", type=int, default=20)
    g.add_argument("--thresholds", default=str(EVALS_DIR / "thresholds.yaml"))
    g.set_defaults(func=cmd_gate)

    c = sub.add_parser("compare", help="one metric across configs")
    c.add_argument("--metric", default="citation_validity")
    c.set_defaults(func=cmd_compare)

    s = sub.add_parser("seed", help="load the golden set into the store")
    s.set_defaults(func=cmd_seed)

    args = p.parse_args(argv)
    if not Path(args.golden_set).exists():
        print(f"golden set not found: {args.golden_set}", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
