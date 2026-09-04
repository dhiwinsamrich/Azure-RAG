"""Dependency wiring.

The pipeline's collaborators are injected, so the API can be exercised end to
end in tests with fakes and no Azure account. `configure()` is the seam the
test suite and the ingest job both use.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from rag_core.config import Settings, get_settings
from rag_core.pipeline import RagPipeline
from rag_core.store import Store

_pipeline: RagPipeline | None = None
_store: Store | None = None


def configure(pipeline: RagPipeline | None = None, store: Store | None = None) -> None:
    global _pipeline, _store
    if pipeline is not None:
        _pipeline = pipeline
    if store is not None:
        _store = store


@lru_cache
def settings() -> Settings:
    return get_settings()


def get_store() -> Store:
    global _store
    if _store is None:
        url = settings().database_url
        path = url.split("///")[-1] if "///" in url else "azure_rag.db"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        _store = Store(path)
    return _store


def get_pipeline() -> RagPipeline:
    global _pipeline
    if _pipeline is None:
        from rag_core.clients import build_chat, build_embedder, build_searcher

        s = settings()
        _pipeline = RagPipeline(
            searcher=build_searcher(s),
            embedder=build_embedder(s),
            chat=build_chat(s),
            settings=s,
        )
    return _pipeline


def reset() -> None:
    """Test helper - drop the cached singletons."""
    global _pipeline, _store
    _pipeline = None
    _store = None
    settings.cache_clear()
