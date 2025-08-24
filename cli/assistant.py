import sys
import json
import shlex
import re
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

    # Obsidian management commands
    if ("obsidian" in t) or ("обсидиан" in t):
        # Extract command substring after prefix like "obsidian:" or the word itself
        cmd_text = user_text
        lt = user_text.lower()
        for prefix in ["obsidian:", "обсидиан:"]:
            i = lt.find(prefix)
            if i >= 0:
                cmd_text = user_text[i + len(prefix):].strip()
                break
        else:
            # If starts with the word without colon, drop it
            tokens = user_text.split(maxsplit=1)
            if tokens and tokens[0].lower() in ("obsidian", "обсидиан"):
                cmd_text = tokens[1] if len(tokens) > 1 else ""

        def _split_segments(s: str) -> List[str]:
            parts = re.split(r"[;，,]+", s)
            out: List[str] = []
            for p in parts:
                p = p.strip()
                if not p:
                    continue
                # further split on ' и ' if present and no URL
                if " и " in p and ("http://" not in p and "https://" not in p):
                    out.extend([x.strip() for x in p.split(" и ") if x.strip()])
                else:
                    out.append(p)
            return out

        def _parse_value(raw: str):
            s = raw.strip().strip("\u00ab\u00bb\"'")
            sl = s.lower()
            if sl in ("true", "false", "yes", "no", "on", "off", "да", "нет", "вкл", "выкл"):
                return sl in ("true", "yes", "on", "да", "вкл")
            # int/float
            try:
                if re.fullmatch(r"[-+]?\d+", s):
                    return int(s)
                if re.fullmatch(r"[-+]?\d+\.\d+", s):
                    return float(s)
            except Exception:
                pass
            # JSON literal fallback
            try:
                return json.loads(s)
            except Exception:
                return s

        def _maybe_setting_key(name: str) -> bool:
            # Heuristic: treat as setting if contains dot or CamelCase letter
            return ("." in name) or any(ch.isupper() for ch in name)

        segments = _split_segments(cmd_text)
        for seg in segments:
            seg_l = seg.lower()
            # backup
            if re.search(r"\b(backup|бэкап)\b", seg_l):
                steps.append({"name": "obsidian_backup", "params": {}})
                continue
            # list plugins
            if ("список" in seg_l and "плагин" in seg_l) or ("list" in seg_l and "plugin" in seg_l):
                steps.append({"name": "obsidian_list_plugins", "params": {}})
                continue
            # install from URL
            m = re.search(r"https?://\S+\.zip", seg, flags=re.IGNORECASE)
            if m and ("установ" in seg_l or "install" in seg_l):
                steps.append({"name": "obsidian_install_plugin_url", "params": {"url": m.group(0)}})
                continue
            # install from zip path
            if (".zip" in seg) and ("установ" in seg_l or "install" in seg_l):
                # naive path extraction: last token ending with .zip
                cand = None
                for tok in re.split(r"\s+", seg):
                    if tok.endswith(".zip"):
                        cand = tok
                if cand:
                    steps.append({"name": "obsidian_install_plugin_zip", "params": {"zip": cand}})
                    continue
            # theme
            if ("тему" in seg_l or "theme" in seg_l) and any(k in seg_l for k in ("постав", "установ", "switch", "set")):
                # take last word(s) after the keyword 'тему'|'theme'
                m2 = re.search(r"(?:тему|theme)\s+(.+)$", seg, flags=re.IGNORECASE)
                theme = (m2.group(1).strip() if m2 else seg).strip().strip('"\'')
                steps.append({"name": "obsidian_set_theme", "params": {"theme": theme}})
                continue
            # snippet enable/disable/write
            if "сниппет" in seg_l or "snippet" in seg_l:
                # write snippet: look for name: content
                if any(k in seg_l for k in ("запиши", "создай", "write", "add")) and ":" in seg:
                    name_part, content_part = seg.split(":", 1)
                    # extract name after word 'сниппет'
                    m3 = re.search(r"(?:сниппет|snippet)\s+([\w\-. ]+)", name_part, flags=re.IGNORECASE)
                    name = (m3.group(1).strip() if m3 else "snippet.css")
                    steps.append({"name": "obsidian_write_snippet", "params": {"name": name, "content": content_part.strip()}})
                    continue
                if any(k in seg_l for k in ("включ", "enable")):
                    m4 = re.search(r"(?:сниппет|snippet)\s+([\w\-. ]+)$", seg, flags=re.IGNORECASE)
                    name = (m4.group(1).strip() if m4 else seg)
                    steps.append({"name": "obsidian_enable_snippet", "params": {"name": name}})
                    continue
                if any(k in seg_l for k in ("выключ", "disable")):
                    m5 = re.search(r"(?:сниппет|snippet)\s+([\w\-. ]+)$", seg, flags=re.IGNORECASE)
                    name = (m5.group(1).strip() if m5 else seg)
                    steps.append({"name": "obsidian_disable_snippet", "params": {"name": name}})
                    continue
            # settings explicit
            if ("настройк" in seg_l or "setting" in seg_l) and any(k in seg_l for k in ("установ", "постав", "set")):
                # pattern: настройку key=value or key: value
                m6 = re.search(r"(?:настройк\w*|setting)\s+([\w\.]+)\s*(?:=|:)\s*(.+)$", seg, flags=re.IGNORECASE)
                if m6:
                    key, val = m6.group(1), m6.group(2)
                    steps.append({"name": "obsidian_set_setting", "params": {"file": "app.json", "path": key, "value": _parse_value(val)}})
                    continue
            # core plugin
            if ("core" in seg_l or "базов" in seg_l or "ядро" in seg_l) and ("плагин" in seg_l or "plugin" in seg_l):
                if any(k in seg_l for k in ("включ", "enable")):
                    m7 = re.search(r"(?:core\s+plugin|базов\w*\s+плагин|ядро\s+плагин|core)\s+([\w\-\.]+)$", seg, flags=re.IGNORECASE)
                    pid = (m7.group(1) if m7 else seg.split()[-1])
                    steps.append({"name": "obsidian_enable_core_plugin", "params": {"id": pid}})
                    continue
                if any(k in seg_l for k in ("выключ", "disable")):
                    m8 = re.search(r"(?:core\s+plugin|базов\w*\s+плагин|ядро\s+плагин|core)\s+([\w\-\.]+)$", seg, flags=re.IGNORECASE)
                    pid = (m8.group(1) if m8 else seg.split()[-1])
                    steps.append({"name": "obsidian_disable_core_plugin", "params": {"id": pid}})
                    continue
            # generic enable/disable: prefer plugin unless heuristic says setting
            if any(k in seg_l for k in ("включ", "enable")):
                m9 = re.search(r"(?:плагин|plugin)\s+([\w\-\.]+)$", seg, flags=re.IGNORECASE)
                if m9:
                    steps.append({"name": "obsidian_enable_plugin", "params": {"id": m9.group(1)}})
                    continue
                # no explicit word — disambiguate
                tail = re.sub(r"^(включи\s+|enable\s+)", "", seg, flags=re.IGNORECASE).strip()
                if _maybe_setting_key(tail):
                    steps.append({"name": "obsidian_set_setting", "params": {"file": "app.json", "path": tail, "value": True}})
                else:
                    steps.append({"name": "obsidian_enable_plugin", "params": {"id": tail}})
                continue
            if any(k in seg_l for k in ("выключ", "disable")):
                m10 = re.search(r"(?:плагин|plugin)\s+([\w\-\.]+)$", seg, flags=re.IGNORECASE)
                if m10:
                    steps.append({"name": "obsidian_disable_plugin", "params": {"id": m10.group(1)}})
                    continue
                tail = re.sub(r"^(выключи\s+|disable\s+)", "", seg, flags=re.IGNORECASE).strip()
                if _maybe_setting_key(tail):
                    steps.append({"name": "obsidian_set_setting", "params": {"file": "app.json", "path": tail, "value": False}})
                else:
                    steps.append({"name": "obsidian_disable_plugin", "params": {"id": tail}})
                continue
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

