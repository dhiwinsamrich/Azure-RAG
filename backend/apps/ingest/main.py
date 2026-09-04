"""Container Apps Job entry point: queue-driven, resumable ingestion.

Runs as a job rather than an endpoint because Document Intelligence is a
long-running operation and the work is bursty - scale to zero between corpora,
scale out per queue message during a bulk load.

    python -m apps.ingest.main --check              # verify config + connectivity
    python -m apps.ingest.main --create-index       # once, before first ingest
    python -m apps.ingest.main --local ./corpus     # a directory of PDFs
    python -m apps.ingest.main --queue              # drain the storage queue
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from rag_core.config import get_settings

from .pipeline import IngestPipeline, IngestResult


def build_pipeline() -> IngestPipeline:
    from rag_core.clients import build_embedder, build_parser, build_searcher

    s = get_settings()
    return IngestPipeline(
        parser=build_parser(s),
        embedder=build_embedder(s),
        searcher=build_searcher(s),
        settings=s,
    )


def check() -> int:
    """Verify configuration and connectivity before spending anything.

    Each dependency is probed separately and failures are reported rather than
    raised, so one broken thing does not hide the state of the others.
    """
    s = get_settings()
    ok = True

    print("configuration")
    print(f"  search backend   : {s.search_backend}")
    print(f"  parser backend   : {s.parser_backend}")
    print(f"  llm provider     : {s.llm_provider}")
    print(f"  embeddings       : {'on' if s.enable_embeddings else 'off (BM25 only)'}")
    print(f"  embed dimensions : {s.embed_dims}")
    print(f"  semantic ranker  : {'on' if s.enable_semantic_ranker else 'off'}")
    print()

    print("connectivity")

    if s.search_backend == "local":
        from rag_core.local_search import LocalSearcher
        idx = LocalSearcher(s.local_index_path)
        print(f"  [ok]   local index    : {idx.count} chunks at {s.local_index_path}")
    else:
        try:
            from azure.search.documents.indexes import SearchIndexClient
            from rag_core.clients import credential
            client = SearchIndexClient(endpoint=s.search_endpoint, credential=credential())
            names = [i for i in client.list_index_names()]
            here = "present" if s.search_index in names else "NOT CREATED YET"
            print(f"  [ok]   AI Search      : reachable, index '{s.search_index}' {here}")
            if s.search_index in names:
                from azure.search.documents import SearchClient
                sc = SearchClient(s.search_endpoint, s.search_index, credential())
                print(f"         documents      : {sc.get_document_count()}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  [FAIL] AI Search      : {type(exc).__name__}: {exc}")

    if s.parser_backend == "local":
        print("  [ok]   parser         : local markdown/text parser")
    else:
        try:
            from azure.ai.documentintelligence import DocumentIntelligenceClient
            from rag_core.clients import credential
            DocumentIntelligenceClient(
                endpoint=s.doc_intelligence_endpoint, credential=credential()
            )
            print(f"  [ok]   Doc Intelligence: client created for {s.doc_intelligence_endpoint}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  [FAIL] Doc Intelligence: {type(exc).__name__}: {exc}")

    if s.enable_embeddings or s.llm_provider == "gemini":
        try:
            from rag_core.clients import resolve_gemini_api_key
            key = resolve_gemini_api_key(s)
            print(f"  [ok]   Gemini key     : found ({len(key)} chars)")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  [FAIL] Gemini key     : {exc}")

    print()
    print("ready" if ok else "not ready - fix the [FAIL] lines above")
    return 0 if ok else 1


def create_index() -> int:
    """Prerequisite for any ingest: the index must exist with the right vector
    dimensions before the first document is uploaded."""
    from rag_core.clients import create_or_update_index

    s = get_settings()
    if s.search_backend == "local":
        print("local search backend: the index file is created on first ingest, "
              "nothing to provision")
        return 0
    name = create_or_update_index(s)
    print(f"index '{name}' ready at {s.search_endpoint} "
          f"({s.embed_dims} dimensions, {s.gemini_embed_model})")
    return 0


def report(results: list[IngestResult]) -> int:
    ok = [r for r in results if not r.errors]
    failed = [r for r in results if r.errors]
    cached = [r for r in results if r.from_cache]

    print(f"\ningested {len(ok)}/{len(results)} documents")
    print(f"  chunks indexed : {sum(r.indexed for r in ok)}")
    print(f"  served from cache: {len(cached)}")
    for r in failed:
        print(f"  FAILED {r.doc_id}: {'; '.join(r.errors)}", file=sys.stderr)
    return 1 if failed else 0


async def run_local(directory: str) -> int:
    """Ingest a directory of PDFs. Useful for a first corpus load and for
    re-running after a chunker change."""
    s = get_settings()
    pipeline = build_pipeline()
    # The local parser reads markdown/text; Document Intelligence reads PDFs.
    suffixes = ({".md", ".markdown", ".txt"} if s.parser_backend == "local"
                else {".pdf", ".xlsx"})
    paths = sorted(
        p for p in Path(directory).rglob("*") if p.suffix.lower() in suffixes
    )
    if not paths:
        print(f"no {'/'.join(sorted(suffixes))} files under {directory}", file=sys.stderr)
        return 2

    results = []
    for i, path in enumerate(paths, 1):
        doc_id = path.stem
        print(f"[{i}/{len(paths)}] {doc_id}", flush=True)
        results.append(
            # as_uri() requires an absolute path; a relative --local arg raises.
            await pipeline.ingest(
                doc_id, path.read_bytes(), source_url=path.resolve().as_uri()
            )
        )
    return report(results)


async def run_queue(max_messages: int = 32) -> int:
    """Drain the ingest queue.

    A message is only deleted after the document is indexed, so a crash
    mid-document redelivers it rather than losing it.
    """
    from azure.storage.blob.aio import BlobServiceClient
    from azure.storage.queue.aio import QueueClient
    from rag_core.clients import credential

    s = get_settings()
    pipeline = build_pipeline()
    cred = credential()

    queue = QueueClient(account_url=s.storage_account_url,
                        queue_name=s.ingest_queue, credential=cred)
    blobs = BlobServiceClient(account_url=s.storage_account_url, credential=cred)

    results: list[IngestResult] = []
    async with queue, blobs:
        messages = queue.receive_messages(
            messages_per_page=min(max_messages, 32), visibility_timeout=900
        )
        async for msg in messages:
            blob_name = msg.content
            client = blobs.get_blob_client(s.raw_container, blob_name)
            data = await (await client.download_blob()).readall()

            result = await pipeline.ingest(
                Path(blob_name).stem, data, source_url=client.url
            )
            results.append(result)
            if not result.errors:
                await queue.delete_message(msg)
    return report(results)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rag-ingest")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true",
                       help="verify configuration and connectivity, then exit")
    group.add_argument("--create-index", action="store_true",
                       help="create or update the search index, then exit")
    group.add_argument("--local", metavar="DIR", help="ingest a local directory")
    group.add_argument("--queue", action="store_true", help="drain the ingest queue")
    p.add_argument("--max-messages", type=int, default=32)
    args = p.parse_args(argv)

    if args.check:
        return check()
    if args.create_index:
        return create_index()
    if args.local:
        return asyncio.run(run_local(args.local))
    return asyncio.run(run_queue(args.max_messages))


if __name__ == "__main__":
    raise SystemExit(main())
