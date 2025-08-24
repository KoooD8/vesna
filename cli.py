#!/usr/bin/env python3
import argparse
from pathlib import Path
from orchestrator.runner import load_agent_config, run_agent


def main():
    ap = argparse.ArgumentParser(description="AI Agents core CLI")
    sub = ap.add_subparsers(dest="cmd")

    sp = sub.add_parser("run-agent", help="Run agent by config path")
    sp.add_argument("config", help="Path to agent YAML")
    sp.add_argument("--id", dest="agent_id", default=None, help="Specific agent id inside list config")

    sp2 = sub.add_parser("run-schedule", help="Run scheduler for agents list")
    sp2.add_argument("--agents", default="configs/agents/core.yaml")
    sp2.add_argument("--timezone", default=None)

    args = ap.parse_args()

    if args.cmd == "run-agent":
        cfg = load_agent_config(args.config)
        if isinstance(cfg, list):
            if not args.agent_id:
                raise SystemExit("--id is required when config contains multiple agents")
            found = next((c for c in cfg if c.get("id") == args.agent_id), None)
            if not found:
                raise SystemExit(f"Agent id not found: {args.agent_id}")
            out = run_agent(found)
        else:
            out = run_agent(cfg)
        print("Done.")
        return 0

    if args.cmd == "run-schedule":
        import subprocess, sys
        from pathlib import Path
        base = Path(__file__).resolve().parent
        cmd = [sys.executable, str(base / "scheduler.py"), "--agents", args.agents]
        if args.timezone:
            cmd += ["--timezone", args.timezone]
        subprocess.run(cmd, check=True)
        return 0

    ap.print_help()

if __name__ == "__main__":
    main()

