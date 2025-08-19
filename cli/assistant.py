import sys
import json
import shlex
from typing import Any, Dict, List
from datetime import datetime

from orchestrator.registry import Registry
from config import load_config

from pipelines import steps  # noqa: F401 - ensure step functions are registered via decorators
# Простой rule-based планировщик
# На вход: текст, на выход: список шагов {name, params}

def plan(user_text: str) -> List[Dict[str, Any]]:
    t = user_text.lower().strip()
    steps: List[Dict[str, Any]] = []

    if not t:
        return steps

    # Шаблоны: ежедневка и создание заметок
    if any(k in t for k in ["ежеднев", "daily", "дневник", "создай заметку", "создать заметку", "заметка сегодня"]):
        # Извлечём содержимое после ключевых слов
        content = user_text  # весь текст как содержимое (включая переносы)
        # Найдём первое вхождение ключевого слова и возьмём весь текст после него (без принудительного обрезания по разделителям)
        for keyword in ["создай заметку", "создать заметку", "заметка сегодня", "ежеднев", "daily", "дневник"]:
            if keyword in t:
                idx = user_text.lower().find(keyword)
                if idx >= 0:
                    after_keyword = user_text[idx + len(keyword):]
                    # Уберём ведущие пробелы и одиночные разделители
                    after_keyword = after_keyword.lstrip()
                    if after_keyword[:1] in ".:!":
                        after_keyword = after_keyword[1:].lstrip()
                    if after_keyword:
                        content = after_keyword
                break
        
        title = f"Daily {datetime.now().strftime('%Y-%m-%d')}"
        steps.append({"name": "create_daily_note", "params": {
            "title": title,
            "content": f"# {title}\n\n{content}\n"
        }})
        return steps

    # Поиск в вебе ➜ сохранить источники ➜ (опц.)индекс ➜ топK
    if any(k in t for k in ["поиск", "search", "гугл", "web"]):
        # Извлечём фразу после двоеточия, если есть
        query = t
        if ":" in t:
            query = t.split(":", 1)[1].strip()
        steps.append({"name": "search_web", "params": {"query": query}})
        # фильтрация по доменам по ключевым словам
        if "только" in t and "домен" in t:
            # очень упрощённо
            steps.append({"name": "filter_results", "params": {"domain_regex": r"(.*)"}})
        steps.append({"name": "save_sources_markdown", "params": {"title": f"Agent Sources: {query[:40]}"}})
        if any(k in t for k in ["индекс", "index", "вектор", "qdrant"]):
            steps.append({"name": "ingest_qdrant", "params": {}})
        if any(k in t for k in ["топ", "top", "выдача"]):
            steps.append({"name": "vector_topk", "params": {"query": query, "k": 10}})
        return steps

    # Добавление в сегодняшнюю заметку
    if any(k in t for k in ["добавь к сегодняшней", "допиши к сегодняшней", "добавь в ежедневку", "допиши в ежедневку", "append daily"]):
        # извлечём содержимое после ключевых фраз
        content = user_text
        for keyword in ["добавь к сегодняшней", "допиши к сегодняшней", "добавь в ежедневку", "допиши в ежедневку", "append daily"]:
            if keyword in t:
                idx = user_text.lower().find(keyword)
                if idx >= 0:
                    after = user_text[idx + len(keyword):].lstrip()
                    if after[:1] in ":.!":
                        after = after[1:].lstrip()
                    if after:
                        content = after
                break
        header_format = "time" if ("время" in t or "короткий" in t) else "iso"
        steps.append({"name": "append_daily_note", "params": {"content": content, "header_format": header_format}})
        return steps

    # Недельная заметка
    if any(k in t for k in ["недел", "weekly", "week note", "недельная заметка"]):
        steps.append({"name": "create_weekly_note", "params": {}})
        return steps

    # Топ-K по базе
    if any(k in t for k in ["топ", "top", "выдача"]):
        # Извлечём запрос
        query = t
        if ":" in t:
            query = t.split(":", 1)[1].strip()
        steps.append({"name": "vector_topk", "params": {"query": query, "k": 10}})
        return steps

    # По умолчанию: лёгкий веб-поиск
    steps.append({"name": "search_web", "params": {"query": user_text}})
    steps.append({"name": "save_sources_markdown", "params": {"title": f"Agent Sources: {user_text[:40]}"}})
    return steps

def confirm(plan_steps: List[Dict[str, Any]]) -> bool:
    print("Предлагаемый план:")
    for i, s in enumerate(plan_steps, 1):
        print(f" {i}. {s['name']} {json.dumps(s.get('params', {}), ensure_ascii=False)}")
    ans = input("Выполнить? [y/N]: ")
    if ans is None:
        return False
    ans = ans.strip().lower()
    # Принимаем любые ответы, начинающиеся на y/д, и общие формы
    return bool(ans) and (ans.startswith("y") or ans.startswith("д") or ans in ("yes", "да"))


def run(plan_steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {}
    for s in plan_steps:
        name = s["name"]
        params = dict(s.get("params") or {})
        fn = Registry.get(name)
        if not fn:
            print(f"⚠️ Шаг '{name}' не найден, пропускаю.")
            continue
        try:
            res = fn(params, ctx)
            if isinstance(res, dict):
                ctx.update(res)
            print(f"✅ {name} -> {json.dumps(res, ensure_ascii=False)}")
        except Exception as e:
            print(f"❌ {name} ошибка: {e}")
            break
    return ctx


def repl():
    cfg = load_config()
    print("AI Assistant (режим подтверждения). Вольт:", cfg.vault_path)
    print("Напишите запрос (Ctrl+C для выхода). Примеры: 'ежедневка', 'поиск: LLM для продакшн', 'топ: безопасность LLM'")
    while True:
        try:
            text = input("\nВы: ").strip()
            if not text:
                continue
            steps = plan(text)
            if not steps:
                print("Не понял запрос. Попробуйте иначе.")
                continue
            if not confirm(steps):
                print("Отменено.")
                continue
            ctx = run(steps)
            # краткий итог
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\nИтог ({ts}): {json.dumps({k: v for k, v in ctx.items() if isinstance(v, str)}, ensure_ascii=False)}")
        except KeyboardInterrupt:
            print("\nВыход.")
            break
        except EOFError:
            print("\nВыход.")
            break


if __name__ == "__main__":
    repl()

