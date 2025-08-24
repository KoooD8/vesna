import os
import re
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from orchestrator.registry import register
from config import load_config

from vector_store import VectorStore
from agents.web_research.working_agent import WorkingWebAgent
from agents.obsidian.manager import ObsidianManager

def _frontmatter(props: Dict[str, Any]) -> str:
    """Build YAML frontmatter using safe YAML dump with proper quoting."""
    import yaml
    dumped = yaml.safe_dump(props, allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{dumped}\n---\n"


def _normalize_text(text: str) -> str:
    """Simple whitespace normalization: strip edges, unify newlines, collapse extra blank lines."""
    # unify newlines
    s = text.replace("\r\n", "\n").replace("\r", "\n")
    # strip trailing spaces per line
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    # collapse 3+ blank lines to 2
    import re as _re
    s = _re.sub(r"\n{3,}", "\n\n", s.strip())
    return s

def _update_frontmatter_block(existing_md: str, updater: Dict[str, Any]) -> str:
    """Update YAML frontmatter in a markdown string with provided keys; create if missing."""
    import yaml
    md = existing_md
    if md.startswith("---\n"):
        # find closing '---' line
        end = md.find("\n---\n", 4)
        if end != -1:
            fm_text = md[4:end]
            body = md[end + 5:]
        else:
            # malformed, treat as no frontmatter
            fm_text = ""
            body = md
    else:
        fm_text = ""
        body = md
    try:
        data = yaml.safe_load(fm_text) if fm_text else {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    # merge tags if both present as lists
    old_tags = set(map(str, (data.get("tags") or []))) if isinstance(data.get("tags"), list) else set()
    new_tags = set(map(str, (updater.get("tags") or []))) if isinstance(updater.get("tags"), list) else set()
    if old_tags or new_tags:
        data["tags"] = sorted(old_tags | new_tags)
    # update other keys (excluding tags already handled)
    for k, v in updater.items():
        if k == "tags":
            continue
        data[k] = v
    fm_new = _frontmatter(data)
    return f"{fm_new}{body.lstrip()}"


def _auto_tags(text: str) -> list:
    """Very simple keyword-based tag extraction (ru/en). Returns unique tag list (multilingual).
    We include both English and Russian tags where appropriate to help search and graph in Obsidian.
    """
    t = text.lower()
    tags = set()
    # Темы/категории (двуязычные теги)
    if any(k in t for k in ["мурав", "насеком", "таракан", "паразит", "укусы"]):
        tags.update(["pests", "вредители", "home", "дом"])
    if any(k in t for k in ["здоров", "здоровье", "боль", "тело", "кожа", "аллерг", "стресс"]):
        tags.update(["health", "здоровье"])
    if any(k in t for k in ["дом", "квартира", "ремонт", "уборк", "вазон", "растен", "окно"]):
        tags.update(["home", "дом"])
    if any(k in t for k in ["работ", "job", "work", "проек", "дедлайн", "коллег"]):
        tags.update(["work", "работа"])
    if any(k in t for k in ["ai", "ии", "ml", "llm", "обучение", "модель", "qdrant", "вектор", "обсидиан", "obsidian"]):
        tags.update(["ai", "ии"])
    if any(k in t for k in ["путеше", "дорог", "поезд", "самолет", "отдых"]):
        tags.update(["travel", "путешествия"])
    if any(k in t for k in ["деньг", "финанс", "бюдж", "карта", "банкир", "счет", "налог"]):
        tags.update(["finance", "финансы"])
    if any(k in t for k in ["текст", "заметк", "дневник", "журнал"]):
        tags.update(["journal", "дневник"])
    # Эмоции/состояния
    if any(k in t for k in ["радост", "счаст", "доволен", "классно"]):
        tags.update(["mood/positive", "настроение/позитив"])
    if any(k in t for k in ["грусть", "печал", "плохо", "тяжело", "боюсь", "страх", "тревог"]):
        tags.update(["mood/negative", "настроение/негатив"])
    # Язык
    if any(k in t for k in ["english", "англий", "en:"]):
        tags.update(["lang/en", "язык/en"])
    if any(k in t for k in ["украин", "uk:"]):
        tags.update(["lang/uk", "язык/uk"])
    if any(k in t for k in ["русск", "ru:"]):
        tags.update(["lang/ru", "язык/ru"])
    return sorted(tags)


def _extract_wikilinks(text: str) -> list:
    """Generate wiki page titles from content via simple keyword map."""
    t = text.lower()
    titles = set()
    # Базовая карта ключевых слов -e названия страниц
    default_map = {
        "мурав": "Муравьи",
        "насеком": "Насекомые",
        "дом": "Дом",
        "квартира": "Дом",
        "здоров": "Здоровье",
        "работ": "Работа",
        "обсидиан": "Obsidian",
        "obsidian": "Obsidian",
        "qdrant": "Qdrant",
        "вектор": "Векторные базы",
        "путеше": "Путешествия",
        "финанс": "Финансы",
        "журнал": "Дневник",
        "дневник": "Дневник",
        "ai": "AI",
        "ии": "ИИ",
        "вазон": "Комнатные растения",
        "растен": "Комнатные растения",
    }
    # Попытка подгрузить пользовательскую карту из Vault/Entities/glossary.map.yaml
    try:
        base, folders = _vault()
        import yaml
        user_map_path = base / folders.entities / "glossary.map.yaml"
        if user_map_path.exists():
            with open(user_map_path, "r", encoding="utf-8") as f:
                user_map = yaml.safe_load(f) or {}
            if isinstance(user_map, dict):
                default_map.update({str(k).lower(): str(v) for k, v in user_map.items()})
    except Exception:
        pass
    for key, title in default_map.items():
        if key in t:
            titles.add(title)
    return sorted(titles)


def _ensure_wikilink_pages(titles: list, source_basename: str, source_title: str) -> None:
    """Ensure glossary pages exist for each title and append backlink to source note."""
    if not titles:
        return
    base, folders = _vault()
    glossary_dir = base / folders.entities / "Glossary"
    glossary_dir.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now().isoformat(timespec='seconds')
    for title in titles:
        p = glossary_dir / f"{title}.md"
        if p.exists():
            existing = p.read_text(encoding="utf-8")
        else:
            existing = ""
        # Build or update frontmatter
        fm_update = {
            "Title": title,
            "Categories": "glossary",
            "tags": ["glossary", "словарь"],
            "last_modified": now_iso,
        }
        if not existing:
            fm = _frontmatter({
                "Title": title,
                "Categories": "glossary",
                "tags": ["glossary", "словарь"],
                "created_at": now_iso,
                "last_modified": now_iso,
            })
            body = f"# {title}\n\n## Описание\n\n## Упоминания\n\n"
            p.write_text(fm + body, encoding="utf-8")
            existing = p.read_text(encoding="utf-8")
        updated = _update_frontmatter_block(existing, fm_update)
        # Append backlink under mentions
        backlink = f"- [[{source_basename}|{source_title}]] ({datetime.now().strftime('%Y-%m-%d')})\n"
        if "## Упоминания" not in updated:
            updated = updated.rstrip() + "\n\n## Упоминания\n\n" + backlink
        else:
            updated = updated.rstrip() + "\n" + backlink
        p.write_text(updated, encoding="utf-8")


def _vault():
    cfg = load_config()
    base = Path(cfg.vault_path)
    folders = cfg.folders
    return base, folders


def _save_json(folder: str, name: str, obj: Dict[str, Any]) -> Dict[str, Any]:
    base, folders = _vault()
    target = base / getattr(folders, folder)
    target.mkdir(parents=True, exist_ok=True)
    p = target / f"{name}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(p)}


def _save_md(folder: str, name: str, content: str) -> Dict[str, Any]:
    base, folders = _vault()
    target = base / getattr(folders, folder)
    target.mkdir(parents=True, exist_ok=True)
    p = target / f"{name}.md"
    p.write_text(content, encoding="utf-8")
    return {"path": str(p)}


@register("health_check")
def step_health_check(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Check agent import, vault, qdrant ready"""
    import urllib.request
    ok = True
    issues = []
    try:
        _ = WorkingWebAgent(timeout=3)
    except Exception as e:
        ok = False
        issues.append(f"web_agent: {e}")
    base, _ = _vault()
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        ok = False
        issues.append(f"vault: {e}")
    try:
        with urllib.request.urlopen(os.environ.get("AI_STACK_QDRANT_URL", "http://localhost:6333") + "/readyz", timeout=2) as resp:
            _ = resp.read().decode("utf-8").strip()
    except Exception as e:
        issues.append(f"qdrant: {e}")
    return {"ok": ok, "issues": issues, "timestamp": datetime.now().isoformat()}


@register("search_web")
def step_search_web(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    queries = params.get("queries") or [params.get("query")] if params.get("query") else []
    agent = WorkingWebAgent(timeout=float(params.get("timeout", 10.0)), max_results=int(params.get("max_results", 5)))
    merged = {"agent": "Working Web Research Agent", "timestamp": datetime.now().isoformat(), "results": []}
    for q in queries:
        if not q:
            continue
        res = agent.execute(q)
        merged["results"].extend(res.get("results") or [])
    merged["count"] = len(merged["results"])
    return {"result": merged}


@register("filter_results")
def step_filter_results(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    obj = ctx.get("result") or {}
    items = obj.get("results") or []
    src = params.get("source")
    dom_re = params.get("domain_regex")
    date_from = params.get("date_from")
    if src:
        items = [r for r in items if r.get("source") == src]
    if dom_re:
        rx = re.compile(dom_re)
        def _match(u: str) -> bool:
            try:
                from urllib.parse import urlparse
                net = urlparse(u or "").netloc
                return bool(rx.search(net))
            except Exception:
                return False
        items = [r for r in items if _match(r.get("url", ""))]
    if date_from:
        # simple YYYY-MM-DD string compare; if relative given, ignore for now
        items = [r for r in items if (r.get("metadata") or {}).get("date", "")[:10] >= date_from]
    obj["results"] = items
    obj["count"] = len(items)
    return {"result": obj}


@register("save_index")
def step_save_index(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    obj = ctx.get("result") or {}
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = params.get("name") or f"agent-index-{ts}"
    out = _save_json("index", name, obj)
    return {"index_path": out["path"]}


@register("save_sources_markdown")
def step_save_sources_markdown(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    obj = ctx.get("result") or {}
    title = params.get("title") or "Agent Results"
    fm = _frontmatter({
        "date": datetime.now().strftime('%Y-%m-%d'),
        "Title": title,
        "Categories": "agents",
        "tags": ["agent", "sources"],
        "cssclasses": []
    })
    lines = [fm, f"# {title}", "", f"- Time: {obj.get('timestamp')} ", ""]
    for i, item in enumerate(obj.get("results") or [], 1):
        if 'error' in item:
            lines.append(f"{i}. ❌ {item['error']}")
            continue
        lines.append(f"{i}. [{item.get('source','Unknown')}] {item.get('title','Без названия')}")
        if item.get('url'):
            lines.append(f"   - URL: {item['url']}")
        if item.get('snippet'):
            lines.append(f"   - Snippet: {item['snippet'][:200]}...")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = params.get("name") or f"agent-sources-{ts}"
    content = "\n".join(lines)
    # Wikilinks из контента
    try:
        body_only = content.split("---\n", 2)[-1] if content.startswith("---\n") else content
    except Exception:
        body_only = content
    links = _extract_wikilinks(body_only)
    if links:
        links_md = "\n".join(f"- [[{t}]]" for t in links)
        content = content.rstrip() + f"\n\n## Ссылки\n\n{links_md}\n"
    out = _save_md("sources", name, content)
    # Обновим страницы-термины обратной ссылкой
    try:
        _ensure_wikilink_pages(links, name, title)
    except Exception:
        pass
    return {"sources_path": out["path"]}


@register("ingest_qdrant")
def step_ingest_qdrant(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    # reuse ingest module functions by invoking as a subprocess is ok, but we can inline minimal ingestion of ctx.result
    from ingest import flatten_result_items
    vs = VectorStore()
    obj = ctx.get("result") or {}
    items = flatten_result_items(obj)
    if not items:
        return {"upserted": 0}
    texts = [r["text"] for r in items]
    metas = [r["metadata"] for r in items]
    n = vs.upsert_texts(texts, metas)
    return {"upserted": n}


@register("vector_topk")
def step_vector_topk(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from vector_store import VectorStore
    vs = VectorStore()
    query = params.get("query") or ""
    k = int(params.get("k", 10))
    pts = vs.search(query, limit=k)
    title = params.get("title") or f"Top-{k} Vector Search"
    fm = _frontmatter({
        "date": datetime.now().strftime('%Y-%m-%d'),
        "Title": title,
        "Categories": "summaries",
        "tags": ["vector", "search"],
        "cssclasses": []
    })
    lines = [fm, f"# {title}: {query}", ""]
    for i, p in enumerate(pts, 1):
        payload = getattr(p, "payload", {})
        score = getattr(p, "score", 0.0)
        title = payload.get("title") or payload.get("file") or "Без названия"
        url = payload.get("url") or ""
        src = payload.get("source") or ""
        lines.append(f"{i}. [{src}] {title} — score: {round(float(score), 4)}")
        if url:
            lines.append(f"   - URL: {url}")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = params.get("name") or f"vector-topk-{ts}"
    content = "\n".join(lines)
    links = _extract_wikilinks(content)
    if links:
        links_md = "\n".join(f"- [[{t}]]" for t in links)
        content = content.rstrip() + f"\n\n## Ссылки\n\n{links_md}\n"
    out = _save_md("summaries", name, content)
    try:
        _ensure_wikilink_pages(links, name, title)
    except Exception:
        pass
    return {"summaries_path": out["path"]}


@register("create_daily_note")
def step_create_daily_note(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    base, _ = _vault()
    date = datetime.now().strftime("%Y-%m-%d")
    title = params.get("title") or f"Daily {date}"
    raw_body = params.get("content") or f"# {title}\n\n- Created: {datetime.now().isoformat()}\n"
    body = _normalize_text(raw_body) + "\n"
    auto = _auto_tags(body)
    base_tags = ["daily"]
    fm = _frontmatter({
        "date": date,
        "Title": title,
        "Categories": "daily",
        "tags": sorted(set(base_tags) | set(auto)),
        "cssclasses": [],
        "created_at": datetime.now().isoformat(timespec='seconds'),
        "last_modified": datetime.now().isoformat(timespec='seconds'),
    })
    folder_path = params.get("folder", "Notes/Journal/Daily")
    target = base / folder_path
    target.mkdir(parents=True, exist_ok=True)
    p = target / f"daily-{date}.md"
    # Добавим раздел ссылок по ключевым словам
    links = _extract_wikilinks(body)
    if links:
        links_md = "\n".join(f"- [[{title}]]" for title in links)
        body = body.rstrip() + f"\n\n## Ссылки\n\n{links_md}\n"
    p.write_text(fm + body, encoding="utf-8")
    # Создадим/обновим страницы-термины и добавим обратные ссылки
    try:
        _ensure_wikilink_pages(links, f"daily-{date}", title)
    except Exception:
        pass
    return {"daily_path": str(p)}

@register("append_daily_note")
def step_append_daily_note(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Append normalized text to today's daily note, update last_modified, and add timestamped section.
    Params:
      content: text to append
      header_format: 'iso' (default) or 'time' to format header as HH:MM
      folder: target folder (default Notes/Journal/Daily)
    """
    base, _ = _vault()
    date = datetime.now().strftime("%Y-%m-%d")
    title = params.get("title") or f"Daily {date}"
    folder_path = params.get("folder", "Notes/Journal/Daily")
    target = base / folder_path
    target.mkdir(parents=True, exist_ok=True)
    p = target / f"daily-{date}.md"

    now = datetime.now()
    now_iso = now.isoformat(timespec='seconds')
    hdr_fmt = str(params.get("header_format") or "iso").lower()
    if hdr_fmt == "time":
        section_header = f"## Запись {now.strftime('%H:%M')}"
    else:
        section_header = f"## Запись от {now_iso}"
    content = _normalize_text(params.get("content") or "")
    if not content:
        return {"daily_path": str(p), "appended": False}
    # Добавим wikilinks для нового контента
    links = _extract_wikilinks(content)
    if links:
        links_md = "\n".join(f"- [[{title}]]" for title in links)
        content = content.rstrip() + f"\n\n### Ссылки\n\n{links_md}\n"
    section = f"{section_header}\n\n{content}\n"

    if p.exists():
        existing = p.read_text(encoding="utf-8")
        # merge tags with auto-extracted from new content
        new_tags = _auto_tags(content)
        updated = _update_frontmatter_block(existing, {"last_modified": now_iso, "tags": new_tags})
        # append section
        updated = updated.rstrip() + "\n\n" + section
        p.write_text(updated, encoding="utf-8")
        # Обновим страницы-термины обратной ссылкой
        try:
            _ensure_wikilink_pages(links, f"daily-{date}", title)
        except Exception:
            pass
    else:
        # create new with frontmatter
        fm = _frontmatter({
            "date": date,
            "Title": title,
            "Categories": "daily",
            "tags": ["daily"],
            "cssclasses": [],
            "created_at": now_iso,
            "last_modified": now_iso,
        })
        body = f"# {title}\n\n{section}"
        p.write_text(fm + body, encoding="utf-8")
    return {"daily_path": str(p), "appended": True}

@register("create_weekly_note")
def step_create_weekly_note(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Create a weekly note with YAML frontmatter and basic template.
    Params:
      week_start: optional YYYY-MM-DD, otherwise uses current date's ISO week
      folder: target folder (default Notes/Journal/Weekly)
    """
    base, _ = _vault()
    now = datetime.now()
    iso_year, iso_week, _ = now.isocalendar()
    title = params.get("title") or f"Weekly {iso_year}-W{iso_week:02d}"
    folder_path = params.get("folder", "Notes/Journal/Weekly")
    target = base / folder_path
    target.mkdir(parents=True, exist_ok=True)
    fm = _frontmatter({
        "date": now.strftime('%Y-%m-%d'),
        "Title": title,
        "Categories": "weekly",
        "tags": ["weekly"],
        "cssclasses": [],
        "created_at": now.isoformat(timespec='seconds'),
        "last_modified": now.isoformat(timespec='seconds'),
    })
    body = params.get("content") or f"# {title}\n\n- Неделя: {iso_year}-W{iso_week:02d}\n\n## Итоги\n\n## Планы\n"
    body = _normalize_text(body) + "\n"
    links = _extract_wikilinks(body)
    if links:
        links_md = "\n".join(f"- [[{t}]]" for t in links)
        body = body.rstrip() + f"\n\n## Ссылки\n\n{links_md}\n"
    p = target / f"weekly-{iso_year}-W{iso_week:02d}.md"
    p.write_text(fm + body, encoding="utf-8")
    try:
        _ensure_wikilink_pages(links, f"weekly-{iso_year}-W{iso_week:02d}", title)
    except Exception:
        pass
    return {"weekly_path": str(p)}

# ---------------- Obsidian management steps ----------------
@register("obsidian_list_notes")
def step_obsidian_list_notes(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    cfg = load_config()
    vault = params.get("vault") or cfg.vault_path
    mgr = ObsidianManager(vault)
    subdir = params.get("subdir")
    pattern = params.get("pattern", "*.md")
    recursive = bool(params.get("recursive", True))
    exclude = params.get("exclude") or None
    files = mgr.list_notes(subdir=subdir, pattern=pattern, recursive=recursive, exclude_dirs=exclude)
    return {"obsidian_notes": files, "count": len(files)}

@register("obsidian_read_note")
def step_obsidian_read_note(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    file = params.get("file") or params.get("path")
    if not file:
        raise ValueError("obsidian_read_note: 'file' is required (relative to vault)")
    cfg = load_config()
    mgr = ObsidianManager(cfg.vault_path)
    content = mgr.read_note(str(file))
    return {"obsidian_note_path": str(file), "obsidian_note_content": content}

@register("obsidian_write_note")
def step_obsidian_write_note(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    file = params.get("file") or params.get("path")
    raw = params.get("content") or ""
    if not file:
        raise ValueError("obsidian_write_note: 'file' is required")
    # optional frontmatter template and auto tag/wikilinks
    add_frontmatter = bool(params.get("frontmatter", True))
    title = params.get("title")
    body = _normalize_text(str(raw))
    fm = ""
    if add_frontmatter:
        # infer title from file if not provided
        if not title:
            try:
                title = Path(str(file)).stem
            except Exception:
                title = "Note"
        tags = _auto_tags(body)
        fm = _frontmatter({
            "date": datetime.now().strftime('%Y-%m-%d'),
            "Title": title,
            "Categories": params.get("category", "notes"),
            "tags": sorted(set(tags)),
            "cssclasses": [],
            "created_at": datetime.now().isoformat(timespec='seconds'),
            "last_modified": datetime.now().isoformat(timespec='seconds'),
        })
    # wikilinks from body
    links = _extract_wikilinks(body)
    if links:
        links_md = "\n".join(f"- [[{t}]]" for t in links)
        body = body.rstrip() + f"\n\n## Ссылки\n\n{links_md}\n"
    content = (fm + (f"# {title}\n\n" if title and add_frontmatter else "") + body + ("\n" if not body.endswith("\n") else ""))
    cfg = load_config()
    mgr = ObsidianManager(cfg.vault_path)
    path = mgr.write_note(str(file), content)
    try:
        if links and title:
            _ensure_wikilink_pages(links, Path(str(file)).stem, title)
    except Exception:
        pass
    return {"obsidian_note_written": path}

@register("obsidian_append_note")
def step_obsidian_append_note(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    file = params.get("file") or params.get("path")
    raw = params.get("content") or ""
    header = params.get("header")
    if not file:
        raise ValueError("obsidian_append_note: 'file' is required")
    # normalize and enrich
    body = _normalize_text(str(raw))
    links = _extract_wikilinks(body)
    if links:
        links_md = "\n".join(f"- [[{t}]]" for t in links)
        body = body.rstrip() + f"\n\n### Ссылки\n\n{links_md}\n"
    cfg = load_config()
    mgr = ObsidianManager(cfg.vault_path)
    path = mgr.append_note(str(file), body, header=str(header) if header else None)
    try:
        # best effort backlink to this file title
        title = Path(str(file)).stem
        _ensure_wikilink_pages(links, title, title)
    except Exception:
        pass
    return {"obsidian_note_appended": path}

@register("obsidian_find")
def step_obsidian_find(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    query = params.get("query")
    if not query:
        raise ValueError("obsidian_find: 'query' is required")
    cfg = load_config()
    mgr = ObsidianManager(cfg.vault_path)
    results = mgr.search_in_notes(
        query=str(query),
        subdir=params.get("subdir"),
        regex=bool(params.get("regex", False)),
        case_sensitive=bool(params.get("case_sensitive", False)),
        limit=int(params.get("limit", 100)),
        exclude_dirs=params.get("exclude") or None,
    )
    return {"obsidian_find": results, "count": len(results)}

@register("ingest_vault_all")
def step_ingest_vault_all(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively ingest all *.md files from entire Vault into Qdrant.
    Optional params: exclude (list[str]), batch_k (ignored here), and limit per file size is handled by chunking in ingest-like fashion.
    """
    from vector_store import VectorStore
    from ingest import chunk_text
    from config import load_config
    cfg = load_config()
    mgr = ObsidianManager(cfg.vault_path)
    exclude = set(map(str.lower, params.get("exclude") or [".trash", ".obsidian", "Attachments", "attachments"]))
    vs = VectorStore()
    texts = []
    metas = []
    total_files = 0
    for p in Path(cfg.vault_path).rglob("*.md"):
        if not p.is_file():
            continue
        parts = set(map(str.lower, p.relative_to(Path(cfg.vault_path)).parts))
        if any(d in parts for d in exclude):
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue
        chunks = chunk_text(content)
        if not chunks:
            continue
        total_files += 1
        import hashlib
        for idx, ch in enumerate(chunks):
            chunk_hash = hashlib.md5(f"{p.name}|{idx}|{ch}".encode("utf-8")).hexdigest()
            texts.append(ch)
            metas.append({
                "chunk_id": chunk_hash,
                "source": "obsidian_md",
                "file": p.name,
                "vault": Path(cfg.vault_path).name,
                "title": p.stem,
                "domain": "",
                "url": "",
                "date": "",
            })
    upserted = 0
    if texts:
        upserted = vs.upsert_texts(texts, metas)
    return {"vault_files": total_files, "upserted": upserted}

@register("obsidian_backup")
def step_obsidian_backup(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    cfg = load_config()
    vault = params.get("vault") or cfg.vault_path
    out_dir = params.get("out_dir")
    mgr = ObsidianManager(vault)
    out = mgr.backup_settings(out_dir)
    return {"obsidian_backup_dir": str(out)}

@register("obsidian_list_plugins")
def step_obsidian_list_plugins(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    cfg = load_config()
    vault = params.get("vault") or cfg.vault_path
    mgr = ObsidianManager(vault)
    info = mgr.list_plugins()
    return {"obsidian_plugins": info}

@register("obsidian_enable_plugin")
def step_obsidian_enable_plugin(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    plugin_id = params.get("id") or params.get("plugin")
    if not plugin_id:
        raise ValueError("obsidian_enable_plugin: 'id' is required")
    cfg = load_config()
    vault = params.get("vault") or cfg.vault_path
    mgr = ObsidianManager(vault)
    mgr.enable_plugin(str(plugin_id))
    return {"obsidian_action": f"enabled {plugin_id}"}

@register("obsidian_disable_plugin")
def step_obsidian_disable_plugin(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    plugin_id = params.get("id") or params.get("plugin")
    if not plugin_id:
        raise ValueError("obsidian_disable_plugin: 'id' is required")
    cfg = load_config()
    vault = params.get("vault") or cfg.vault_path
    mgr = ObsidianManager(vault)
    mgr.disable_plugin(str(plugin_id))
    return {"obsidian_action": f"disabled {plugin_id}"}

@register("obsidian_enable_core_plugin")
def step_obsidian_enable_core_plugin(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    plugin_id = params.get("id") or params.get("plugin")
    if not plugin_id:
        raise ValueError("obsidian_enable_core_plugin: 'id' is required")
    cfg = load_config()
    vault = params.get("vault") or cfg.vault_path
    mgr = ObsidianManager(vault)
    mgr.enable_core_plugin(str(plugin_id))
    return {"obsidian_action": f"enabled core {plugin_id}"}

@register("obsidian_disable_core_plugin")
def step_obsidian_disable_core_plugin(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    plugin_id = params.get("id") or params.get("plugin")
    if not plugin_id:
        raise ValueError("obsidian_disable_core_plugin: 'id' is required")
    cfg = load_config()
    vault = params.get("vault") or cfg.vault_path
    mgr = ObsidianManager(vault)
    mgr.disable_core_plugin(str(plugin_id))
    return {"obsidian_action": f"disabled core {plugin_id}"}

@register("obsidian_install_plugin_zip")
def step_obsidian_install_plugin_zip(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    zip_path = params.get("zip") or params.get("path")
    if not zip_path:
        raise ValueError("obsidian_install_plugin_zip: 'zip' is required")
    dir_name = params.get("dir")
    cfg = load_config()
    vault = params.get("vault") or cfg.vault_path
    mgr = ObsidianManager(vault)
    pid = mgr.install_plugin_from_zip(str(zip_path), plugin_dir_name=dir_name)
    return {"obsidian_plugin_installed": pid}

@register("obsidian_install_plugin_url")
def step_obsidian_install_plugin_url(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    url = params.get("url")
    if not url:
        raise ValueError("obsidian_install_plugin_url: 'url' is required")
    dir_name = params.get("dir")
    cfg = load_config()
    vault = params.get("vault") or cfg.vault_path
    mgr = ObsidianManager(vault)
    pid = mgr.install_plugin_from_url(str(url), plugin_dir_name=dir_name)
    return {"obsidian_plugin_installed": pid}

@register("obsidian_set_theme")
def step_obsidian_set_theme(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    theme = params.get("theme")
    if not theme:
        raise ValueError("obsidian_set_theme: 'theme' is required")
    cfg = load_config()
    vault = params.get("vault") or cfg.vault_path
    mgr = ObsidianManager(vault)
    mgr.set_theme(str(theme))
    return {"obsidian_theme": theme}

@register("obsidian_enable_snippet")
def step_obsidian_enable_snippet(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    name = params.get("name") or params.get("file")
    if not name:
        raise ValueError("obsidian_enable_snippet: 'name' (or 'file') is required")
    cfg = load_config()
    vault = params.get("vault") or cfg.vault_path
    mgr = ObsidianManager(vault)
    mgr.enable_snippet(str(name))
    return {"obsidian_snippet_enabled": str(name)}

@register("obsidian_disable_snippet")
def step_obsidian_disable_snippet(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    name = params.get("name") or params.get("file")
    if not name:
        raise ValueError("obsidian_disable_snippet: 'name' (or 'file') is required")
    cfg = load_config()
    vault = params.get("vault") or cfg.vault_path
    mgr = ObsidianManager(vault)
    mgr.disable_snippet(str(name))
    return {"obsidian_snippet_disabled": str(name)}

@register("obsidian_write_snippet")
def step_obsidian_write_snippet(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    name = params.get("name") or params.get("file")
    content = params.get("content")
    if not name or content is None:
        raise ValueError("obsidian_write_snippet: 'name' and 'content' are required")
    cfg = load_config()
    vault = params.get("vault") or cfg.vault_path
    mgr = ObsidianManager(vault)
    p = mgr.ensure_snippet_file(str(name), str(content))
    return {"obsidian_snippet_path": str(p)}

@register("obsidian_set_setting")
def step_obsidian_set_setting(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from config import load_config
    file = params.get("file") or params.get("settings_file") or "app.json"
    path = params.get("path") or params.get("json_path")
    value = params.get("value")
    if not path:
        raise ValueError("obsidian_set_setting: 'path' is required (dot-notation)")
    cfg = load_config()
    vault = params.get("vault") or cfg.vault_path
    mgr = ObsidianManager(vault)
    mgr.set_setting(str(file), str(path), value)
    return {"obsidian_setting_updated": {"file": file, "path": path}}

@register("transcribe_inbox")
def step_transcribe_inbox(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Scan Inbox/Audio and create a simple report (kept for quick checks)."""
    base, folders = _vault()
    inbox = params.get("inbox", "Inbox/Audio")
    audio_dir = base / inbox
    audio_dir.mkdir(parents=True, exist_ok=True)
    files = [p.name for p in audio_dir.glob("*.*")]
    lines = ["# Transcription Inbox", "", f"Files found: {len(files)}"]
    for f in files:
        lines.append(f"- {f}")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = _save_md("summaries", f"transcription-inbox-{ts}", "\n".join(lines))
    return {"transcription_report": out["path"]}

@register("transcribe_inbox_whisper")
def step_transcribe_inbox_whisper(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Transcribe all audio files in Vault Inbox/Audio using faster-whisper.
    Env:
      WHISPER_MODEL (default: small)
      WHISPER_DEVICE (auto/cpu) — mps/cuda if supported
      WHISPER_COMPUTE (int8/int8_float16/float16/float32)
    Params:
      inbox: relative folder in Vault (default Inbox/Audio)
      model, device, compute_type: override env
      max_chars: group segments into chunks up to N chars for ingest (default 2000)
      per_chunk_notes: create separate notes per chunk (default false)
      ingest: bool (default true)
    """
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as e:
        return {"error": f"faster-whisper not installed: {e}"}

    base, folders = _vault()
    inbox = params.get("inbox", "Inbox/Audio")
    audio_dir = base / inbox
    audio_dir.mkdir(parents=True, exist_ok=True)

    model_name = os.environ.get("WHISPER_MODEL", params.get("model", "small"))
    device = os.environ.get("WHISPER_DEVICE", params.get("device", "auto"))
    compute = os.environ.get("WHISPER_COMPUTE", params.get("compute_type", "int8"))

    model = WhisperModel(model_name, device=device, compute_type=compute)

    max_chars = int(params.get("max_chars", 2000))
    per_chunk_notes = bool(params.get("per_chunk_notes", False))

    processed = []
    for p in sorted(audio_dir.glob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg"}:
            continue
        try:
            segments, info = model.transcribe(str(p), beam_size=5)
            # collect segments
            segs = list(segments)
            # build full text
            def fmt(seg):
                return f"[{seg.start:.2f}-{seg.end:.2f}] {seg.text.strip()}"
            full_text = "\n".join(fmt(s) for s in segs)
            # chunking for ingest/notes
            chunks = []
            buf = []
            cur_len = 0
            start_t = None
            for s in segs:
                t = fmt(s)
                if start_t is None:
                    start_t = s.start
                if cur_len + len(t) + 1 > max_chars and buf:
                    end_t = s.end
                    chunks.append((start_t, end_t, "\n".join(buf)))
                    buf = [t]
                    cur_len = len(t)
                    start_t = s.start
                else:
                    buf.append(t)
                    cur_len += len(t) + 1
            if buf:
                end_t = segs[-1].end if segs else 0.0
                chunks.append((start_t or 0.0, end_t, "\n".join(buf)))

            # Save master note
            title = f"Transcription: {p.stem}"
            md = f"# {title}\n\n- File: {p.name}\n- Duration: {getattr(info, 'duration', 0):.1f}s\n- Language: {getattr(info, 'language', 'unk')}\n\n{full_text}\n"
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            name = f"transcription-{p.stem}-{ts}"
            out = _save_md("sources", name, md)
            entry = {"file": p.name, "note": out["path"], "chunks": []}

            # Optional per-chunk notes
            if per_chunk_notes:
                for idx, (st, et, text) in enumerate(chunks, 1):
                    ctitle = f"Transcription chunk: {p.stem} [{st:.0f}-{et:.0f}s]"
                    cmd = f"# {ctitle}\n\n{text}\n"
                    cname = f"transcription-{p.stem}-chunk{idx}-{ts}"
                    cout = _save_md("sources", cname, cmd)
                    entry["chunks"].append({"note": cout["path"], "start": st, "end": et})

            processed.append(entry)
        except Exception as e:
            processed.append({"file": p.name, "error": str(e)})

    # Optional: ingest transcriptions into Qdrant
    if params.get("ingest", True) and processed:
        from vector_store import VectorStore
        vs = VectorStore()
        texts = []
        metas = []
        for it in processed:
            # prefer chunks if produced, else whole note
            if it.get("chunks"):
                for ch in it["chunks"]:
                    try:
                        note_path = Path(ch["note"]) if ch["note"].startswith("/") else base / ch["note"]
                        content = Path(note_path).read_text(encoding="utf-8")
                        texts.append(content)
                        metas.append({
                            "source": "obsidian_md",
                            "file": Path(note_path).name,
                            "title": Path(note_path).stem,
                            "domain": "",
                            "url": "",
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "section": f"{ch.get('start',0):.0f}-{ch.get('end',0):.0f}s",
                        })
                    except Exception:
                        continue
            elif "note" in it:
                try:
                    note_path = Path(it["note"]) if it["note"].startswith("/") else base / it["note"]
                    content = Path(note_path).read_text(encoding="utf-8")
                    texts.append(content)
                    metas.append({
                        "source": "obsidian_md",
                        "file": Path(note_path).name,
                        "title": Path(note_path).stem,
                        "domain": "",
                        "url": "",
                        "date": datetime.now().strftime("%Y-%m-%d"),
                    })
                except Exception:
                    pass
        if texts:
            vs.upsert_texts(texts, metas)
    return {"transcribed": processed}

