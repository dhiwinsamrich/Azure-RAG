"""A local stand-in for Azure AI Search, so the app runs with no cloud spend.

This is a DEVELOPMENT backend, not a production one. It implements the same
`Searcher` protocol as `AzureSearcher` - same request kwargs, same result
shape - so the pipeline, the API and the evaluator are all exercised for real.

What it genuinely does:
  * Okapi BM25 over a local inverted index.
  * Cosine similarity when a query vector is supplied.
  * Reciprocal Rank Fusion across whichever retrievers are enabled.
  * The subset of OData filtering that `retrieval.build_odata_filter` emits.

What it does NOT do:
  * The semantic ranker. That is a hosted Microsoft cross-encoder with no local
    equivalent, so `use_semantic_ranker` configs fall back to fused ranking and
    say so. Any quality number measured here is therefore NOT comparable to a
    number measured against Azure.
  * Scale. Everything is held in memory and persisted as one JSON file.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .retrieval import reciprocal_rank_fusion

_TOKEN = re.compile(r"[a-z0-9][a-z0-9.\-]*")

K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


# --------------------------------------------------------------------------
# OData subset
# --------------------------------------------------------------------------

_SEARCH_IN = re.compile(r"search\.in\((\w+),\s*'((?:[^']|'')*)',\s*'([^']*)'\)")
_EQ = re.compile(r"(\w+)\s+eq\s+(\d+)")


def matches_filter(doc: dict[str, Any], odata: str | None) -> bool:
    """Evaluate the filter expressions this codebase generates.

    Deliberately narrow: it understands `search.in(field, 'a,b', ',')` and
    `(field eq 1 or field eq 2)` joined by `and`, which is exactly what
    `build_odata_filter` produces. A test asserts the two stay in sync.
    """
    if not odata:
        return True

    for clause in _split_and(odata):
        m = _SEARCH_IN.search(clause)
        if m:
            field, raw, sep = m.group(1), m.group(2).replace("''", "'"), m.group(3)
            wanted = {v.strip() for v in raw.split(sep) if v.strip()}
            if str(doc.get(field) or "") not in wanted:
                return False
            continue

        eqs = _EQ.findall(clause)
        if eqs:
            field = eqs[0][0]
            wanted_ints = {int(v) for _, v in eqs}
            value = doc.get(field)
            if value is None or int(value) not in wanted_ints:
                return False
            continue

        raise ValueError(f"local search cannot evaluate filter clause: {clause!r}")
    return True


def _split_and(odata: str) -> list[str]:
    """Split on top-level ` and `, ignoring separators inside parentheses."""
    parts, depth, current = [], 0, []
    tokens = re.split(r"(\(|\)|\sand\s)", odata)
    for tok in tokens:
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth -= 1
        if depth == 0 and tok.strip() == "and":
            parts.append("".join(current))
            current = []
        else:
            current.append(tok)
    if current:
        parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


# --------------------------------------------------------------------------
# Index
# --------------------------------------------------------------------------

class LocalSearcher:
    def __init__(self, path: str | Path = ".local_index.json") -> None:
        self.path = Path(path)
        self.docs: dict[str, dict[str, Any]] = {}
        # (mtime_ns, size): float mtime is too coarse to distinguish two
        # writes in the same clock tick, which made reloads miss.
        self._stamp: tuple[int, int] = (-1, -1)
        self._load()

    # -- persistence -----------------------------------------------------
    def _load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.docs = raw.get("docs", {})
            self._stamp = self._file_stamp()
        self._reindex()

    def _file_stamp(self) -> tuple[int, int]:
        st = self.path.stat()
        return (st.st_mtime_ns, st.st_size)

    def _refresh(self) -> None:
        """Reload if the file changed underneath us.

        The ingest CLI writes this file from a separate process, so an API
        holding an in-memory copy would keep serving a stale index.
        """
        if not self.path.exists():
            return
        if self._file_stamp() != self._stamp:
            self._load()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"docs": self.docs}), encoding="utf-8")
        self._stamp = self._file_stamp()

    def _reindex(self) -> None:
        self._tf: dict[str, Counter] = {}
        self._len: dict[str, int] = {}
        self._df: Counter = Counter()
        for doc_id, doc in self.docs.items():
            toks = tokenize(doc.get("content", ""))
            self._tf[doc_id] = Counter(toks)
            self._len[doc_id] = len(toks)
            self._df.update(set(toks))
        self._avg_len = (sum(self._len.values()) / len(self._len)) if self._len else 0.0

    # -- write -----------------------------------------------------------
    async def upload(self, documents: list[dict[str, Any]]) -> int:
        self._refresh()
        for d in documents:
            self.docs[d["id"]] = d
        self._reindex()
        self._save()
        return len(documents)

    @property
    def count(self) -> int:
        return len(self.docs)

    def list_documents(self) -> list[dict[str, Any]]:
        """Documents present in the index, which is the only list a scope
        selector can honestly offer."""
        self._refresh()
        out: dict[str, dict[str, Any]] = {}
        for d in self.docs.values():
            doc_id = d.get("doc_id") or (d["id"].split("__")[0] if "__" in d["id"] else d["id"].split("::")[0])
            entry = out.setdefault(doc_id, {
                "doc_id": doc_id, "company": d.get("company", ""),
                "ticker": d.get("ticker", ""), "doc_type": d.get("doc_type", ""),
                "fiscal_year": d.get("fiscal_year"), "chunk_count": 0,
                "has_vectors": False,
            })
            entry["chunk_count"] += 1
            if d.get("content_vector"):
                entry["has_vectors"] = True
        return sorted(out.values(), key=lambda e: e["doc_id"])

    async def delete_document(self, doc_id: str) -> int:
        """Remove every chunk of a document, vectors included.

        Deleting from the metadata store alone would leave the chunks
        searchable - the index is what retrieval actually reads.
        """
        self._refresh()
        victims = [
            cid for cid, d in self.docs.items()
            if (d.get("doc_id") or (cid.split("__")[0] if "__" in cid else cid.split("::")[0])) == doc_id
        ]
        for cid in victims:
            del self.docs[cid]
        if victims:
            self._reindex()
            self._save()
        return len(victims)

    # -- read ------------------------------------------------------------
    def _bm25(self, query: str, candidates: list[str]) -> list[tuple[str, float]]:
        n = len(self.docs)
        scores: list[tuple[str, float]] = []
        q_tokens = tokenize(query)
        for doc_id in candidates:
            tf, dl = self._tf[doc_id], self._len[doc_id]
            score = 0.0
            for term in q_tokens:
                f = tf.get(term, 0)
                if not f:
                    continue
                df = self._df.get(term, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                denom = f + K1 * (1 - B + B * (dl / self._avg_len if self._avg_len else 1))
                score += idf * (f * (K1 + 1)) / denom
            if score > 0:
                scores.append((doc_id, score))
        scores.sort(key=lambda x: (-x[1], x[0]))
        return scores

    def _cosine(self, vector: list[float], candidates: list[str]) -> list[tuple[str, float]]:
        qn = math.sqrt(sum(v * v for v in vector)) or 1.0
        out: list[tuple[str, float]] = []
        for doc_id in candidates:
            dv = self.docs[doc_id].get("content_vector")
            if not dv:
                continue
            dn = math.sqrt(sum(v * v for v in dv)) or 1.0
            dot = sum(a * b for a, b in zip(vector, dv, strict=False))
            out.append((doc_id, dot / (qn * dn)))
        out.sort(key=lambda x: (-x[1], x[0]))
        return out

    async def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._refresh()
        odata = kwargs.get("filter")
        top = int(kwargs.get("top") or 10)
        search_text = kwargs.get("search_text")
        vector_queries = kwargs.get("vector_queries") or []

        candidates = [i for i, d in self.docs.items() if matches_filter(d, odata)]
        if not candidates:
            return []

        rankings: list[list[str]] = []
        bm25_scores: dict[str, float] = {}
        vec_scores: dict[str, float] = {}

        if search_text:
            ranked = self._bm25(search_text, candidates)
            bm25_scores = dict(ranked)
            rankings.append([d for d, _ in ranked])

        if vector_queries:
            ranked = self._cosine(list(vector_queries[0]["vector"]), candidates)
            vec_scores = dict(ranked)
            rankings.append([d for d, _ in ranked])

        if not rankings:  # no query at all - return an arbitrary stable page
            ordered = sorted(candidates)[:top]
            return [self._hit(i, 0.0) for i in ordered]

        fused = reciprocal_rank_fusion(rankings)
        ordered = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:top]

        hits = []
        for doc_id, score in ordered:
            hit = self._hit(doc_id, score)
            hit["@search.bm25_score"] = bm25_scores.get(doc_id)
            hit["@search.vector_score"] = vec_scores.get(doc_id)
            hits.append(hit)
        return hits

    def _hit(self, doc_id: str, score: float) -> dict[str, Any]:
        doc = {k: v for k, v in self.docs[doc_id].items() if k != "content_vector"}
        doc["@search.score"] = score
        # No local semantic ranker exists, so no reranker score is invented.
        doc["@search.reranker_score"] = None
        return doc

    async def close(self) -> None:
        return None
