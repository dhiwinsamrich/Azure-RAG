-- PostgreSQL schema. Mirrors backend/libs/rag_core/store.py, which uses SQLite
-- so the test suite and local development need no server.
--
-- The design point is eval_metric_value: metrics are ROWS, not columns.
-- Adding a RAGAS metric needs no migration and no UI change, and the dashboard
-- pivots generically.

CREATE TABLE IF NOT EXISTS document (
    id              TEXT PRIMARY KEY,
    company         TEXT,
    ticker          TEXT,
    doc_type        TEXT,
    fiscal_year     INTEGER,
    fiscal_quarter  INTEGER,
    source_url      TEXT,
    page_count      INTEGER,
    parse_status    TEXT NOT NULL DEFAULT 'queued',
    parse_error     TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS document_filters_idx
    ON document (ticker, fiscal_year, doc_type);

-- Mirror of what is in the search index, so you can join, audit and diff
-- without querying Search.
CREATE TABLE IF NOT EXISTS chunk (
    id             TEXT PRIMARY KEY,
    doc_id         TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    section_path   TEXT,
    page_start     INTEGER,
    page_end       INTEGER,
    contains_table BOOLEAN NOT NULL DEFAULT false,
    token_count    INTEGER,
    content_hash   TEXT
);
CREATE INDEX IF NOT EXISTS chunk_doc_idx ON chunk (doc_id);

-- The ablation axis. Every trace and eval result references one of these, so
-- comparing retrieval strategies is a GROUP BY.
CREATE TABLE IF NOT EXISTS retrieval_config (
    id                  TEXT PRIMARY KEY,
    name                TEXT,
    chunk_size          INTEGER,
    chunk_overlap       INTEGER,
    top_k               INTEGER,
    rerank_top_n        INTEGER,
    use_bm25            BOOLEAN,
    use_vector          BOOLEAN,
    use_semantic_ranker BOOLEAN,
    embed_model         TEXT,
    embed_dims          INTEGER,
    gen_model           TEXT,
    prompt_version      TEXT,
    payload             JSONB NOT NULL
);

-- One row per answered query, online or offline.
CREATE TABLE IF NOT EXISTS trace (
    id                 TEXT PRIMARY KEY,
    config_id          TEXT NOT NULL,
    query              TEXT NOT NULL,
    answer             TEXT,
    refused            BOOLEAN NOT NULL DEFAULT false,
    total_ms           DOUBLE PRECISION,
    retrieval_ms       DOUBLE PRECISION,
    generation_ms      DOUBLE PRECISION,
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    estimated_cost_usd DOUBLE PRECISION,
    citation_failures  INTEGER,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload            JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS trace_config_time_idx ON trace (config_id, created_at DESC);
CREATE INDEX IF NOT EXISTS trace_refused_idx ON trace (refused) WHERE refused;

CREATE TABLE IF NOT EXISTS golden_question (
    id                   TEXT PRIMARY KEY,
    question             TEXT NOT NULL,
    gold_answer          TEXT,
    gold_chunk_ids       TEXT[],
    q_type               TEXT NOT NULL,
    answerable           BOOLEAN NOT NULL DEFAULT true,
    difficulty           TEXT,
    provenance           TEXT,
    expected_fiscal_year INTEGER,
    payload              JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_run (
    id           TEXT PRIMARY KEY,
    config_id    TEXT NOT NULL,
    question_set TEXT,
    judge_model  TEXT,
    trigger      TEXT NOT NULL DEFAULT 'manual',
    status       TEXT NOT NULL DEFAULT 'running',
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS eval_run_config_idx ON eval_run (config_id, started_at DESC);

CREATE TABLE IF NOT EXISTS eval_result (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES eval_run(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL,
    trace_id    TEXT,
    UNIQUE (run_id, question_id)
);

CREATE TABLE IF NOT EXISTS eval_metric_value (
    result_id    BIGINT NOT NULL REFERENCES eval_result(id) ON DELETE CASCADE,
    metric_name  TEXT NOT NULL,
    value        DOUBLE PRECISION,
    reason       TEXT,
    judge_tokens INTEGER DEFAULT 0,
    PRIMARY KEY (result_id, metric_name)
);
CREATE INDEX IF NOT EXISTS metric_name_idx ON eval_metric_value (metric_name);

-- Structured financials with accounting-identity validation. Violations are
-- flagged, never silently accepted.
CREATE TABLE IF NOT EXISTS extraction (
    id                    BIGSERIAL PRIMARY KEY,
    doc_id                TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    field                 TEXT NOT NULL,
    value                 NUMERIC,
    unit                  TEXT,
    source_chunk_id       TEXT,
    identity_check_passed BOOLEAN,
    UNIQUE (doc_id, field)
);

-- Run aggregates, the query the dashboard's overview is built on.
CREATE OR REPLACE VIEW eval_run_summary AS
SELECT r.id            AS run_id,
       r.config_id,
       r.trigger,
       r.status,
       r.started_at,
       v.metric_name,
       AVG(v.value)    AS mean_value,
       COUNT(v.value)  AS n
FROM eval_run r
JOIN eval_result e       ON e.run_id = r.id
JOIN eval_metric_value v ON v.result_id = e.id
GROUP BY r.id, r.config_id, r.trigger, r.status, r.started_at, v.metric_name;

-- The segment breakdown: a healthy mean routinely hides a failing question
-- type, and table-dependent questions are usually the one.
CREATE OR REPLACE VIEW eval_by_question_type AS
SELECT r.id           AS run_id,
       r.config_id,
       q.q_type,
       v.metric_name,
       AVG(v.value)   AS mean_value,
       COUNT(v.value) AS n
FROM eval_run r
JOIN eval_result e       ON e.run_id = r.id
JOIN golden_question q   ON q.id = e.question_id
JOIN eval_metric_value v ON v.result_id = e.id
GROUP BY r.id, r.config_id, q.q_type, v.metric_name;
