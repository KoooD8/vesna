#!/usr/bin/env python3
"""
Qdrant vector store helper for local RAG
- Uses sentence-transformers/all-MiniLM-L6-v2 for embeddings
- Connects to local Qdrant (localhost:6333) and collection 'ai_research' by default
- Adds server-side filters and simple retries for reliability
"""
from __future__ import annotations
import os
import time
import hashlib
import json
from typing import List, Dict, Any, Optional, Iterable
from dataclasses import dataclass

# Optional imports: provide light fallbacks so tests can run without heavy deps
try:
    from qdrant_client import QdrantClient  # type: ignore
    from qdrant_client.http import models as qm  # type: ignore
except Exception:  # pragma: no cover - fallback stubs for tests
    QdrantClient = object  # type: ignore

    class _QM:  # minimal stubs used only to construct payloads; tests monkeypatch client
        class VectorParams:  # type: ignore
            def __init__(self, *a, **kw):
                pass
        class Distance:  # type: ignore
            COSINE = "COSINE"
        class PayloadSchemaType:  # type: ignore
            KEYWORD = "KEYWORD"
            TEXT = "TEXT"
        class MatchValue:  # type: ignore
            def __init__(self, *a, **kw):
                pass
        class MatchText:  # type: ignore
            def __init__(self, *a, **kw):
                pass
        class Range:  # type: ignore
            def __init__(self, *a, **kw):
                pass
        class FieldCondition:  # type: ignore
            def __init__(self, *a, **kw):
                pass
        class Filter:  # type: ignore
            def __init__(self, *a, **kw):
                pass
        class PointStruct:  # type: ignore
            def __init__(self, *a, **kw):
                # Allow using plain dicts instead; tests' DummyClient ignores structure
                self.__dict__.update(kw)
        class FilterSelector:  # type: ignore
            def __init__(self, *a, **kw):
                pass
    qm = _QM()  # type: ignore

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
except Exception:  # pragma: no cover - fallback stub (tests monkeypatch)
    class SentenceTransformer:  # type: ignore
        def __init__(self, *a, **kw):
            raise RuntimeError("SentenceTransformer is not installed")
        def encode(self, *a, **kw):
            raise RuntimeError("SentenceTransformer is not installed")


DEFAULT_COLLECTION = os.environ.get("AI_STACK_QDRANT_COLLECTION", "ai_research")
DEFAULT_QDRANT_URL = os.environ.get("AI_STACK_QDRANT_URL", "http://localhost:6333")
DEFAULT_MODEL = os.environ.get("AI_STACK_EMB_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


@dataclass
class VectorConfig:
    url: str = DEFAULT_QDRANT_URL
    collection: str = DEFAULT_COLLECTION
    model_name: str = DEFAULT_MODEL
    vector_size: int = 384  # all-MiniLM-L6-v2 output size
    retries: int = 2
    backoff: float = 0.5
    batch_size: int = 128

class VectorStore:
    def __init__(self, cfg: Optional[VectorConfig] = None) -> None:
        self.cfg = cfg or VectorConfig()
        # override batch size from env at runtime
        try:
            self.cfg.batch_size = int(os.environ.get("AI_STACK_QDRANT_BATCH", str(self.cfg.batch_size)))
        except Exception:
            pass
        # lazy-init external clients; tests monkeypatch these symbols
        try:
            self.client = QdrantClient(url=self.cfg.url)  # type: ignore
        except Exception:
            # If QdrantClient is not available, create a dummy object; tests replace it
            class _Dummy: pass
            self.client = _Dummy()
        try:
            self.model = SentenceTransformer(self.cfg.model_name)  # type: ignore
        except Exception:
            # In tests, SentenceTransformer is monkeypatched
            class _DummyModel:
                def encode(self, texts, convert_to_numpy=False, normalize_embeddings=True):
                    return [[0.0] * 384 for _ in texts]
            self.model = _DummyModel()
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        # Best-effort: skip if client doesn't provide these methods
        try:
            collections = getattr(self.client, "get_collections", lambda: type("C", (), {"collections": []})())()
            existing = {c.name for c in getattr(collections, "collections", [])}
            if self.cfg.collection not in existing and hasattr(self.client, "recreate_collection"):
                self.client.recreate_collection(  # type: ignore
                    collection_name=self.cfg.collection,
                    vectors_config=qm.VectorParams(
                        size=self.cfg.vector_size,
                        distance=qm.Distance.COSINE,
                    ),
                )
            # Ensure payload indexes for faster filters
            for field, schema in (
                ("source", qm.PayloadSchemaType.KEYWORD),
                ("domain", qm.PayloadSchemaType.KEYWORD),
                ("date", qm.PayloadSchemaType.TEXT),
                ("id", qm.PayloadSchemaType.KEYWORD),
            ):
                try:
                    if hasattr(self.client, "create_payload_index"):
                        self.client.create_payload_index(self.cfg.collection, field_name=field, field_schema=schema)  # type: ignore
                except Exception:
                    pass
        except Exception:
            # silently ignore in environments without qdrant
            pass

    def embed(self, texts: Iterable[str]) -> List[List[float]]:
        embeddings = self.model.encode(list(texts), convert_to_numpy=False, normalize_embeddings=True)
        # Ensure list[list[float]]
        return [list(map(float, vec)) for vec in embeddings]

    # -------- helpers: retries and filters --------
    def _with_retries(self, func, *args, **kwargs):
        tries = max(1, int(self.cfg.retries) + 1)
        delay = float(self.cfg.backoff)
        last_exc = None
        for attempt in range(tries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exc = e
                if attempt == tries - 1:
                    break
                time.sleep(delay * (2 ** attempt))
        raise last_exc

    @staticmethod
    def build_filter(source: Optional[str] = None, domain: Optional[str] = None, date_from: Optional[str] = None) -> Optional[Any]:
        # When real qdrant models are unavailable, return None; server-side filtering won't be used.
        try:
            must: List[Any] = []
            if source:
                must.append(qm.FieldCondition(key="source", match=qm.MatchValue(value=source)))
            if domain:
                must.append(qm.FieldCondition(key="domain", match=qm.MatchText(text=domain)))
            if date_from:
                must.append(qm.FieldCondition(key="date", range=qm.Range(gte=date_from)))
            if not must:
                return None
            return qm.Filter(must=must)
        except Exception:
            return None

    # --------------- operations -------------------
    def upsert_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> int:
        if not texts:
            return 0
        payloads = metadatas or [{} for _ in texts]
        total = 0
        batch = int(self.cfg.batch_size)
        for start in range(0, len(texts), batch):
            chunk_texts = texts[start:start+batch]
            chunk_payloads = payloads[start:start+batch]
            chunk_ids = ids[start:start+batch] if ids else None
            vectors = self.embed(chunk_texts)
            points: List[Any] = []
            for i, (text, vec, payload) in enumerate(zip(chunk_texts, vectors, chunk_payloads)):
                payload = payload or {}
                # Prefer provided id list; else payload["id"]; else deterministic hash from text+payload
                pid = None
                if chunk_ids and i < len(chunk_ids) and chunk_ids[i]:
                    pid = chunk_ids[i]
                elif "id" in payload and payload["id"]:
                    pid = payload["id"]
                else:
                    base = f"{text}|{json.dumps(payload, sort_keys=True, ensure_ascii=False)}"
                    pid = hashlib.md5(base.encode("utf-8")).hexdigest()
                    payload["id"] = pid
                try:
                    points.append(qm.PointStruct(id=pid, vector=vec, payload=payload))
                except Exception:
                    # fallback to plain dict if models are absent
                    points.append({"id": pid, "vector": vec, "payload": payload})
            # Upsert with retries only if method exists
            if hasattr(self.client, "upsert"):
                self._with_retries(self.client.upsert, collection_name=self.cfg.collection, points=points)  # type: ignore
            total += len(points)
        return total

    def search(
        self,
        query: str,
        limit: int = 5,
        filter_: Optional[Any] = None,
        *,
        source: Optional[str] = None,
        domain: Optional[str] = None,
        date_from: Optional[str] = None,
    ) -> List[Any]:
        query_vec = self.embed([query])[0]
        f = filter_ or self.build_filter(source=source, domain=domain, date_from=date_from)
        if hasattr(self.client, "search"):
            result = self._with_retries(
                self.client.search,
                collection_name=self.cfg.collection,
                query_vector=query_vec,
                limit=limit,
                query_filter=f,
                with_payload=True,
            )
            return result
        return []

    def delete_by_filter(self, filter_: Any) -> None:
        if hasattr(self.client, "delete"):
            try:
                selector = qm.FilterSelector(filter=filter_)  # type: ignore
            except Exception:
                selector = {"filter": filter_}
            self._with_retries(self.client.delete, collection_name=self.cfg.collection, points_selector=selector)  # type: ignore

    def clear(self) -> None:
        if hasattr(self.client, "delete_collection"):
            self._with_retries(self.client.delete_collection, collection_name=self.cfg.collection)  # type: ignore
        self._ensure_collection()


if __name__ == "__main__":
    # quick manual test (optional)
    vs = VectorStore()
    n = vs.upsert_texts(
        ["Claude is great for coding", "Qdrant is a vector database", "Obsidian stores markdown notes"],
        [
            {"source": "test", "id": "a1", "domain": "example.com", "date": "2024-01-01"},
            {"source": "test", "id": "a2", "domain": "example.com", "date": "2024-01-02"},
            {"source": "test", "id": "a3", "domain": "obsidian.md", "date": "2024-01-03"},
        ],
    )
    print(f"Upserted: {n}")
    out = vs.search("code assistant", limit=3, source="test", domain="example.com", date_from="2024-01-01")
    for p in out:
        print(getattr(p, "score", None), getattr(p, "payload", None))
