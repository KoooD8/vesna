#!/usr/bin/env python3
"""
Простой чат с AI агентами
"""

import sys
import os
import argparse
import logging
import json
from datetime import datetime
from pathlib import Path

# Добавляем текущую папку в путь Python
sys.path.append(os.path.dirname(__file__))

# Загружаем переменные окружения из .env, если есть
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    # теперь экспортируется из пакета
    from agents.web_research import WorkingWebAgent
    web_agent = None  # инициализируем позже с параметрами CLI
    AGENT_IMPORT_OK = True
except ImportError as e:
    print(f"❌ Ошибка импорта Working Web Research Agent: {e}")
    web_agent = None
    AGENT_IMPORT_OK = False

def print_results(result):
    """Красиво показать результаты (нормализованная схема)"""
    print(f"\n🤖 Агент: {result.get('agent','Web Agent')}")
    print(f"📊 Найдено результатов: {result.get('count',0)}")
    print(f"⏰ Время: {result.get('timestamp','')}")
    
    items = result.get('results') or []
    if items:
        print("\n📋 Результаты:")
        for i, item in enumerate(items, 1):
            if 'error' in item:
                print(f"{i}. ❌ {item['error']}")
                continue

            title = item.get('title', 'Без названия')
            url = item.get('url', '')
            source = item.get('source', 'Unknown')
            snippet = (item.get('snippet') or '')[:200]
            meta = item.get('metadata') or {}

            print(f"\n{i}. [{source}] 📝 {title}")
            if snippet:
                print(f"   📝 {snippet}...")
            # Специализированные метаданные по источникам
            if source == 'Reddit':
                print(f"   📍 r/{meta.get('subreddit','unknown')} | 👤 u/{meta.get('author','unknown')}")
                print(f"   ⬆️ {meta.get('score',0)} очков")
            if source == 'Google News' and meta.get('date'):
                print(f"   📅 {meta.get('date')}")
            if url:
                print(f"   🔗 {url}")
    else:
        print("❌ Результатов не найдено")

def build_parser():
    p = argparse.ArgumentParser(description="AI Agents Chat (Web Research)")
    p.add_argument("-v", "--verbose", action="store_true", help="подробные логи (DEBUG)")
    p.add_argument("--health", action="store_true", help="проверить доступность сервисов и выйти")
    p.add_argument("--timeout", type=float, default=10.0, help="таймаут запросов, сек")
    p.add_argument("--max-results", type=int, default=5, help="макс. результатов на источник")
    p.add_argument("--retries", type=int, default=2, help="число повторов при ошибках")
    p.add_argument("--backoff", type=float, default=0.5, help="коэффициент backoff между повторами")

    sub = p.add_subparsers(dest="command")

    # list-steps: показать доступные шаги оркестратора
    sp_ls = sub.add_parser("list-steps", help="показать доступные шаги pipeline (Registry)")

    # Общие фильтры для выборок/печати и для vector search
    for sp in [p]:
        sp.add_argument("--filter-source", choices=["DuckDuckGo", "Reddit", "Google News", "test", "obsidian_md"], help="фильтр по источнику")
        sp.add_argument("--filter-domain", help="фильтр по домену (example.com)")
        sp.add_argument("--filter-date", help="фильтр по дате YYYY-MM-DD (для новостей/ингеста)")

    # search:web
    sp_web = sub.add_parser("search:web", help="выполнить веб-поиск (DDG/Reddit/RSS)")
    sp_web.add_argument("query", nargs="+", help="запрос для поиска")
    sp_web.add_argument("--save", action="store_true", help="сохранять результаты в Obsidian Sources")

    # search:news
    sp_news = sub.add_parser("search:news", help="поиск новостей (Google News RSS)")
    sp_news.add_argument("query", nargs="+", help="запрос для новостей")
    sp_news.add_argument("--save", action="store_true", help="сохранять результаты в Obsidian Sources")

    # index:results
    sp_index = sub.add_parser("index:results", help="сохранить JSON результаты в Obsidian Index")
    sp_index.add_argument("json_file", help="путь к JSON с результатами execute()")
    sp_index.add_argument("--name", default=None, help="имя файла индекса без расширения")

    # summarize:file
    sp_sum = sub.add_parser("summarize:file", help="создать краткую сводку из файла с результатами")
    sp_sum.add_argument("json_file", help="путь к JSON с результатами execute()")
    sp_sum.add_argument("--title", default=None, help="заголовок заметки в Summaries")

    # summarize:topk — векторный поиск и запись топ-K в Summaries
    sp_topk = sub.add_parser("summarize:topk", help="векторный поиск по Qdrant и сохранение Top-K в Summaries")
    sp_topk.add_argument("query", nargs="+", help="текст запроса")
    sp_topk.add_argument("--k", type=int, default=10, help="количество результатов")
    sp_topk.add_argument("--title", default=None, help="заголовок заметки")

    return p

def load_vault_config():
    from config import load_config
    cfg = load_config()
    return {"vault_path": cfg.vault_path, "folders": {
        "sources": cfg.folders.sources,
        "summaries": cfg.folders.summaries,
        "entities": cfg.folders.entities,
        "index": cfg.folders.index,
        "logs": cfg.folders.logs,
    }}

def save_note(base_dir: Path, folder: str, name: str, content: str):
    target_dir = base_dir / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    print(f"📝 Saved: {path}")

def save_json(base_dir: Path, folder: str, name: str, obj: dict):
    target_dir = base_dir / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{name}.json"
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"🗂️ Saved JSON: {path}")

def make_results_markdown(result: dict, title: str) -> str:
    lines = [f"# {title}", "", f"- Agent: {result.get('agent')}", f"- Time: {result.get('timestamp')}",""]
    for i, item in enumerate(result.get('results') or [], 1):
        if 'error' in item:
            lines.append(f"{i}. ❌ {item['error']}")
            continue
        lines.append(f"{i}. [{item.get('source','Unknown')}] {item.get('title','Без названия')}")
        if item.get('url'):
            lines.append(f"   - URL: {item['url']}")
        if item.get('snippet'):
            lines.append(f"   - Snippet: {item['snippet'][:300]}...")
        meta = item.get('metadata') or {}
        if meta:
            lines.append(f"   - Meta: {json.dumps(meta, ensure_ascii=False)}")
    return "\n".join(lines)

def run_interactive(args):
    print("🤖 AI Agents Chat")
    print("=" * 30)
    print("Доступные команды:")
    print("• help - помощь")
    print("• quit - выход")
    print("• Любой текст - поиск через Web Research Agent")
    while True:
        try:
            user_input = input("\n💬 Ваш запрос: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ['quit', 'exit', 'выход']:
                print("👋 До свидания!")
                break
            if user_input.lower() == 'help':
                print("\n📚 Справка:")
                print("• Команды CLI: search:web, search:news, index:results, summarize:file")
                continue
            if web_agent:
                result = web_agent.execute(user_input)
                print_results(result)
            else:
                print("❌ Web Research Agent недоступен")
        except KeyboardInterrupt:
            print("\n👋 Выход")
            break
        except Exception as e:
            print(f"❌ Ошибка: {e}")

def main():
    parser = build_parser()
    args = parser.parse_args()

    # Если команда не указана — показать помощь и список доступных команд
    if not args.health and args.command is None:
        available = ["search:web", "search:news", "index:results", "summarize:file", "summarize:topk"]
        print("❓ Не указана команда. Доступные команды:")
        for c in available:
            print(f"  - {c}")
        parser.print_help()
        sys.exit(2)

    # базовая настройка логов (поддержка JSON если AI_STACK_JSON_LOGS=1)
    level = logging.DEBUG if args.verbose else logging.INFO
    if os.environ.get("AI_STACK_JSON_LOGS", "0") == "1":
        from logging_setup import setup_json_logger
        setup_json_logger(level)
    else:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    global web_agent
    if AGENT_IMPORT_OK:
        try:
            web_agent = WorkingWebAgent(
                timeout=args.timeout,
                max_results=args.max_results,
                retries=args.retries,
                backoff=args.backoff,
                verbose=args.verbose
            )
        except Exception as e:
            print(f"❌ Не удалось инициализировать агент: {e}")
            web_agent = None
    else:
        print("❌ Web Research Agent недоступен (импорт не удался)")

    # health-check режим: проверить доступность ключевых сервисов
    if args.health:
        ok = True
        # Проверим импорт агента
        if not AGENT_IMPORT_OK:
            print("❌ Web Research Agent импорт: FAIL")
            ok = False
        else:
            print("✅ Web Research Agent импорт: OK")
        # Проверим конфиг Vault
        cfg = load_vault_config()
        base = Path(cfg["vault_path"])
        try:
            base.mkdir(parents=True, exist_ok=True)
            print(f"✅ Vault путь: {base} доступен")
        except Exception as e:
            print(f"❌ Vault путь ошибка: {e}")
            ok = False
        # Проверим Qdrant readyz (локально)
        try:
            import urllib.request
            with urllib.request.urlopen(os.environ.get("AI_STACK_QDRANT_URL", "http://localhost:6333") + "/readyz", timeout=2) as resp:
                ready = resp.read().decode("utf-8").strip()
                print("✅ Qdrant readyz:", ready)
        except Exception as e:
            print(f"⚠️  Qdrant readyz не доступен: {e}")
        # Проверка лёгкого vector search запроса (если Qdrant поднят)
        try:
            from vector_store import VectorStore
            vs = VectorStore()
            _ = vs.search("health-check", limit=1)
            print("✅ Vector search: OK")
        except Exception as e:
            print(f"⚠️  Vector search ошибка: {e}")
        print("OK" if ok else "FAIL")
        return 0
    # если нет сабкоманд — интерактив
    if not args.command:
        return run_interactive(args)

    # загрузим конфиг Vault
    cfg = load_vault_config()
    base = Path(cfg["vault_path"])
    folders = cfg["folders"]

    # обработка сабкоманд
    def _apply_filters(obj: dict) -> dict:
        items = obj.get("results") or []
        src = getattr(args, "filter_source", None)
        dom = getattr(args, "filter_domain", None)
        fdate = getattr(args, "filter_date", None)
        if src:
            items = [r for r in items if r.get("source") == src]
        if dom:
            def _match_domain(u: str) -> bool:
                try:
                    from urllib.parse import urlparse
                    net = urlparse(u or "").netloc
                    return net.endswith(dom)
                except Exception:
                    return False
            items = [r for r in items if _match_domain(r.get("url", ""))]
        if fdate:
            # Оставим только записи, где metadata.date >= YYYY-MM-DD (префиксное сравнение)
            items = [r for r in items if (r.get("metadata") or {}).get("date","")[:10] >= fdate]
        obj["results"] = items
        obj["count"] = len(items)
        return obj

    if args.command == "search:web":
        query = " ".join(args.query)
        result = web_agent.execute(query) if web_agent else {"results": [], "agent":"n/a","timestamp":datetime.now().isoformat(),"count":0}
        result = _apply_filters(result)
        print_results(result)
        if getattr(args, "save", False):
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            name = f"search-web-{ts}"
            save_json(base, folders["index"], name, result)
            md = make_results_markdown(result, f"Search Web: {query}")
            save_note(base, folders["sources"], name, md)

    elif args.command == "search:news":
        query = " ".join(args.query)
        result = web_agent.execute(query) if web_agent else {"results": [], "agent":"n/a","timestamp":datetime.now().isoformat(),"count":0}
        result["results"] = [r for r in (result.get("results") or []) if r.get("source") == "Google News"]
        result = _apply_filters(result)
        print_results(result)
        if getattr(args, "save", False):
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            name = f"search-news-{ts}"
            save_json(base, folders["index"], name, result)
            md = make_results_markdown(result, f"Search News: {query}")
            save_note(base, folders["sources"], name, md)

    elif args.command == "index:results":
        jf = Path(args.json_file)
        if not jf.exists():
            print(f"❌ Файл не найден: {jf}")
            return
        with open(jf, "r", encoding="utf-8") as f:
            obj = json.load(f)
        name = args.name or jf.stem
        save_json(base, folders["index"], name, obj)
        print("✅ Индексация завершена")
 
    elif args.command == "summarize:file":
        jf = Path(args.json_file)
        if not jf.exists():
            print(f"❌ Файл не найден: {jf}")
            return
        with open(jf, "r", encoding="utf-8") as f:
            obj = json.load(f)
        title = args.title or f"Summary {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        md = make_results_markdown(obj, title)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"summary-{ts}"
        save_note(base, folders["summaries"], name, md)
        print("✅ Сводка сохранена")
 
    elif args.command == "list-steps":
        from orchestrator.registry import Registry
        print("Доступные шаги (Registry):")
        for k in sorted(Registry.keys()):
            print(f" - {k}")

    elif args.command == "summarize:topk":
        # Векторный поиск в Qdrant с server-side фильтрами и записью в Summaries
        from vector_store import VectorStore
        query = " ".join(args.query)
        vs = VectorStore()
        # Собираем фильтры
        src = getattr(args, "filter_source", None)
        dom = getattr(args, "filter_domain", None)
        fdate = getattr(args, "filter_date", None)
        k = getattr(args, "k", 10)
        points = vs.search(query, limit=k, source=src, domain=dom, date_from=fdate)
        # Рендер Markdown
        lines = [f"# Top-{k} Vector Search: {query}", ""]
        for i, p in enumerate(points, 1):
            payload = p.payload if isinstance(p, dict) else getattr(p, "payload", {})  # подстрахуемся под мок
            score = p.get("score") if isinstance(p, dict) else getattr(p, "score", 0.0)
            title = payload.get("title") or payload.get("file") or "Без названия"
            url = payload.get("url") or ""
            src2 = payload.get("source") or ""
            lines.append(f"{i}. [{src2}] {title} — score: {round(float(score), 4)}")
            if url:
                lines.append(f"   - URL: {url}")
        md = "\n".join(lines)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"vector-topk-{ts}"
        title_opt = getattr(args, "title", None)
        if title_opt:
            md = "# " + title_opt + "\n\n" + "\n".join(lines[1:])
        save_note(base, folders["summaries"], name, md)
        print("✅ Top-K сохранены в Summaries")
 

if __name__ == "__main__":
    main()
