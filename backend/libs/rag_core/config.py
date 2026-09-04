"""Settings and the named RetrievalConfig registry.

Azure services authenticate with DefaultAzureCredential, so the deployed app
holds a managed identity and no Azure key reaches application config.

Gemini is the exception: the Gemini API authenticates with an API key. It is
kept out of config and images by living in Key Vault and being fetched at
runtime with that same managed identity - see `resolve_gemini_api_key`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .schemas import RetrievalConfig

# backend/libs/rag_core/config.py -> backend/
BACKEND_ROOT = Path(__file__).resolve().parents[2]
EVALS_DIR = BACKEND_ROOT / "evals"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Which LLM provider serves generation, embeddings and the eval judge.
    llm_provider: Literal["gemini", "azure_openai"] = "gemini"

    # "local" runs BM25 + cosine over an on-disk index and parses markdown/text
    # directly, so the whole app runs with no Azure resources at all. It is a
    # development backend: there is no local semantic ranker, so quality
    # numbers measured this way are NOT comparable to Azure ones.
    search_backend: Literal["azure", "local"] = "azure"
    parser_backend: Literal["azure", "local"] = "azure"
    local_index_path: str = ".local_index.json"
    # Turn off to ingest and search with BM25 alone - no embedding calls, so no
    # API key is needed at all. Vector and hybrid configs stop working.
    enable_embeddings: bool = True

    # Endpoints - resource names only, never keys.
    search_endpoint: str = ""
    search_index: str = "filings"
    # The Azure AI Search FREE tier does not offer the semantic ranker. Set
    # false there, or index creation defines a config you can never use and
    # `hybrid_semantic` queries fail at query time.
    enable_semantic_ranker: bool = True
    openai_endpoint: str = ""
    openai_api_version: str = "2024-10-21"
    doc_intelligence_endpoint: str = ""
    storage_account_url: str = ""
    raw_container: str = "raw"
    parsed_container: str = "parsed"
    ingest_queue: str = "ingest"

    # --- Gemini ---------------------------------------------------------
    # The key is read from the environment for local work, or pulled from Key
    # Vault with the app's managed identity in Azure, so it never sits in
    # container config or an image layer.
    gemini_api_key: SecretStr = SecretStr("")
    gemini_api_key_secret_name: str = "gemini-api-key"
    key_vault_uri: str = ""

    gemini_chat_model: str = "gemini-3.8-flash"
    # A stable model for the judge, not a preview one: judge drift shows up as
    # a quality change that isn't real.
    gemini_judge_model: str = "gemini-2.5-pro"
    # gemini-embedding-001 returns one embedding PER input string.
    # gemini-embedding-2 returns a single aggregated embedding for a list,
    # which would silently corrupt a batch of chunks - see GeminiEmbedder.
    gemini_embed_model: str = "gemini-embedding-001"

    # --- Azure OpenAI (alternate provider) -------------------------------
    chat_deployment: str = "gpt-4o-mini"
    judge_deployment: str = "gpt-4.1"
    embed_deployment: str = "text-embedding-3-large"

    # Gemini supports 768 / 1536 / 3072 (MRL truncation); Azure OpenAI's
    # text-embedding-3-* supports arbitrary shortening. This is fixed at index
    # creation time - changing it means rebuilding the index.
    embed_dims: int = 1536

    database_url: str = "sqlite+pysqlite:///./azure_rag.db"

    default_config_id: str = "hybrid_semantic"
    online_eval_sample_rate: float = Field(default=0.05, ge=0.0, le=1.0)

    prompt_cost_per_1k: float = 0.00015
    completion_cost_per_1k: float = 0.0006

    applicationinsights_connection_string: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


# --------------------------------------------------------------------------
# Retrieval configs
# --------------------------------------------------------------------------

BUILTIN_CONFIGS: dict[str, RetrievalConfig] = {
    c.id: c
    for c in [
        RetrievalConfig(
            id="vector_only", name="Vector only",
            use_bm25=False, use_vector=True, use_semantic_ranker=False,
        ),
        RetrievalConfig(
            id="bm25_only", name="BM25 only",
            use_bm25=True, use_vector=False, use_semantic_ranker=False,
        ),
        RetrievalConfig(
            id="hybrid_rrf", name="Hybrid + RRF",
            use_bm25=True, use_vector=True, use_semantic_ranker=False,
        ),
        RetrievalConfig(
            id="hybrid_semantic", name="Hybrid + semantic ranker",
            use_bm25=True, use_vector=True, use_semantic_ranker=True,
        ),
    ]
}


def load_configs(directory: str | Path | None = None) -> dict[str, RetrievalConfig]:
    """Built-ins overlaid with any YAML variants in evals/configs.

    Chunk-size sweeps and dimension experiments are added as files so a new
    ablation arm never needs a code change.
    """
    configs = dict(BUILTIN_CONFIGS)
    d = Path(directory) if directory else EVALS_DIR / "configs"
    if not d.is_dir():
        return configs
    for path in sorted(d.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for entry in data.get("configs", []):
            cfg = RetrievalConfig.model_validate(entry)
            configs[cfg.id] = cfg
    return configs


def get_config(config_id: str) -> RetrievalConfig:
    configs = load_configs()
    if config_id not in configs:
        raise KeyError(
            f"unknown retrieval config {config_id!r}; known: {sorted(configs)}"
        )
    return configs[config_id]
