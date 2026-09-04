"""The CI quality gate.

Compares a run's aggregates against absolute floors and against the stored
baseline, and fails the build when either is breached. Deliberately dependency
free so it runs in a pipeline step in under a second.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..schemas import EvalRun, GateOutcome, GateThreshold


def load_thresholds(path: str | Path) -> list[GateThreshold]:
    data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [
        GateThreshold(
            metric=name,
            min_value=spec.get("min"),
            max_drop_vs_baseline=spec.get("max_drop"),
        )
        for name, spec in (data.get("thresholds") or {}).items()
    ]


def evaluate_gate(
    run: EvalRun,
    thresholds: list[GateThreshold],
    baseline: dict[str, float] | None = None,
) -> GateOutcome:
    actual = run.aggregate()
    baseline = baseline or {}
    failures: list[str] = []
    details: dict[str, Any] = {}

    for t in thresholds:
        value = actual.get(t.metric)
        if value is None:
            failures.append(f"{t.metric}: not produced by this run")
            continue

        entry: dict[str, Any] = {"value": round(value, 4)}

        if t.min_value is not None:
            entry["min"] = t.min_value
            if value < t.min_value:
                failures.append(f"{t.metric}: {value:.3f} < floor {t.min_value:.3f}")

        if t.max_drop_vs_baseline is not None and t.metric in baseline:
            base = baseline[t.metric]
            drop = base - value
            entry["baseline"] = round(base, 4)
            entry["drop"] = round(drop, 4)
            if drop > t.max_drop_vs_baseline:
                failures.append(
                    f"{t.metric}: dropped {drop:.3f} vs baseline "
                    f"{base:.3f} (max {t.max_drop_vs_baseline:.3f})"
                )

        details[t.metric] = entry

    return GateOutcome(passed=not failures, failures=failures, details=details)
