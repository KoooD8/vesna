import os
import json
from unittest.mock import patch, MagicMock

import pytest

from agents.web_research.working_agent import WorkingWebAgent
from vector_store import VectorStore, VectorConfig


class DummyResp:
    def __init__(self, status_code=200, text="", json_obj=None):
        self.status_code = status_code
        self.text = text
        self._json = json_obj or {}

    def json(self):
        return self._json


@patch("requests.Session.get")
@patch("requests.Session.post")
def test_agent_ddg_fallback(mock_post, mock_get):
    # First call to duckduckgo.com (home) returns no vqd -> fallback path
    mock_get.side_effect = [
        DummyResp(200, text="no vqd here"),  # home
        DummyResp(200, text="<html><a class='result__a' href='https://ex.com'>Example</a></html>")  # html serp
    ]
    ag = WorkingWebAgent(timeout=1.0, max_results=1, retries=0, backoff=0.0, verbose=False)
    out = ag.search_duckduckgo("test")
    assert out and out[0]["url"].startswith("https://ex.com")


@patch("requests.Session.get")
def test_agent_reddit_public(mock_get):
    data = {
        "data": {"children": [
            {"data": {"title": "A", "permalink": "/r/x/1", "selftext": "t", "subreddit": "x", "score": 1, "author": "u"}}
        ]}
    }
    mock_get.return_value = DummyResp(200, json_obj=data)
    ag = WorkingWebAgent(timeout=1.0, max_results=1, retries=0, backoff=0.0, verbose=False)
    out = ag.search_reddit_simple("q")
    assert out and out[0]["source"] == "Reddit"


def test_vector_store_batch(monkeypatch):
    calls = {"upsert": 0}

    class DummyClient:
        def __init__(self, *a, **kw):
            pass
        def get_collections(self):
            class C: collections = []
            return C()
        def recreate_collection(self, **kw):
            pass
        def create_payload_index(self, *a, **kw):
            pass
        def upsert(self, **kw):
            calls["upsert"] += 1
            class R: pass
            return R()
        def search(self, **kw):
            return []

    monkeypatch.setenv("AI_STACK_QDRANT_BATCH", "2")
    monkeypatch.setenv("AI_STACK_EMB_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

    # Patch client and model.encode
    monkeypatch.setattr("vector_store.QdrantClient", lambda *a, **kw: DummyClient())
    class DummyModel:
        def encode(self, texts, convert_to_numpy=False, normalize_embeddings=True):
            return [[0.0] * 384 for _ in texts]
    monkeypatch.setattr("vector_store.SentenceTransformer", lambda name: DummyModel())

    vs = VectorStore(VectorConfig())
    n = vs.upsert_texts(["a", "b", "c"], [{}, {}, {}])
    assert n == 3
    assert calls["upsert"] == 2  # 2 batches: (a,b) and (c)

