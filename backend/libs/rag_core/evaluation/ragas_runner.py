"""RAGAS wiring, plus the judge-verdict cache.

RAGAS is an optional dependency: it is imported inside the functions so the
deterministic suite, the CI gate and the whole test suite keep working without
it installed.

Two cost controls that matter more than they look:

  * The judge is a SEPARATE, stronger deployment from the generator. A model
    grading its own output inflates faithfulness, and eval traffic competing
    with serving traffic for quota is how you get 429s in production.
  * Verdicts are cached on hash(question, answer, contexts, metric, judge).
    A full suite over 80 questions across 4 configs is several thousand judge
    calls; without the cache, re-running after a prompt tweak pays for all of
    them again.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from ..schemas import GoldenQuestion, MetricValue, Trace

# Metric names as the dashboard knows them. Keep stable - they are stored as
# rows and pivoted generically by the UI.
FAITHFULNESS = "faithfulness"
ANSWER_RELEVANCY = "answer_relevancy"
CONTEXT_PRECISION = "context_precision"
CONTEXT_RECALL = "context_recall"
CONTEXT_ENTITY_RECALL = "context_entity_recall"
NOISE_SENSITIVITY = "noise_sensitivity"
FACTUAL_CORRECTNESS = "factual_correctness"
SEMANTIC_SIMILARITY = "semantic_similarity"

# What to run when. The CI gate uses none of these - they all cost money.
NIGHTLY_METRICS = [
    FAITHFULNESS, ANSWER_RELEVANCY, CONTEXT_PRECISION, CONTEXT_RECALL,
    CONTEXT_ENTITY_RECALL, NOISE_SENSITIVITY, FACTUAL_CORRECTNESS,
    SEMANTIC_SIMILARITY,
]
# Online sampling runs the cheap end only: an NLI cross-encoder for
# faithfulness rather than an LLM judge.
ONLINE_METRICS = [FAITHFULNESS]


class JudgeCache:
    """Content-addressed cache of judge verdicts."""

    def __init__(self, path: str | Path = ".judge_cache.db") -> None:
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS verdict ("
                "key TEXT PRIMARY KEY, value REAL, reason TEXT, tokens INTEGER)"
            )
            c.commit()

    @staticmethod
    def key(question: str, answer: str, contexts: Sequence[str],
            metric: str, judge_model: str) -> str:
        blob = json.dumps(
            [question, answer, list(contexts), metric, judge_model], sort_keys=True
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, key: str) -> MetricValue | None:
        with closing(sqlite3.connect(self.path)) as c:
            row = c.execute(
                "SELECT value, reason, tokens FROM verdict WHERE key=?", (key,)
            ).fetchone()
        if not row:
            return None
        return MetricValue(metric_name="", value=row[0], reason=row[1] or "",
                           judge_tokens=row[2] or 0)

    def put(self, key: str, metric: MetricValue) -> None:
        with closing(sqlite3.connect(self.path)) as c:
            c.execute(
                "INSERT OR REPLACE INTO verdict (key, value, reason, tokens) VALUES (?,?,?,?)",
                (key, metric.value, metric.reason, metric.judge_tokens),
            )
            c.commit()


def build_dataset(traces: dict[str, Trace], questions: Sequence[GoldenQuestion]) -> list[dict]:
    """Shape traces into RAGAS's sample format.

    Unanswerable questions carry no reference, so reference-based metrics skip
    them rather than scoring a refusal against an empty string.
    """
    rows = []
    for q in questions:
        t = traces.get(q.id)
        if t is None:
            continue
        row: dict[str, Any] = {
            "user_input": q.question,
            "retrieved_contexts": t.contexts(),
            "response": t.answer,
        }
        if q.answerable and q.gold_answer:
            row["reference"] = q.gold_answer
        rows.append(row)
    return rows


def _metric_objects(names: Sequence[str], llm, embeddings) -> list:
    from ragas import metrics as M

    registry = {
        FAITHFULNESS: lambda: M.Faithfulness(llm=llm),
        ANSWER_RELEVANCY: lambda: M.ResponseRelevancy(llm=llm, embeddings=embeddings),
        CONTEXT_PRECISION: lambda: M.LLMContextPrecisionWithReference(llm=llm),
        CONTEXT_RECALL: lambda: M.LLMContextRecall(llm=llm),
        CONTEXT_ENTITY_RECALL: lambda: M.ContextEntityRecall(llm=llm),
        NOISE_SENSITIVITY: lambda: M.NoiseSensitivity(llm=llm),
        FACTUAL_CORRECTNESS: lambda: M.FactualCorrectness(llm=llm),
        SEMANTIC_SIMILARITY: lambda: M.SemanticSimilarity(embeddings=embeddings),
    }
    out = []
    for n in names:
        if n not in registry:
            raise KeyError(f"unknown RAGAS metric {n!r}; known: {sorted(registry)}")
        out.append(registry[n]())
    return out


def judge_models(settings):
    """Wrap the judge model for RAGAS.

    Note the deliberate asymmetry in both branches: the JUDGE model, never the
    generator. Temperature is pinned to 0 because judge variance is
    indistinguishable from a real quality change on the dashboard.
    """
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper

    if settings.llm_provider == "gemini":
        from langchain_google_genai import (
            ChatGoogleGenerativeAI,
            GoogleGenerativeAIEmbeddings,
        )

        from ..clients import resolve_gemini_api_key

        api_key = resolve_gemini_api_key(settings)
        llm = ChatGoogleGenerativeAI(
            model=settings.gemini_judge_model,
            google_api_key=api_key,
            temperature=0.0,
        )
        emb = GoogleGenerativeAIEmbeddings(
            model=f"models/{settings.gemini_embed_model}",
            google_api_key=api_key,
        )
        return LangchainLLMWrapper(llm), LangchainEmbeddingsWrapper(emb)

    from azure.identity import get_bearer_token_provider
    from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings

    from ..clients import credential

    token_provider = get_bearer_token_provider(
        credential(), "https://cognitiveservices.azure.com/.default"
    )
    llm = AzureChatOpenAI(
        azure_endpoint=settings.openai_endpoint,
        azure_deployment=settings.judge_deployment,
        api_version=settings.openai_api_version,
        azure_ad_token_provider=token_provider,
        temperature=0.0,
    )
    emb = AzureOpenAIEmbeddings(
        azure_endpoint=settings.openai_endpoint,
        azure_deployment=settings.embed_deployment,
        api_version=settings.openai_api_version,
        azure_ad_token_provider=token_provider,
    )
    return LangchainLLMWrapper(llm), LangchainEmbeddingsWrapper(emb)


def judge_name(settings) -> str:
    """The judge identity that goes into the verdict-cache key and the run
    record - swapping judges must invalidate cached verdicts."""
    return (settings.gemini_judge_model if settings.llm_provider == "gemini"
            else settings.judge_deployment)


def run_ragas(
    traces: dict[str, Trace],
    questions: Sequence[GoldenQuestion],
    metric_names: Sequence[str],
    settings,
    cache: JudgeCache | None = None,
    max_workers: int = 8,
) -> dict[str, list[MetricValue]]:
    """Score every question, returning {question_id: [MetricValue, ...]}.

    Cached verdicts short-circuit before any network call, so a re-run after an
    unrelated change is close to free.
    """
    from ragas import EvaluationDataset, evaluate
    from ragas.run_config import RunConfig

    cache = cache or JudgeCache()
    judge = judge_name(settings)

    ordered = [q for q in questions if q.id in traces]
    pending: list[GoldenQuestion] = []
    out: dict[str, list[MetricValue]] = {q.id: [] for q in ordered}

    for q in ordered:
        t = traces[q.id]
        missing = False
        for name in metric_names:
            hit = cache.get(cache.key(q.question, t.answer, t.contexts(), name, judge))
            if hit is None:
                missing = True
            else:
                out[q.id].append(hit.model_copy(update={"metric_name": name}))
        if missing:
            pending.append(q)

    if not pending:
        return out

    llm, embeddings = judge_models(settings)
    dataset = EvaluationDataset.from_list(build_dataset(traces, pending))
    result = evaluate(
        dataset=dataset,
        metrics=_metric_objects(metric_names, llm, embeddings),
        run_config=RunConfig(max_workers=max_workers, timeout=180),
    )

    frame = result.to_pandas()
    for row_i, q in enumerate(pending):
        t = traces[q.id]
        # Cached entries were already appended; replace this question's list.
        out[q.id] = []
        for name in metric_names:
            value = None
            if name in frame.columns:
                raw = frame.iloc[row_i][name]
                value = None if raw != raw else float(raw)  # NaN check
            mv = MetricValue(metric_name=name, value=value, reason="ragas")
            out[q.id].append(mv)
            cache.put(cache.key(q.question, t.answer, t.contexts(), name, judge), mv)

    return out
