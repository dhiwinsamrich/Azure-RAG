"""Trace and evaluation store.

SQLite via the standard library so the whole thing runs locally with no server;
the DDL is deliberately plain SQL that maps one-to-one onto the PostgreSQL
schema used in Azure (see infra/sql/schema.sql).

The design point is `eval_metric_value`: metrics are rows, not columns. Adding
a RAGAS metric needs no migration and no UI change, and the dashboard pivots
generically.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schemas import (
    Chunk,
    EvalResult,
    EvalRun,
    GoldenQuestion,
    MetricValue,
    Trace,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS retrieval_config (
    id TEXT PRIMARY KEY,
    name TEXT,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trace (
    id TEXT PRIMARY KEY,
    config_id TEXT NOT NULL,
    query TEXT NOT NULL,
    answer TEXT,
    refused INTEGER NOT NULL DEFAULT 0,
    total_ms REAL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    estimated_cost_usd REAL,
    citation_failures INTEGER,
    created_at TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS trace_config_idx ON trace(config_id, created_at);

CREATE TABLE IF NOT EXISTS document (
    id TEXT PRIMARY KEY,
    company TEXT,
    ticker TEXT,
    doc_type TEXT,
    fiscal_year INTEGER,
    page_count INTEGER,
    chunk_count INTEGER,
    indexed INTEGER NOT NULL DEFAULT 0,
    source_url TEXT,
    created_at TEXT
);

-- Mirror of what is in the search index, so the corpus can be browsed,
-- audited and diffed without querying Search.
CREATE TABLE IF NOT EXISTS chunk (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    chunk_index INTEGER,
    section_path TEXT,
    page_start INTEGER,
    page_end INTEGER,
    contains_table INTEGER,
    token_count INTEGER,
    embed_dims INTEGER,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunk_doc_idx ON chunk(doc_id, chunk_index);

CREATE TABLE IF NOT EXISTS golden_question (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_run (
    id TEXT PRIMARY KEY,
    config_id TEXT NOT NULL,
    question_set TEXT,
    judge_model TEXT,
    trigger TEXT,
    status TEXT,
    started_at TEXT
);

CREATE TABLE IF NOT EXISTS eval_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES eval_run(id),
    question_id TEXT NOT NULL,
    trace_id TEXT,
    UNIQUE(run_id, question_id)
);

-- Long-form: one row per (result, metric). New metric = new rows.
CREATE TABLE IF NOT EXISTS eval_metric_value (
    result_id INTEGER NOT NULL REFERENCES eval_result(id),
    metric_name TEXT NOT NULL,
    value REAL,
    reason TEXT,
    judge_tokens INTEGER DEFAULT 0,
    PRIMARY KEY (result_id, metric_name)
);
CREATE INDEX IF NOT EXISTS metric_name_idx ON eval_metric_value(metric_name);
"""


class Store:
    def __init__(self, path: str | Path = "azure_rag.db") -> None:
        self.path = str(path)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # -- traces ----------------------------------------------------------
    def save_trace(self, trace: Trace) -> None:
        with self.conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO trace
                   (id, config_id, query, answer, refused, total_ms, prompt_tokens,
                    completion_tokens, estimated_cost_usd, citation_failures,
                    created_at, payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    trace.id, trace.config_id, trace.query, trace.answer,
                    int(trace.refused), trace.timings.total_ms,
                    trace.usage.prompt_tokens, trace.usage.completion_tokens,
                    trace.estimated_cost_usd,
                    sum(not v.valid for v in trace.verdicts),
                    trace.created_at.isoformat(),
                    trace.model_dump_json(),
                ),
            )

    def get_trace(self, trace_id: str) -> Trace | None:
        with self.conn() as c:
            row = c.execute("SELECT payload FROM trace WHERE id=?", (trace_id,)).fetchone()
        return Trace.model_validate_json(row["payload"]) if row else None

    def recent_traces(self, limit: int = 50) -> list[Trace]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT payload FROM trace ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Trace.model_validate_json(r["payload"]) for r in rows]

    # -- corpus ----------------------------------------------------------
    def save_document(
        self, doc_id: str, meta: dict[str, Any], chunk_count: int, indexed: bool
    ) -> None:
        with self.conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO document
                   (id, company, ticker, doc_type, fiscal_year, page_count,
                    chunk_count, indexed, source_url, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (doc_id, meta.get("company", ""), meta.get("ticker", ""),
                 meta.get("doc_type", ""), meta.get("fiscal_year"),
                 meta.get("page_count", 0), chunk_count, int(indexed),
                 meta.get("source_url", ""), datetime.now(UTC).isoformat()),
            )

    def save_chunks(self, chunks: list[Chunk], embed_dims: int = 0) -> None:
        with self.conn() as c:
            c.executemany(
                """INSERT OR REPLACE INTO chunk
                   (id, doc_id, chunk_index, section_path, page_start, page_end,
                    contains_table, token_count, embed_dims, payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [(ch.id, ch.metadata.doc_id, ch.metadata.chunk_index,
                  ch.metadata.section_path, ch.metadata.page_start,
                  ch.metadata.page_end, int(ch.metadata.contains_table),
                  ch.token_count, embed_dims, ch.model_dump_json())
                 for ch in chunks],
            )

    def documents(self) -> list[dict[str, Any]]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM document ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def chunks(self, doc_id: str) -> list[Chunk]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT payload FROM chunk WHERE doc_id=? ORDER BY chunk_index",
                (doc_id,),
            ).fetchall()
        return [Chunk.model_validate_json(r["payload"]) for r in rows]

    def chunk_dims(self, doc_id: str) -> int:
        with self.conn() as c:
            row = c.execute(
                "SELECT MAX(embed_dims) AS d FROM chunk WHERE doc_id=?", (doc_id,)
            ).fetchone()
        return int(row["d"] or 0)

    def delete_document(self, doc_id: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM chunk WHERE doc_id=?", (doc_id,))
            c.execute("DELETE FROM document WHERE id=?", (doc_id,))

    # -- golden set ------------------------------------------------------
    def save_questions(self, questions: Iterable[GoldenQuestion]) -> None:
        with self.conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO golden_question (id, payload) VALUES (?,?)",
                [(q.id, q.model_dump_json()) for q in questions],
            )

    def questions(self) -> list[GoldenQuestion]:
        with self.conn() as c:
            rows = c.execute("SELECT payload FROM golden_question ORDER BY id").fetchall()
        return [GoldenQuestion.model_validate_json(r["payload"]) for r in rows]

    # -- eval runs -------------------------------------------------------
    def save_run(self, run: EvalRun) -> None:
        with self.conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO eval_run
                   (id, config_id, question_set, judge_model, trigger, status, started_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (run.id, run.config_id, run.question_set, run.judge_model,
                 run.trigger, run.status, run.started_at.isoformat()),
            )
            for result in run.results:
                cur = c.execute(
                    """INSERT OR REPLACE INTO eval_result (run_id, question_id, trace_id)
                       VALUES (?,?,?)""",
                    (run.id, result.question_id, result.trace_id),
                )
                rid = cur.lastrowid
                c.executemany(
                    """INSERT OR REPLACE INTO eval_metric_value
                       (result_id, metric_name, value, reason, judge_tokens)
                       VALUES (?,?,?,?,?)""",
                    [(rid, m.metric_name, m.value, m.reason, m.judge_tokens)
                     for m in result.metrics],
                )

    def get_run(self, run_id: str) -> EvalRun | None:
        with self.conn() as c:
            row = c.execute("SELECT * FROM eval_run WHERE id=?", (run_id,)).fetchone()
            if not row:
                return None
            results: list[EvalResult] = []
            for r in c.execute(
                "SELECT id, question_id, trace_id FROM eval_result WHERE run_id=?", (run_id,)
            ).fetchall():
                metrics = [
                    MetricValue(metric_name=m["metric_name"], value=m["value"],
                                reason=m["reason"] or "", judge_tokens=m["judge_tokens"] or 0)
                    for m in c.execute(
                        "SELECT * FROM eval_metric_value WHERE result_id=?", (r["id"],)
                    ).fetchall()
                ]
                results.append(EvalResult(question_id=r["question_id"],
                                          trace_id=r["trace_id"] or "", metrics=metrics))
        return EvalRun(
            id=row["id"], config_id=row["config_id"],
            question_set=row["question_set"] or "golden",
            judge_model=row["judge_model"] or "", trigger=row["trigger"] or "manual",
            status=row["status"] or "complete", results=results,
        )

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Run history with aggregates, document attribution and question breakdown."""
        with self.conn() as c:
            rows = c.execute(
                """SELECT r.id, r.config_id, r.question_set, r.judge_model, r.trigger, r.status, r.started_at,
                          v.metric_name, AVG(v.value) AS mean_value, COUNT(v.value) AS n
                   FROM eval_run r
                   LEFT JOIN eval_result e ON e.run_id = r.id
                   LEFT JOIN eval_metric_value v ON v.result_id = e.id
                   GROUP BY r.id, v.metric_name
                   ORDER BY r.started_at DESC""",
            ).fetchall()

            # Load question metadata to attribute target documents and question types
            q_rows = c.execute("SELECT id, payload FROM golden_question").fetchall()
            q_map: dict[str, dict[str, Any]] = {}
            for qr in q_rows:
                try:
                    q_map[qr["id"]] = json.loads(qr["payload"])
                except Exception:
                    pass

            run_q_rows = c.execute("SELECT run_id, question_id FROM eval_result").fetchall()
            run_docs: dict[str, set[str]] = {}
            run_qtypes: dict[str, dict[str, int]] = {}
            run_qcounts: dict[str, set[str]] = {}
            for rq in run_q_rows:
                rid = rq["run_id"]
                qid = rq["question_id"]
                run_qcounts.setdefault(rid, set()).add(qid)
                qinfo = q_map.get(qid)
                if qinfo:
                    qt = qinfo.get("q_type", "other")
                    qtype_dict = run_qtypes.setdefault(rid, {})
                    qtype_dict[qt] = qtype_dict.get(qt, 0) + 1
                    for ch_id in qinfo.get("gold_chunk_ids", []):
                        doc_id = ch_id.split("::")[0]
                        if doc_id:
                            run_docs.setdefault(rid, set()).add(doc_id)

        runs: dict[str, dict[str, Any]] = {}
        for r in rows:
            entry = runs.setdefault(r["id"], {
                "id": r["id"],
                "config_id": r["config_id"],
                "trigger": r["trigger"],
                "status": r["status"],
                "started_at": r["started_at"],
                "question_set": r["question_set"] or "golden",
                "judge_model": r["judge_model"] or "",
                "question_count": len(run_qcounts.get(r["id"], set())),
                "doc_ids": sorted(list(run_docs.get(r["id"], set()))),
                "question_types": run_qtypes.get(r["id"], {}),
                "metrics": {},
            })
            if r["metric_name"]:
                entry["metrics"][r["metric_name"]] = round(r["mean_value"], 4)
        return list(runs.values())[:limit]

    def compare(self, metric: str) -> list[dict[str, Any]]:
        """Mean of one metric per retrieval config - the ablation matrix cell."""
        with self.conn() as c:
            rows = c.execute(
                """SELECT r.config_id, AVG(v.value) AS mean_value, COUNT(v.value) AS n
                   FROM eval_run r
                   JOIN eval_result e ON e.run_id = r.id
                   JOIN eval_metric_value v ON v.result_id = e.id
                   WHERE v.metric_name = ?
                   GROUP BY r.config_id
                   ORDER BY mean_value DESC""",
                (metric,),
            ).fetchall()
        return [
            {"config_id": r["config_id"], "value": round(r["mean_value"], 4), "n": r["n"]}
            for r in rows
        ]

    def baseline(self, config_id: str) -> dict[str, float]:
        """Most recent complete run's aggregates, for the CI gate to compare to."""
        with self.conn() as c:
            row = c.execute(
                """SELECT id FROM eval_run
                   WHERE config_id=? AND status='complete'
                   ORDER BY started_at DESC LIMIT 1""",
                (config_id,),
            ).fetchone()
            if not row:
                return {}
            rows = c.execute(
                """SELECT v.metric_name, AVG(v.value) AS mean_value
                   FROM eval_result e JOIN eval_metric_value v ON v.result_id = e.id
                   WHERE e.run_id = ? GROUP BY v.metric_name""",
                (row["id"],),
            ).fetchall()
        return {r["metric_name"]: r["mean_value"] for r in rows if r["mean_value"] is not None}


def load_golden_set(path: str | Path) -> list[GoldenQuestion]:
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [GoldenQuestion.model_validate(q) for q in data.get("questions", [])]


def dump_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)
