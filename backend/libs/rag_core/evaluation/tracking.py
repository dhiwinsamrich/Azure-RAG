"""MLflow logging for eval runs.

This sits alongside the SQLite Store, not in place of it: the Store is the
system of record the app's own dashboard reads from, and stays that way.
MLflow adds the run-comparison view - params (what changed in the retrieval
config) next to metrics (what happened to quality) - that the CI gate and
manual `run`/`gate` invocations already compute but have nowhere to log
side-by-side across iterations.

mlflow is an optional dependency (see the `eval` extra) and a tracking
backend is infrastructure that can be down or misconfigured, so every
function here degrades to a no-op rather than ever failing the caller's
actual eval run or CI gate.
"""

from __future__ import annotations

import subprocess

from ..schemas import EvalRun, GateOutcome, RetrievalConfig


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def log_run(
    run: EvalRun,
    config: RetrievalConfig,
    *,
    tracking_uri: str,
    experiment: str,
    regression_pass_rate: float | None = None,
    gate: GateOutcome | None = None,
) -> str | None:
    """Log one EvalRun as one MLflow run. Returns the MLflow run id, or None
    if mlflow isn't installed or logging failed for any other reason."""
    try:
        import mlflow
    except ImportError:
        print("mlflow not installed - skipping tracking (pip install '.[eval]')")
        return None

    try:
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(experiment)
        with mlflow.start_run(run_name=run.id) as active:
            mlflow.set_tags({
                "config_id": config.id,
                "trigger": run.trigger,
                "eval_run_id": run.id,
                "git_sha": _git_sha(),
                "gate_passed": str(gate.passed) if gate is not None else "",
            })
            mlflow.log_params({
                "chunk_size": config.chunk_size,
                "chunk_overlap": config.chunk_overlap,
                "top_k": config.top_k,
                "rerank_top_n": config.rerank_top_n,
                "use_bm25": config.use_bm25,
                "use_vector": config.use_vector,
                "use_semantic_ranker": config.use_semantic_ranker,
                "embed_model": config.embed_model,
                "judge_model": run.judge_model,
                "n_questions": len(run.results),
            })
            for name, value in run.aggregate().items():
                mlflow.log_metric(name, value)
            if regression_pass_rate is not None:
                mlflow.log_metric("regression_pass_rate", regression_pass_rate)
            if gate is not None:
                mlflow.log_dict(gate.model_dump(), "gate_outcome.json")
            return active.info.run_id
    except Exception as exc:  # noqa: BLE001
        print(f"mlflow logging skipped: {type(exc).__name__}: {exc}")
        return None
