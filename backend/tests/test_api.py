"""End-to-end API tests driven entirely by fakes - no Azure, no credentials.

This is the payoff of injecting the pipeline's collaborators: the same code
path that serves production is exercised here.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from rag_core.config import BUILTIN_CONFIGS
from rag_core.indexing import chunk_to_document
from rag_core.pipeline import RagPipeline
from rag_core.schemas import Chunk, ChunkMetadata, DocType
from rag_core.store import Store


class FakeEmbedder:
    async def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeSearcher:
    def __init__(self, docs):
        self.docs = docs
        self.last_request = None

    async def search(self, **kwargs):
        self.last_request = kwargs
        top = kwargs.get("top", 10)
        return self.docs[:top]


class FakeChat:
    def __init__(self, payload):
        self.payload = payload

    async def complete(self, messages, schema=None):
        self.messages = messages
        return json.dumps(self.payload), 900, 120


def build_docs():
    meta = ChunkMetadata(
        doc_id="MSFT-10K-FY23", company="Microsoft Corporation", ticker="MSFT",
        doc_type=DocType.TEN_K, fiscal_year=2023, section_path="Item 7",
        page_start=34, page_end=34,
    )
    chunks = [
        Chunk(id="MSFT-10K-FY23::0001",
              content="Gross margin was 69.8% in fiscal year 2023, compared with 68.4% in fiscal year 2022.",
              metadata=meta),
        Chunk(id="MSFT-10K-FY23::0002",
              content="Intelligent Cloud revenue was $87,907 million in FY23.",
              metadata=meta),
    ]
    docs = []
    for i, c in enumerate(chunks):
        d = chunk_to_document(c)
        d["@search.score"] = 1.0 - i * 0.1
        d["@search.reranker_score"] = 3.4 - i * 0.5
        docs.append(d)
    return docs


@pytest.fixture
def client(tmp_path):
    from apps.api import deps
    from apps.api.main import app

    deps.reset()
    pipeline = RagPipeline(
        searcher=FakeSearcher(build_docs()),
        embedder=FakeEmbedder(),
        chat=FakeChat({
            "answer": "Gross margin rose to 69.8% in FY23.",
            "citations": [{"chunk_id": "MSFT-10K-FY23::0001",
                           "quoted_span": "Gross margin was 69.8%"}],
            "refused": False,
        }),
        known_tickers=("MSFT",),
    )
    deps.configure(pipeline=pipeline, store=Store(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c
    deps.reset()


def parse_sse(text: str) -> dict[str, list]:
    events: dict[str, list] = {}
    for block in text.strip().split("\n\n"):
        name = payload = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
        if name:
            events.setdefault(name, []).append(payload)
    return events


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_chat_streams_tokens_citations_validation_and_trace(client):
    r = client.post("/api/chat", json={"query": "MSFT FY23 gross margin"})
    assert r.status_code == 200
    events = parse_sse(r.text)

    assert {"start", "token", "citations", "validation", "trace", "done"} <= set(events)
    answer = "".join(e["text"] for e in events["token"])
    assert "69.8%" in answer
    assert events["validation"][0]["validity"] == 1.0
    assert events["validation"][0]["failures"] == 0
    assert events["trace"][0]["chunks_retrieved"] == 2


def test_chat_reports_the_filters_it_extracted(client):
    r = client.post("/api/chat", json={"query": "MSFT FY23 gross margin"})
    trace = parse_sse(r.text)["trace"][0]
    assert 2023 in trace["filters"]["fiscal_years"]


def test_fabricated_citation_is_reported_as_a_validation_failure(client, tmp_path):
    from apps.api import deps
    from apps.api.main import app

    deps.reset()
    deps.configure(
        pipeline=RagPipeline(
            searcher=FakeSearcher(build_docs()),
            embedder=FakeEmbedder(),
            chat=FakeChat({
                "answer": "Gross margin was 88%.",
                "citations": [{"chunk_id": "GHOST::9999", "quoted_span": "Gross margin was 88%"}],
                "refused": False,
            }),
        ),
        store=Store(tmp_path / "t2.db"),
    )
    with TestClient(app) as c:
        events = parse_sse(c.post("/api/chat", json={"query": "margin"}).text)

    v = events["validation"][0]
    assert v["failures"] == 1
    assert v["verdicts"][0]["reason"] == "unknown_chunk"
    assert events["citations"][0] == []  # dropped from the rendered answer
    deps.reset()


def test_trace_is_persisted_and_retrievable(client):
    trace_id = parse_sse(client.post("/api/chat", json={"query": "margin"}).text)["done"][0][
        "trace_id"
    ]
    r = client.get(f"/api/traces/{trace_id}")
    assert r.status_code == 200
    assert r.json()["query"] == "margin"

    assert client.get("/api/traces/nope").status_code == 404


def test_search_endpoint_exposes_per_retriever_scores(client):
    r = client.post("/api/search", json={"query": "MSFT FY23 gross margin"})
    body = r.json()
    assert body["odata_filter"] and "MSFT" in body["odata_filter"]
    assert body["results"][0]["rerank_score"] == 3.4


def test_configs_endpoint_lists_the_ablation_arms(client):
    ids = {c["id"] for c in client.get("/api/configs").json()}
    assert set(BUILTIN_CONFIGS) <= ids


def test_unknown_config_id_is_rejected(client):
    with pytest.raises(KeyError):
        client.post("/api/chat", json={"query": "x", "config_id": "nope"})
