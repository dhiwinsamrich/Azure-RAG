"""Service adapters: Gemini or Azure OpenAI for the model calls, Azure for
search, parsing and storage.

Every SDK import is deferred into a method so that importing `rag_core` costs
nothing and the pure-logic test suite runs with no SDKs installed and no
credentials. Adapters satisfy the `ChatModel` / `Embedder` / `Searcher`
protocols, so swapping providers is a settings change, not a rewrite.

Auth differs by service, deliberately:
  * Azure services prefer DefaultAzureCredential - your `az login` locally,
    the managed identity in Container Apps - and fall back to an admin key
    (`search_credential` / `docintel_credential`) only when one is explicitly
    configured. The key path exists for a portfolio setup that has not gone
    through RBAC yet; production should leave those settings empty.
  * The Gemini API is key-based. The key stays out of config and images by
    living in Key Vault and being fetched at runtime with that same managed
    identity (`resolve_gemini_api_key`).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Sequence
from typing import Any, Protocol

from .config import Settings, get_settings


def credential():
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential(exclude_interactive_browser_credential=False)


def search_credential(settings: Settings | None = None):
    s = settings or get_settings()
    key = s.search_key.get_secret_value() if hasattr(s.search_key, "get_secret_value") else str(s.search_key)
    if key:
        from azure.core.credentials import AzureKeyCredential

        return AzureKeyCredential(key)
    return credential()


def docintel_credential(settings: Settings | None = None):
    s = settings or get_settings()
    key = s.doc_intelligence_key.get_secret_value() if hasattr(s.doc_intelligence_key, "get_secret_value") else str(s.doc_intelligence_key)
    if key:
        from azure.core.credentials import AzureKeyCredential

        return AzureKeyCredential(key)
    return credential()


# --------------------------------------------------------------------------
# Protocols - the apps depend on these, so tests can substitute fakes.
# --------------------------------------------------------------------------

class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class Searcher(Protocol):
    async def search(self, **kwargs: Any) -> list[dict[str, Any]]: ...


class ChatModel(Protocol):
    async def complete(
        self, messages: list[dict[str, str]], schema: dict[str, Any] | None = None
    ) -> tuple[str, int, int]:
        """Return (raw_text, prompt_tokens, completion_tokens).

        `schema` is the provider-neutral JSON schema from
        `generation.answer_schema()`; each adapter wraps it in its own envelope.
        """
        ...


# --------------------------------------------------------------------------
# Retry
# --------------------------------------------------------------------------

async def with_backoff(fn, *, attempts: int = 6, base: float = 1.0, cap: float = 60.0):
    """Retry on 429/5xx with exponential backoff and full jitter.

    First bulk ingestion will hit the embedding rate limit; this is what makes
    that survivable rather than a restart.
    """
    last: Exception | None = None
    for i in range(attempts):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 - SDK raises varied types
            status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
            retryable = status in (408, 429, 500, 502, 503, 504) or status is None
            if not retryable or i == attempts - 1:
                raise
            last = exc
            delay = min(cap, base * (2 ** i))
            await asyncio.sleep(random.uniform(0, delay))
    if last:
        raise last


# --------------------------------------------------------------------------
# Azure OpenAI
# --------------------------------------------------------------------------

class AzureOpenAIEmbedder:
    """Batched embeddings. Batch size is bounded by the service's per-request
    input cap, not by anything we choose."""

    def __init__(self, settings: Settings | None = None, batch_size: int = 256) -> None:
        self.s = settings or get_settings()
        self.batch_size = batch_size
        self._client = None

    def _get(self):
        if self._client is None:
            from azure.identity import get_bearer_token_provider
            from openai import AsyncAzureOpenAI

            self._client = AsyncAzureOpenAI(
                azure_endpoint=self.s.openai_endpoint,
                api_version=self.s.openai_api_version,
                azure_ad_token_provider=get_bearer_token_provider(
                    credential(), "https://cognitiveservices.azure.com/.default"
                ),
            )
        return self._client

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        client = self._get()
        for i in range(0, len(texts), self.batch_size):
            batch = list(texts[i:i + self.batch_size])

            async def call(b=batch):
                return await client.embeddings.create(
                    model=self.s.embed_deployment, input=b, dimensions=self.s.embed_dims
                )

            resp = await with_backoff(call)
            out.extend(d.embedding for d in resp.data)
        return out


class AzureOpenAIChat:
    def __init__(self, settings: Settings | None = None, deployment: str | None = None) -> None:
        self.s = settings or get_settings()
        self.deployment = deployment or self.s.chat_deployment
        self._client = None

    def _get(self):
        if self._client is None:
            from azure.identity import get_bearer_token_provider
            from openai import AsyncAzureOpenAI

            self._client = AsyncAzureOpenAI(
                azure_endpoint=self.s.openai_endpoint,
                api_version=self.s.openai_api_version,
                azure_ad_token_provider=get_bearer_token_provider(
                    credential(), "https://cognitiveservices.azure.com/.default"
                ),
            )
        return self._client

    async def complete(
        self, messages: list[dict[str, str]], schema: dict[str, Any] | None = None
    ) -> tuple[str, int, int]:
        client = self._get()
        response_format = None
        if schema is not None:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "grounded_answer", "strict": True, "schema": schema,
                },
            }

        async def call():
            return await client.chat.completions.create(
                model=self.deployment,
                messages=messages,
                response_format=response_format,
                temperature=0.0,
            )

        resp = await with_backoff(call)
        usage = resp.usage
        return (
            resp.choices[0].message.content or "",
            getattr(usage, "prompt_tokens", 0),
            getattr(usage, "completion_tokens", 0),
        )


# --------------------------------------------------------------------------
# Azure AI Search
# --------------------------------------------------------------------------

class AzureSearcher:
    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()
        self._client = None

    def _get(self):
        if self._client is None:
            from azure.search.documents.aio import SearchClient

            self._client = SearchClient(
                endpoint=self.s.search_endpoint,
                index_name=self.s.search_index,
                credential=search_credential(self.s),
            )
        return self._client

    async def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        client = self._get()

        async def call():
            results = await client.search(**kwargs)
            return [dict(r) async for r in results]

        return await with_backoff(call)

    async def upload(self, documents: list[dict[str, Any]]) -> int:
        client = self._get()

        async def call():
            return await client.merge_or_upload_documents(documents=documents)

        result = await with_backoff(call)
        return sum(1 for r in result if getattr(r, "succeeded", True))

    async def delete_document(self, doc_id: str) -> int:
        """Delete every chunk belonging to a document.

        Azure AI Search deletes by key, so the chunk ids are collected first.
        Paged, because a long filing can produce far more chunks than one
        response returns.
        """
        client = self._get()
        safe = doc_id.replace("'", "''")

        async def fetch_ids():
            results = await client.search(
                search_text="*", filter=f"doc_id eq '{safe}'",
                select=["id"], top=1000,
            )
            return [r["id"] async for r in results]

        deleted = 0
        while True:
            ids = await with_backoff(fetch_ids)
            if not ids:
                break

            async def purge(batch=ids):
                return await client.delete_documents(
                    documents=[{"id": i} for i in batch]
                )

            await with_backoff(purge)
            deleted += len(ids)
            if len(ids) < 1000:
                break
        return deleted

    async def list_documents(self) -> list[dict[str, Any]]:
        """Distinct documents in the index, via a faceted match-all query.

        Facets return counts without pulling every chunk back, so this stays
        cheap as the corpus grows.
        """
        client = self._get()

        async def call():
            results = await client.search(
                search_text="*", top=0,
                facets=["doc_id,count:200", "doc_type", "fiscal_year"],
            )
            facets = await results.get_facets()
            return facets or {}

        facets = await with_backoff(call)
        return sorted(
            (
                {"doc_id": f["value"], "chunk_count": f["count"],
                 "company": "", "ticker": "", "doc_type": "",
                 "fiscal_year": None, "has_vectors": True}
                for f in facets.get("doc_id", [])
            ),
            key=lambda e: e["doc_id"],
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()


def create_or_update_index(settings: Settings | None = None) -> str:
    """Create the search index from `indexing.index_definition`.

    The index schema lives in the repo and deploys like everything else, so a
    field change is reviewable in a diff.

    Note this is create-or-UPDATE: Azure AI Search will not change a vector
    field's dimensions on an existing index. Changing `embed_dims` means a new
    index name and a re-embed, not an update.
    """
    from azure.search.documents.indexes import SearchIndexClient

    from .indexing import build_search_index

    s = settings or get_settings()
    index = build_search_index(
        s.search_index, s.embed_dims, include_semantic=s.enable_semantic_ranker
    )
    client = SearchIndexClient(endpoint=s.search_endpoint, credential=search_credential(s))
    result = client.create_or_update_index(index)
    return result.name


# --------------------------------------------------------------------------
# Document Intelligence
# --------------------------------------------------------------------------

class DocumentIntelligenceParser:
    """prebuilt-layout in markdown mode.

    Layout, not read: tables come back as structured cells with spans, section
    headings give chunk boundaries, and bounding regions give real citations.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()
        self._client = None

    def _get(self):
        if self._client is None:
            from azure.ai.documentintelligence.aio import DocumentIntelligenceClient

            self._client = DocumentIntelligenceClient(
                endpoint=self.s.doc_intelligence_endpoint, credential=docintel_credential(self.s)
            )
        return self._client

    async def analyze(self, content: bytes) -> dict[str, Any]:
        """Submit and poll. This is a long-running operation - budget for it in
        the ingest job, and record the resume point per document."""
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest

        client = self._get()

        async def call():
            poller = await client.begin_analyze_document(
                "prebuilt-layout",
                AnalyzeDocumentRequest(bytes_source=content),
                output_content_format="markdown",
            )
            return await poller.result()

        result = await with_backoff(call, attempts=4, base=2.0)
        return result.as_dict() if hasattr(result, "as_dict") else dict(result)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()


# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------

def resolve_gemini_api_key(settings: Settings | None = None) -> str:
    """Environment first, then Key Vault.

    Locally the key comes from `.env`. In Azure the container holds no key at
    all: it authenticates to Key Vault with its managed identity and fetches
    the secret at startup, so the key never appears in container config, an
    image layer, or a pipeline variable.
    """
    s = settings or get_settings()
    env_key = s.gemini_api_key.get_secret_value()
    if env_key:
        return env_key

    if not s.key_vault_uri:
        raise RuntimeError(
            "No Gemini API key. Set GEMINI_API_KEY, or set KEY_VAULT_URI so the "
            "managed identity can fetch it from Key Vault."
        )

    from azure.keyvault.secrets import SecretClient

    client = SecretClient(vault_url=s.key_vault_uri, credential=credential())
    return client.get_secret(s.gemini_api_key_secret_name).value or ""


def _gemini_client(settings: Settings):
    from google import genai

    return genai.Client(api_key=resolve_gemini_api_key(settings))


class GeminiChat:
    """Generation via the Interactions API.

    The SDK call is synchronous, so it is run in a worker thread rather than
    assuming an async surface exists for this endpoint - it is a network call,
    so the thread is parked on I/O and the event loop stays free.
    """

    def __init__(self, settings: Settings | None = None, model: str | None = None) -> None:
        self.s = settings or get_settings()
        self.model = model or self.s.gemini_chat_model
        self._client = None

    def _get(self):
        if self._client is None:
            self._client = _gemini_client(self.s)
        return self._client

    async def complete(
        self, messages: list[dict[str, str]], schema: dict[str, Any] | None = None
    ) -> tuple[str, int, int]:
        from .generation import split_messages

        system, user = split_messages(messages)
        client = self._get()

        kwargs: dict[str, Any] = {
            "model": self.model,
            "input": user,
            "generation_config": {"temperature": 0.0},
        }
        if system:
            kwargs["system_instruction"] = system
        if schema is not None:
            kwargs["response_format"] = {
                "type": "text",
                "mime_type": "application/json",
                "schema": schema,
            }

        async def call():
            return await asyncio.to_thread(lambda: client.interactions.create(**kwargs))

        interaction = await with_backoff(call)
        usage = getattr(interaction, "usage", None)
        return (
            getattr(interaction, "output_text", "") or "",
            int(getattr(usage, "total_input_tokens", 0) or 0),
            int(getattr(usage, "total_output_tokens", 0) or 0),
        )


class GeminiEmbedder:
    """Batched embeddings.

    IMPORTANT: this relies on the model returning ONE embedding PER input
    string. `gemini-embedding-001` does. `gemini-embedding-2` instead returns a
    single aggregated embedding for a list of inputs - passing a batch of
    chunks to it would silently produce one vector for the whole batch and
    corrupt the index. The count assertion below turns that into a loud failure
    rather than a quiet one.
    """

    AGGREGATING_MODELS = ("gemini-embedding-2",)

    def __init__(
        self, settings: Settings | None = None, batch_size: int = 100
    ) -> None:
        self.s = settings or get_settings()
        self.model = self.s.gemini_embed_model
        self.batch_size = batch_size
        self._client = None

        if any(self.model.startswith(m) for m in self.AGGREGATING_MODELS):
            raise ValueError(
                f"{self.model!r} returns a single aggregated embedding for a list of "
                "inputs and cannot be used for per-chunk embedding. Use "
                "gemini-embedding-001, or embed one chunk per call."
            )

    def _get(self):
        if self._client is None:
            self._client = _gemini_client(self.s)
        return self._client

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        from google.genai import types

        client = self._get()
        config = types.EmbedContentConfig(output_dimensionality=self.s.embed_dims)
        out: list[list[float]] = []

        for i in range(0, len(texts), self.batch_size):
            batch = list(texts[i:i + self.batch_size])

            async def call(b=batch):
                return await asyncio.to_thread(
                    lambda: client.models.embed_content(
                        model=self.model, contents=b, config=config
                    )
                )

            resp = await with_backoff(call)
            vectors = [list(e.values) for e in resp.embeddings]
            if len(vectors) != len(batch):
                raise RuntimeError(
                    f"{self.model} returned {len(vectors)} embeddings for "
                    f"{len(batch)} inputs; expected one per input."
                )
            out.extend(vectors)
        return out


# --------------------------------------------------------------------------
# Provider factory
# --------------------------------------------------------------------------

def build_chat(settings: Settings | None = None, judge: bool = False) -> ChatModel:
    """Chat model for the configured provider.

    `judge=True` selects the evaluation model, which is deliberately a
    different and stronger model than the generator: a model grading its own
    output inflates faithfulness.
    """
    s = settings or get_settings()
    if s.llm_provider == "gemini":
        return GeminiChat(s, model=s.gemini_judge_model if judge else s.gemini_chat_model)
    return AzureOpenAIChat(s, deployment=s.judge_deployment if judge else s.chat_deployment)


class NullEmbedder:
    """Produces no vectors, for BM25-only operation with no API key.

    Returns an empty vector per input rather than zeros: `chunk_to_document`
    omits an empty vector entirely, so nothing is indexed as a meaningless
    all-zeros point that would then match everything equally.
    """

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[] for _ in texts]


def build_embedder(settings: Settings | None = None) -> Embedder:
    s = settings or get_settings()
    if not s.enable_embeddings:
        return NullEmbedder()
    if s.llm_provider == "gemini":
        return GeminiEmbedder(s)
    return AzureOpenAIEmbedder(s)


# The local index lives in memory, so every caller must share one instance -
# otherwise a delete or an upload mutates a copy the API's pipeline cannot see.
_LOCAL_SEARCHERS: dict[str, Any] = {}


def build_searcher(settings: Settings | None = None) -> Searcher:
    s = settings or get_settings()
    if s.search_backend == "local":
        from .local_search import LocalSearcher

        path = s.local_index_path
        if path not in _LOCAL_SEARCHERS:
            _LOCAL_SEARCHERS[path] = LocalSearcher(path)
        return _LOCAL_SEARCHERS[path]
    return AzureSearcher(s)


def build_parser(settings: Settings | None = None):
    s = settings or get_settings()
    if s.parser_backend == "local":
        from .local_parse import LocalParser

        return LocalParser()
    return DocumentIntelligenceParser(s)
