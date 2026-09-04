"""The search index defined as code, plus chunk -> document mapping.

Keeping the index schema in the repo means it deploys through the same pipeline
as everything else and a field change is reviewable in a diff.
"""

from __future__ import annotations

from typing import Any

from .schemas import Chunk

VECTOR_PROFILE = "hnsw-cosine"
VECTOR_ALGORITHM = "hnsw-config"
SEMANTIC_CONFIG = "default"


def index_definition(name: str, dims: int = 1024) -> dict[str, Any]:
    """Fields, vector profile and semantic configuration.

    Two choices worth defending:
      - `content_vector` is not retrievable. The raw floats are never needed
        back and returning them bloats every response.
      - `m` is raised from the default 4 to 8, trading memory for recall.
    """
    return {
        "name": name,
        "fields": [
            {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
            {"name": "content", "type": "Edm.String", "searchable": True,
             "analyzer": "en.microsoft"},
            {"name": "content_vector", "type": "Collection(Edm.Single)",
             "searchable": True, "retrievable": False,
             "dimensions": dims, "vectorSearchProfile": VECTOR_PROFILE},
            {"name": "doc_id", "type": "Edm.String", "filterable": True, "facetable": True},
            {"name": "company", "type": "Edm.String", "searchable": True,
             "filterable": True, "facetable": True},
            {"name": "ticker", "type": "Edm.String", "filterable": True, "facetable": True},
            {"name": "doc_type", "type": "Edm.String", "filterable": True, "facetable": True},
            {"name": "fiscal_year", "type": "Edm.Int32", "filterable": True,
             "facetable": True, "sortable": True},
            {"name": "fiscal_quarter", "type": "Edm.Int32", "filterable": True,
             "facetable": True},
            {"name": "section_path", "type": "Edm.String", "searchable": True,
             "filterable": True},
            {"name": "page_start", "type": "Edm.Int32", "filterable": True, "sortable": True},
            {"name": "page_end", "type": "Edm.Int32", "filterable": True},
            {"name": "chunk_index", "type": "Edm.Int32", "filterable": True, "sortable": True},
            {"name": "contains_table", "type": "Edm.Boolean", "filterable": True,
             "facetable": True},
            {"name": "source_url", "type": "Edm.String"},
            {"name": "token_count", "type": "Edm.Int32", "filterable": True},
        ],
        "vectorSearch": {
            "algorithms": [{
                "name": VECTOR_ALGORITHM,
                "kind": "hnsw",
                "hnswParameters": {
                    "m": 8,
                    "efConstruction": 400,
                    "efSearch": 500,
                    "metric": "cosine",
                },
            }],
            "profiles": [{"name": VECTOR_PROFILE, "algorithm": VECTOR_ALGORITHM}],
        },
        "semantic": {
            "configurations": [{
                "name": SEMANTIC_CONFIG,
                "prioritizedFields": {
                    "titleField": {"fieldName": "section_path"},
                    "prioritizedContentFields": [{"fieldName": "content"}],
                    "prioritizedKeywordsFields": [{"fieldName": "company"}],
                },
            }],
        },
    }


def build_search_index(name: str, dims: int = 1536, include_semantic: bool = True):
    """The same schema as `index_definition`, as typed SDK objects.

    The SDK has no `SearchIndex.from_dict`, so the index has to be constructed
    from models. The dict form above stays as the readable, dependency-free
    description of the schema, and a test asserts the two cannot drift apart.

    `include_semantic=False` is for the Azure AI Search **Free tier**, which
    does not offer the semantic ranker.
    """
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration,
        HnswParameters,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SemanticConfiguration,
        SemanticField,
        SemanticPrioritizedFields,
        SemanticSearch,
        VectorSearch,
        VectorSearchAlgorithmMetric,
        VectorSearchProfile,
    )

    S = SearchFieldDataType.String
    I32 = SearchFieldDataType.Int32
    BOOL = SearchFieldDataType.Boolean

    fields = [
        SearchField(name="id", type=S, key=True, filterable=True),
        SearchField(name="content", type=S, searchable=True, analyzer_name="en.microsoft"),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            # `hidden` is the SDK's name for retrievable=false. The raw floats
            # are never needed back and would bloat every response.
            hidden=True,
            vector_search_dimensions=dims,
            vector_search_profile_name=VECTOR_PROFILE,
        ),
        SearchField(name="doc_id", type=S, filterable=True, facetable=True),
        SearchField(name="company", type=S, searchable=True, filterable=True, facetable=True),
        SearchField(name="ticker", type=S, filterable=True, facetable=True),
        SearchField(name="doc_type", type=S, filterable=True, facetable=True),
        SearchField(name="fiscal_year", type=I32, filterable=True, facetable=True, sortable=True),
        SearchField(name="fiscal_quarter", type=I32, filterable=True, facetable=True),
        SearchField(name="section_path", type=S, searchable=True, filterable=True),
        SearchField(name="page_start", type=I32, filterable=True, sortable=True),
        SearchField(name="page_end", type=I32, filterable=True),
        SearchField(name="chunk_index", type=I32, filterable=True, sortable=True),
        SearchField(name="contains_table", type=BOOL, filterable=True, facetable=True),
        SearchField(name="source_url", type=S),
        SearchField(name="token_count", type=I32, filterable=True),
    ]

    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(
                name=VECTOR_ALGORITHM,
                parameters=HnswParameters(
                    m=8, ef_construction=400, ef_search=500,
                    metric=VectorSearchAlgorithmMetric.COSINE,
                ),
            )
        ],
        profiles=[
            VectorSearchProfile(
                name=VECTOR_PROFILE, algorithm_configuration_name=VECTOR_ALGORITHM
            )
        ],
    )

    semantic_search = None
    if include_semantic:
        semantic_search = SemanticSearch(configurations=[
            SemanticConfiguration(
                name=SEMANTIC_CONFIG,
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="section_path"),
                    content_fields=[SemanticField(field_name="content")],
                    keywords_fields=[SemanticField(field_name="company")],
                ),
            )
        ])

    return SearchIndex(
        name=name, fields=fields,
        vector_search=vector_search, semantic_search=semantic_search,
    )


def chunk_to_document(chunk: Chunk, vector: list[float] | None = None) -> dict[str, Any]:
    m = chunk.metadata
    doc: dict[str, Any] = {
        "id": chunk.id,
        "content": chunk.content,
        "doc_id": m.doc_id,
        "company": m.company,
        "ticker": m.ticker,
        "doc_type": m.doc_type.value,
        "fiscal_year": m.fiscal_year,
        "fiscal_quarter": m.fiscal_quarter,
        "section_path": m.section_path,
        "page_start": m.page_start,
        "page_end": m.page_end,
        "chunk_index": m.chunk_index,
        "contains_table": m.contains_table,
        "source_url": m.source_url,
        "token_count": chunk.token_count,
    }
    if vector:  # empty means embeddings are off - omit the field entirely
        doc["content_vector"] = vector
    return doc
