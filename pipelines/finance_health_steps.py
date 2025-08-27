from __future__ import annotations
import os
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from orchestrator.registry import register
from config import load_config
from agents.obsidian.manager import ObsidianManager

# Finance and Health pipeline steps
# These steps write to Obsidian vault in structured folders:
# - Notes/Finance/ (CSV imports, ledger records, monthly summaries)
# - Notes/Health/ (daily logs, metrics)

@dataclass
class FinanceConfig:
    base_dir: str = "Notes/Finance"
    ledger_file: str = "ledger.csv"  # cumulative ledger inside base_dir


def _vault_root() -> Path:
    from config import load_config
    cfg = load_config()
    return Path(cfg.vault_path)


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _csv_read(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def _csv_write(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


@register("finance_import_csv")
def step_finance_import_csv(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Import a bank CSV into ledger (append), and create a markdown summary note.
    Params:
      csv: path to a CSV file (absolute or relative to CWD)
      delimiter: optional CSV delimiter (default ",")
      encoding: default utf-8
      map: optional mapping dict {date, amount, currency, description, category}
    Output:
      { imported: N, ledger_path, note_path }
    """
    src = params.get("csv")
    if not src:
        raise ValueError("finance_import_csv: 'csv' is required")
    delim = params.get("delimiter", ",")
    enc = params.get("encoding", "utf-8")
    mapping = params.get("map") or {}

    # Read source CSV
    abs_src = Path(src).expanduser()
    if not abs_src.exists():
        raise FileNotFoundError(abs_src)
    with open(abs_src, "r", encoding=enc, newline="") as f:
        reader = csv.DictReader(f, delimiter=delim)
        src_rows = [dict(row) for row in reader]

    # Normalize columns
    def norm(row: Dict[str, Any]) -> Dict[str, Any]:
        def pick(*keys: str) -> str:
            for k in keys:
                if k in row and str(row[k]).strip() != "":
                    return str(row[k]).strip()
            return ""
        date = row.get(mapping.get("date")) if mapping.get("date") else pick("date", "Date", "Дата")
        desc = row.get(mapping.get("description")) if mapping.get("description") else pick("description", "Description", "Назначение")
        amount = row.get(mapping.get("amount")) if mapping.get("amount") else pick("amount", "Amount", "Сумма", "Сума")
        currency = row.get(mapping.get("currency")) if mapping.get("currency") else pick("currency", "Currency", "Валюта")
        category = row.get(mapping.get("category")) if mapping.get("category") else pick("category", "Категория")
        # Basic cleanup
        try:
            amt = float(str(amount).replace(" ", "").replace(",", ".")) if amount else 0.0
        except Exception:
            amt = 0.0
        cur = currency or "UAH"
        dt = date or datetime.now().strftime("%Y-%m-%d")
        cat = category or "uncategorized"
        return {
            "date": dt[:10],
            "amount": amt,
            "currency": cur,
            "description": desc or "",
            "category": cat,
            "source_file": abs_src.name,
        }

    norm_rows = [norm(r) for r in src_rows]

    # Append into ledger CSV under vault
    base = _vault_root()
    cfg = FinanceConfig()
    ledger_path = base / cfg.base_dir / cfg.ledger_file
    existing = _csv_read(ledger_path)
    merged = existing + norm_rows
    # Ensure consistent fieldnames
    fields = ["date", "amount", "currency", "description", "category", "source_file"]
    _csv_write(ledger_path, merged, fields)

    # Write a short note with stats
    total = sum(r.get("amount", 0.0) for r in norm_rows)
    cnt = len(norm_rows)
    md_lines = [
        f"# Finance Import: {abs_src.name}",
        "",
        f"- Imported rows: {cnt}",
        f"- Sum: {total:.2f}",
        f"- Ledger: {ledger_path.relative_to(base)}",
    ]
    name = f"import-{abs_src.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    mgr = ObsidianManager(str(base))
    note_rel = f"Notes/Finance/{name}.md"
    mgr.write_note(note_rel, "\n".join(md_lines))

    return {"imported": cnt, "ledger_path": str(ledger_path), "note_path": str(base / note_rel)}


@register("finance_add_record")
def step_finance_add_record(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Add a single finance record into ledger CSV and append to a daily finance note.
    Params:
      type: 'expense'|'income' (default 'expense')
      amount: float
      currency: str (default UAH)
      category: str
      note: str (optional description)
    """
    base = _vault_root()
    cfg = FinanceConfig()
    rec_type = (params.get("type") or "expense").lower()
    amt = float(params.get("amount") or 0.0)
    cur = params.get("currency") or "UAH"
    cat = params.get("category") or ("income" if rec_type == "income" else "uncategorized")
    desc = params.get("note") or ""
    row = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "amount": amt if rec_type == "income" else -abs(amt),
        "currency": cur,
        "description": desc,
        "category": cat,
        "source_file": "manual",
    }
    ledger_path = base / cfg.base_dir / cfg.ledger_file
    existing = _csv_read(ledger_path)
    existing.append(row)
    _csv_write(ledger_path, existing, ["date", "amount", "currency", "description", "category", "source_file"])

    # Append to daily finance note
    mgr = ObsidianManager(str(base))
    date = datetime.now().strftime("%Y-%m-%d")
    rel = f"Notes/Finance/daily-{date}.md"
    sign = "+" if row["amount"] >= 0 else "-"
    line = f"- {date} {sign}{abs(row['amount']):.2f} {row['currency']} [{row['category']}] {row['description']}"
    mgr.append_note(rel, line, header="Движения")
    return {"ledger_path": str(ledger_path), "finance_note": str(base / rel)}


@register("health_log")
def step_health_log(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Append health metrics to a daily health note.
    Params can include: weight_kg, pulse_bpm, bp_sys, bp_dia, sleep_min, steps, note
    """
    base = _vault_root()
    mgr = ObsidianManager(str(base))
    date = datetime.now().strftime("%Y-%m-%d")
    rel = f"Notes/Health/daily-{date}.md"
    metrics = []
    if "weight_kg" in params:
        metrics.append(f"вес: {float(params['weight_kg']):.1f} кг")
    if "pulse_bpm" in params:
        metrics.append(f"пульс: {int(params['pulse_bpm'])} bpm")
    if "bp_sys" in params and "bp_dia" in params:
        metrics.append(f"давление: {int(params['bp_sys'])}/{int(params['bp_dia'])}")
    if "sleep_min" in params:
        h = int(params["sleep_min"]) // 60
        m = int(params["sleep_min"]) % 60
        metrics.append(f"сон: {h}:{m:02d}")
    if "steps" in params:
        metrics.append(f"шаги: {int(params['steps'])}")
    note = params.get("note") or ""
    if note:
        metrics.append(f"заметка: {note}")
    line = "- " + "; ".join(metrics)
    mgr.append_note(rel, line, header="Метрики")
    return {"health_note": str(base / rel)}

