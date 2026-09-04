"""Provider-seam tests.

These run with neither SDK installed: the factory is exercised for selection
and validation only, and the schema/message translation is pure logic.
"""

from __future__ import annotations

import pytest
from rag_core.clients import GeminiEmbedder, build_chat, build_embedder
from rag_core.config import Settings
from rag_core.generation import answer_schema, build_messages, split_messages
from rag_core.schemas import Chunk, ChunkMetadata


# _env_file=None keeps a developer's local backend/.env out of the tests. A
# suite whose result depends on ambient config is not a test of the code.
def gemini_settings(**over) -> Settings:
    base = dict(llm_provider="gemini", gemini_api_key="test-key",
                embed_dims=1536, enable_embeddings=True)
    base.update(over)
    return Settings(_env_file=None, **base)


def azure_settings(**over) -> Settings:
    base = dict(llm_provider="azure_openai", enable_embeddings=True,
                openai_endpoint="https://x.openai.azure.com/")
    base.update(over)
    return Settings(_env_file=None, **base)


# --------------------------------------------------------------------------
# Factory selection
# --------------------------------------------------------------------------

def test_gemini_is_the_default_provider():
    assert Settings(_env_file=None).llm_provider == "gemini"


def test_embeddings_can_be_disabled_for_keyless_bm25_only_operation():
    s = gemini_settings(enable_embeddings=False)
    assert type(build_embedder(s)).__name__ == "NullEmbedder"


def test_factory_selects_gemini_adapters():
    s = gemini_settings()
    assert type(build_chat(s)).__name__ == "GeminiChat"
    assert type(build_embedder(s)).__name__ == "GeminiEmbedder"


def test_factory_selects_azure_adapters():
    s = azure_settings()
    assert type(build_chat(s)).__name__ == "AzureOpenAIChat"
    assert type(build_embedder(s)).__name__ == "AzureOpenAIEmbedder"


def test_judge_uses_a_different_model_from_the_generator():
    s = gemini_settings()
    generator = build_chat(s, judge=False)
    judge = build_chat(s, judge=True)

    assert generator.model == s.gemini_chat_model
    assert judge.model == s.gemini_judge_model
    # Self-grading inflates faithfulness; the two must not collapse together.
    assert judge.model != generator.model


def test_judge_name_tracks_the_active_provider():
    from rag_core.evaluation.ragas_runner import judge_name

    assert judge_name(gemini_settings()) == "gemini-2.5-pro"
    assert judge_name(azure_settings()) == "gpt-4.1"


# --------------------------------------------------------------------------
# The aggregating-embedding trap
# --------------------------------------------------------------------------

def test_aggregating_embedding_model_is_rejected():
    # gemini-embedding-2 returns ONE vector for a list of inputs. Used for
    # per-chunk embedding it would silently index one vector for a whole
    # batch, so it must fail loudly at construction.
    s = gemini_settings(gemini_embed_model="gemini-embedding-2")
    with pytest.raises(ValueError, match="aggregated embedding"):
        GeminiEmbedder(s)


def test_per_input_embedding_model_is_accepted():
    assert GeminiEmbedder(gemini_settings()).model == "gemini-embedding-001"


def test_embedder_carries_the_configured_dimensions():
    assert GeminiEmbedder(gemini_settings(embed_dims=768)).s.embed_dims == 768


# --------------------------------------------------------------------------
# Prompt translation
# --------------------------------------------------------------------------

def chunk() -> Chunk:
    return Chunk(
        id="D::0001",
        content="Gross margin was 69.8% in fiscal year 2023.",
        metadata=ChunkMetadata(doc_id="D", ticker="MSFT", fiscal_year=2023),
    )


def test_split_messages_separates_system_instruction_from_input():
    system, user = split_messages(build_messages("What was margin?", [chunk()]))

    assert "ONLY the numbered context passages" in system
    assert "What was margin?" in user
    # Retrieved content must never end up in the system instruction - that is
    # the indirect prompt-injection vector for third-party filings.
    assert "Gross margin was 69.8%" not in system
    assert "Gross margin was 69.8%" in user


def test_split_messages_handles_a_missing_system_message():
    system, user = split_messages([{"role": "user", "content": "hi"}])
    assert system == ""
    assert user == "hi"


def test_answer_schema_is_provider_neutral():
    schema = answer_schema()
    # No OpenAI or Gemini envelope - adapters add their own.
    assert schema["type"] == "object"
    assert set(schema["required"]) == {"answer", "citations", "refused"}
    assert "json_schema" not in schema
    assert "mime_type" not in schema


def test_citation_contract_survives_in_the_schema():
    props = answer_schema()["properties"]["citations"]["items"]["properties"]
    assert set(props) == {"chunk_id", "quoted_span"}
