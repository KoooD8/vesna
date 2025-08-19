import json
import types
from typing import Any, Dict, List

import pytest
from unittest.mock import patch, MagicMock

from ingest import flatten_result_items, chunk_text


def test_flatten_result_items_basic():
    obj = {
        "results": [
            {"title": "A", "url": "https://ex.com/a", "snippet": "s", "source": "test", "metadata": {"date": "2024-01-01"}},
            {"error": "skip"},
        ]
    }
    items = flatten_result_items(obj)
    assert len(items) == 1
    rec = items[0]
    assert rec["metadata"]["source"] == "test"
    assert rec["metadata"]["domain"] == "ex.com"
    assert rec["metadata"]["date"] == "2024-01-01"


def test_chunk_text_paragraphs():
    text = "one\n" + ("x" * 900) + "\n" + ("y" * 300)
    chunks = chunk_text(text, max_len=800)
    assert len(chunks) >= 2


