import os
from dataclasses import dataclass
from typing import Dict, Any, Optional

import yaml

# Путь к YAML-конфигу (может переопределяться env)
DEFAULT_CONFIG_PATH = os.environ.get(
    "AI_STACK_CONFIG",
    "/Users/onopriychukpavel/Library/Mobile Documents/iCloud~md~obsidian/Documents/Version1/ai_agents_stack.config.yaml",
)

# Дефолтный путь к Obsidian Vault берётся из переменной окружения при каждом вызове,
# чтобы корректно работать в тестах/динамических окружениях.


@dataclass
class AppFolders:
    sources: str = "Sources"
    summaries: str = "Summaries"
    entities: str = "Entities"
    index: str = "Index"
    logs: str = "Logs"


@dataclass
class AppConfig:
    vault_path: str
    folders: AppFolders

    @staticmethod
    def default_vault() -> str:
        return os.environ.get(
            "AI_STACK_DEFAULT_VAULT",
            "/Users/onopriychukpavel/Library/Mobile Documents/iCloud~md~obsidian/Documents/Version1",
        )


def load_config(path: Optional[str] = None) -> AppConfig:
    cfg_path = path or DEFAULT_CONFIG_PATH
    # Defaults
    data: Dict[str, Any] = {
        "vault_path": AppConfig.default_vault(),
        "folders": {
            "sources": "Sources",
            "summaries": "Summaries",
            "entities": "Entities",
            "index": "Index",
            "logs": "Logs",
        },
    }
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            y = yaml.safe_load(f) or {}
        # Merge shallow
        if isinstance(y, dict):
            if "vault_path" in y:
                data["vault_path"] = str(y["vault_path"])
            if isinstance(y.get("folders"), dict):
                data["folders"].update({k: str(v) for k, v in y["folders"].items()})  # type: ignore
    except Exception:
        # Конфиг может отсутствовать — используем значения по умолчанию
        pass
    folders = AppFolders(**data["folders"])  # type: ignore[arg-type]
    return AppConfig(vault_path=data["vault_path"], folders=folders)

