import os
import yaml
from typing import Any, Dict
from datetime import datetime

from orchestrator.registry import Registry

from pipelines import steps  # noqa: F401 - ensure step functions are registered via decorators

def _resolve(value, ctx):
    if isinstance(value, str) and value.startswith("@"):
        # simple resolver for @filters.xxx
        path = value[1:].split(".")
        cur = ctx
        for p in path:
            cur = cur.get(p, {})
        return cur if cur != {} else None
    return value


def run_agent(agent_cfg: Dict[str, Any]) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {}
    ctx.update(agent_cfg.get("inputs") or {})
    ctx["filters"] = agent_cfg.get("filters") or {}
    for step in agent_cfg.get("pipeline") or []:
        name = step.get("step")
        if name not in Registry:
            available = ", ".join(sorted(Registry.keys())) or "(empty)"
            raise ValueError(f"Unknown step: {name}. Available steps: {available}")
        params = step.get("with") or {}
        # resolve @-refs
        for k, v in list(params.items()):
            params[k] = _resolve(v, ctx)
        out = Registry[name](params, ctx)
        ctx.update(out or {})
    return ctx


def load_agent_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

