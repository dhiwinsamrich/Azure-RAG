"""MLflow logging: no-op without the optional dependency, real when present."""

from __future__ import annotations

import pytest
from rag_core.evaluation.tracking import get_run, log_run
from rag_core.schemas import EvalResult, EvalRun, GateOutcome, MetricValue, RetrievalConfig


def _run(config_id: str = "hybrid_rrf") -> EvalRun:
    return EvalRun(
        id="run-test-1",
        config_id=config_id,
        trigger="manual",
        results=[
            EvalResult(
                question_id="Q1", trace_id="t1",
                metrics=[MetricValue(metric_name="citation_validity", value=1.0)],
            ),
        ],
        status="complete",
    )


def test_log_run_is_a_no_op_without_mlflow_installed(monkeypatch, tmp_path):
    import builtins

    real_import = builtins.__import__

    def blocked(name, *a, **kw):
        if name == "mlflow":
            raise ImportError("mlflow not installed")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", blocked)

    result = log_run(
        _run(), RetrievalConfig(id="hybrid_rrf"),
        tracking_uri=f"sqlite:///{tmp_path / 'mlflow.db'}", experiment="test",
    )
    assert result is None


def test_log_run_persists_params_metrics_and_tags(tmp_path):
    pytest.importorskip("mlflow")
    import mlflow

    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    run = _run(config_id="vector_only")
    config = RetrievalConfig(id="vector_only", use_bm25=False, use_semantic_ranker=False)
    gate = GateOutcome(passed=True, failures=[], details={"citation_validity": {"value": 1.0}})

    run_id = log_run(
        run, config, tracking_uri=uri, experiment="test-exp",
        regression_pass_rate=0.97, gate=gate,
    )
    assert run_id is not None

    mlflow.set_tracking_uri(uri)
    rows = mlflow.search_runs(experiment_names=["test-exp"])
    assert len(rows) == 1
    assert rows.loc[0, "tags.config_id"] == "vector_only"
    assert rows.loc[0, "tags.eval_run_id"] == "run-test-1"
    assert rows.loc[0, "metrics.citation_validity"] == 1.0
    assert rows.loc[0, "metrics.regression_pass_rate"] == 0.97
    assert rows.loc[0, "params.use_bm25"] == "False"


def test_get_run_returns_full_detail_including_the_gate_artifact(tmp_path):
    pytest.importorskip("mlflow")

    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    run = _run(config_id="hybrid_semantic")
    config = RetrievalConfig(id="hybrid_semantic")
    gate = GateOutcome(
        passed=False, failures=["mrr: 0.500 < floor 0.600"],
        details={"mrr": {"value": 0.5, "min": 0.6}},
    )

    run_id = log_run(run, config, tracking_uri=uri, experiment="test-detail", gate=gate)
    assert run_id is not None

    detail = get_run(uri, run_id)
    assert detail is not None
    assert detail["config_id"] == "hybrid_semantic"
    assert detail["params"]["top_k"] == "10"
    assert detail["gate_outcome"]["passed"] is False
    assert detail["gate_outcome"]["details"]["mrr"]["value"] == 0.5


def test_get_run_is_none_for_an_unknown_run_id(tmp_path):
    pytest.importorskip("mlflow")
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    assert get_run(uri, "does-not-exist") is None


def test_log_run_never_raises_on_a_bad_tracking_uri():
    # A tracking backend being unreachable must not fail the eval run that
    # triggered logging - this is a side-observation, not part of the result.
    result = log_run(
        _run(), RetrievalConfig(id="hybrid_rrf"),
        tracking_uri="not-a-real-uri://nope", experiment="test",
    )
    assert result is None
