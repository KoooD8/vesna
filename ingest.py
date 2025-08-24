#!/usr/bin/env python3
"""
Ingest pipeline for Obsidian -> Qdrant

- Reads JSON results stored by chat.py in Obsidian Index/
- Optionally reads Markdown notes from Sources/ (basic extraction)
- Creates embeddings with sentence-transformers/all-MiniLM-L6-v2
- Upserts into local Qdrant collection (default ai_research)

Usage examples:
  python ingest.py --vault "/Users/onopriychukpavel/Library/Mobile Documents/iCloud~md~obsidian/Documents/Version1" --index Index --sources Sources --limit 100
  python ingest.py --only-json
  python ingest.py --clear  # clears collection

Environment overrides:
  AI_STACK_QDRANT_URL (default: http://localhost:6333)
  AI_STACK_QDRANT_COLLECTION (default: ai_research)
  AI_STACK_EMB_MODEL (default: sentence-transformers/all-MiniLM-L6-v2)
"""

from __future__ import annotations
import os
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Iterable, Tuple, Optional

import re
try:
    import yaml  # for frontmatter parsing
except Exception:
    yaml = None  # will handle gracefully

from vector_store import VectorStore, VectorConfig
from config import load_config

# Optionally load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

def load_config_from_vault(vault_path: str) -> Dict[str, Any]:
    """Return config dict using provided vault_path, keeping folder names from YAML/defaults."""
    cfg = load_config()
    base = Path(vault_path).expanduser()
    return {
        "vault_path": str(base),
        "folders": {
            "sources": cfg.folders.sources,
            "summaries": cfg.folders.summaries,
            "entities": cfg.folders.entities,
            "index": cfg.folders.index,
            "logs": cfg.folders.logs,
        },
    }


def iter_index_json(index_dir: Path, limit: Optional[int] = None) -> Iterable[Tuple[Path, Dict[str, Any]]]:
    count = 0
    for p in sorted(index_dir.glob("*.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            yield p, obj
            count += 1
            if limit and count >= limit:
                break
        except Exception:
            continue


def flatten_result_items(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract items from execute() result structure into flat records with richer payload."""
    items: List[Dict[str, Any]] = []
    for it in obj.get("results") or []:
        if "error" in it:
            continue
        title = (it.get("title") or "").strip()
        snippet = (it.get("snippet") or "").strip()
        url = (it.get("url") or "").strip()
        source = it.get("source", "Unknown")
        meta = it.get("metadata") or {}

        # derive domain and date if present
        domain = ""
        try:
            from urllib.parse import urlparse
            netloc = urlparse(url).netloc
            domain = netloc.lower()
        except Exception:
            domain = ""
        date = (meta.get("date") or "")[:10] if isinstance(meta.get("date"), str) else ""

        text_parts = [p for p in [title, snippet, url, json.dumps(meta, ensure_ascii=False)] if p]
        text = "\n".join(text_parts).strip()

        if not text:
            continue

        # chunk_id для единичных записей из результатов считаем как хэш текста
        import hashlib
        chunk_id = hashlib.md5(text.encode("utf-8")).hexdigest()

        record = {
            "text": text,
            "metadata": {
                "chunk_id": chunk_id,
                "source": source,
                "title": title,
                "url": url,
                "domain": domain,
                "date": date,
                **meta,
            },
        }
        items.append(record)
    return items


def iter_sources_markdown(src_dir: Path, limit: Optional[int] = None) -> Iterable[Tuple[Path, str]]:
    count = 0
    for p in sorted(src_dir.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8")
            if text.strip():
                yield p, text
                count += 1
                if limit and count >= limit:
                    break
        except Exception:
            continue


def _split_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Extract YAML frontmatter if present and return (fm_dict, body).
    If pyyaml is unavailable, return empty dict and original text.
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    fm_text = text[4:end]
    body = text[end + 5:]
    if yaml is None:
        return {}, body
    try:
        data = yaml.safe_load(fm_text) or {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    return data, body


def chunk_text(text: str, max_len: int = 800) -> List[str]:
    """Naive chunking by paragraphs to keep MiniLM within reasonable size."""
    parts: List[str] = []
    buf: List[str] = []
    cur = 0
    for line in text.splitlines():
        ln = line.strip()
        if cur + len(ln) + 1 > max_len and buf:
            parts.append("\n".join(buf))
            buf = [ln]
            cur = len(ln)
        else:
            buf.append(ln)
            cur += len(ln) + 1
    if buf:
        parts.append("\n".join(buf))
    return [p for p in parts if p]


def main():
    import time
    ap = argparse.ArgumentParser(description="Ingest Obsidian notes and results into Qdrant")
    ap.add_argument("--vault", default="/Users/onopriychukpavel/Library/Mobile Documents/iCloud~md~obsidian/Documents/Version1", help="Obsidian Vault path")
    ap.add_argument("--index", default=None, help="Index folder name (default from config)")
    ap.add_argument("--sources", default=None, help="Sources folder name (default from config)")
    ap.add_argument("--limit", type=int, default=200, help="Max files per folder to process")
    ap.add_argument("--only-json", action="store_true", help="Only ingest JSON results from Index/")
    ap.add_argument("--only-md", action="store_true", help="Only ingest Markdown notes from Sources/")
    ap.add_argument("--clear", action="store_true", help="Clear Qdrant collection before ingest")
    ap.add_argument("-v", "--verbose", action="store_true", help="verbose logging")
    args = ap.parse_args()

    t0 = time.time()
    cfg = load_config_from_vault(args.vault)
    base = Path(cfg["vault_path"])
    idx_name = args.index or cfg["folders"]["index"]
    src_name = args.sources or cfg["folders"]["sources"]

    vs = VectorStore(VectorConfig())
    if args.clear:
        print("Clearing collection...")
        vs.clear()
        print("Collection recreated.")

    total_upserted = 0
    json_files = 0
    json_records = 0
    md_files = 0
    md_chunks = 0

    if not args.only_md:
        t_json0 = time.time()
        index_dir = base / idx_name
        index_dir.mkdir(parents=True, exist_ok=True)
        print(f"Scanning JSON in: {index_dir}")
        for p, obj in iter_index_json(index_dir, limit=args.limit):
            json_files += 1
            items = flatten_result_items(obj)
            json_records += len(items)
            if items:
                texts = [r["text"] for r in items]
                metas = [r["metadata"] for r in items]
                t_up0 = time.time()
                total_upserted += vs.upsert_texts(texts, metas)
                t_up1 = time.time()
                if args.verbose:
                    print(f"  + {len(items)} from {p.name} (upsert {t_up1 - t_up0:.3f}s)")
        t_json1 = time.time()
        print(f"JSON done: files={json_files}, records={json_records}, time={t_json1 - t_json0:.3f}s")

    if not args.only_json:
        t_md0 = time.time()
        src_dir = base / src_name
        src_dir.mkdir(parents=True, exist_ok=True)
        print(f"Scanning Markdown in: {src_dir}")
        for p, text in iter_sources_markdown(src_dir, limit=args.limit):
            md_files += 1
            fm, body = _split_frontmatter(text)
            chunks = chunk_text(body)
            if chunks:
                # Формируем расширенный payload для чанков
                import hashlib
                metas = []
                # prepare keywords/tags/date
                tags = []
                keywords = []
                date = ""
                try:
                    tv = fm.get("tags") if isinstance(fm, dict) else None
                    if isinstance(tv, list):
                        tags = [str(x) for x in tv]
                    kv = fm.get("keywords") if isinstance(fm, dict) else None
                    if isinstance(kv, list):
                        keywords = [str(x) for x in kv]
                    dv = fm.get("date") if isinstance(fm, dict) else None
                    if isinstance(dv, str):
                        date = dv[:10]
                except Exception:
                    pass
                # inject keywords into chunk text to improve semantic search
                if keywords:
                    prefix = "Keywords: " + ", ".join(keywords) + "\n\n"
                    chunks = [prefix + c for c in chunks]
                for idx, chunk in enumerate(chunks):
                    chunk_hash = hashlib.md5(f"{p.name}|{idx}|{chunk}".encode("utf-8")).hexdigest()
                    metas.append({
                        "chunk_id": chunk_hash,
                        "source": "obsidian_md",
                        "file": p.name,
                        "vault": base.name,
                        "title": p.stem,
                        "domain": "",
                        "url": "",
                        "date": date,
                        "tags": tags,
                        "keywords": keywords,
                    })
                md_chunks += len(chunks)
                t_up0 = time.time()
                total_upserted += vs.upsert_texts(chunks, metas)
                t_up1 = time.time()
                if args.verbose:
                    print(f"  + {len(chunks)} chunks from {p.name} (upsert {t_up1 - t_up0:.3f}s)")
        t_md1 = time.time()
        print(f"MD done: files={md_files}, chunks={md_chunks}, time={t_md1 - t_md0:.3f}s")

    print(f"✅ Ingest done. Upserted vectors: {total_upserted} | total_time={time.time() - t0:.3f}s")
 

if __name__ == "__main__":
    main()
