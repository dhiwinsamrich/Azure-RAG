"""Prompt construction and the structured-output contract.

Citations are requested as a JSON object with a schema, not parsed out of
brackets in prose. Bracket-parsing fails silently and often; a schema either
validates or it does not.
"""

from __future__ import annotations

import json
from typing import Any

from .schemas import Chunk, ModelAnswer, ScoredChunk

SYSTEM_PROMPT = """You answer questions about financial filings using ONLY the numbered context passages provided.

Rules:
1. Every factual claim must be supported by a passage. Cite the passage number it came from.
2. For each citation, quote a short span (5-25 words) copied EXACTLY from that passage. Do not paraphrase inside the quote; it is checked character by character against the source.
3. If the context does not contain the answer, set "refused" to true, explain briefly what is missing, and return an empty citations list. Do not guess, and do not use knowledge from outside the context.
4. Report figures at the scale the source uses and say which fiscal period they belong to.
5. Prefer figures from tables over figures mentioned in prose when the two disagree, and say so.

Return JSON matching the provided schema."""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "description": "The answer text. Reference passages inline as [1], [2].",
        },
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chunk_id": {
                        "type": "string",
                        "description": "The chunk id shown in the passage header.",
                    },
                    "quoted_span": {
                        "type": "string",
                        "description": "Text copied verbatim from that passage.",
                    },
                },
                "required": ["chunk_id", "quoted_span"],
                "additionalProperties": False,
            },
        },
        "refused": {
            "type": "boolean",
            "description": "True when the context does not support an answer.",
        },
    },
    "required": ["answer", "citations", "refused"],
    "additionalProperties": False,
}


def format_context(chunks: list[Chunk]) -> str:
    """Number the passages and expose each chunk id the model must cite."""
    blocks = []
    for i, c in enumerate(chunks, start=1):
        m = c.metadata
        pages = (f"p.{m.page_start}" if m.page_start == m.page_end
                 else f"pp.{m.page_start}-{m.page_end}")
        blocks.append(
            f"[{i}] chunk_id={c.id} | {c.context_header()} | {pages}\n{c.content}"
        )
    return "\n\n".join(blocks)


def build_messages(question: str, chunks: list[Chunk]) -> list[dict[str, str]]:
    """Retrieved content goes in a user message, never a system message.

    Ingested filings are third-party documents; treating their text as
    instructions is the indirect prompt-injection vector.
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Context passages:\n\n{format_context(chunks)}\n\n"
                f"Question: {question}"
            ),
        },
    ]


def answer_schema() -> dict[str, Any]:
    """The provider-neutral schema.

    Each chat adapter translates this into its own envelope - OpenAI's
    `json_schema` response_format, Gemini's `response_format.schema` - so the
    citation contract is defined once here rather than per provider.
    """
    return RESPONSE_SCHEMA


def split_messages(messages: list[dict[str, str]]) -> tuple[str, str]:
    """Split a chat message list into (system instruction, user input).

    Gemini takes the system instruction as its own argument rather than as a
    message with a role, so adapters need the two parts separately.
    """
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    user = "\n\n".join(m["content"] for m in messages if m.get("role") != "system")
    return system, user


def parse_model_output(raw: str) -> ModelAnswer:
    """Parse the structured response, degrading to a refusal on malformed JSON.

    A model that returns unparseable output has not grounded anything, so the
    safe reading is a refusal rather than an unsourced answer.
    """
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return ModelAnswer(
            answer="The model returned a malformed response.", refused=True
        )
    if not isinstance(data, dict):
        return ModelAnswer(
            answer="The model returned a malformed response.", refused=True
        )
    return ModelAnswer.model_validate(
        {
            "answer": data.get("answer", ""),
            "citations": data.get("citations", []) or [],
            "refused": bool(data.get("refused", False)),
        }
    )


def context_chunks(scored: list[ScoredChunk]) -> list[Chunk]:
    return [s.chunk for s in scored]


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    prompt_per_1k: float = 0.00015,
    completion_per_1k: float = 0.0006,
) -> float:
    """Rough per-request cost. Rates are settings, not constants - verify them
    against current pricing for your region and deployment."""
    return (prompt_tokens / 1000.0) * prompt_per_1k + (
        completion_tokens / 1000.0
    ) * completion_per_1k
