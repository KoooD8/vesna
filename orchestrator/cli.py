#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Any, Dict

from orchestrator.runner import load_agent_config, run_agent


def build_parser():
    p = argparse.ArgumentParser(description="Orchestrator CLI: run agent pipelines from YAML")
    p.add_argument("--config", required=True, help="Path to agent YAML config")
    p.add_argument("--print", action="store_true", help="Print resulting context as JSON")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"❌ Config not found: {cfg_path}")
        return 1
    agent_cfg: Dict[str, Any] = load_agent_config(str(cfg_path))
    try:
        ctx = run_agent(agent_cfg)
    except Exception as e:
        print(f"❌ Pipeline error: {e}")
        return 2
    if args.__dict__.get("print"):
        print(json.dumps(ctx, ensure_ascii=False, indent=2))
    else:
        print("✅ Pipeline executed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

