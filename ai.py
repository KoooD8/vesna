#!/usr/bin/env python3
"""
Unified CLI for AI Agents Stack

Commands:
  - health
  - steps list
  - search web|news
  - index results
  - summarize file|topk
  - agent run
  - schedule start
  - docker up|up-all|down|logs|health
  - config show|init

This is a thin wrapper around existing scripts (chat.py, cli.py, orchestrator, docker compose).
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import subprocess
from pathlib import Path
from typing import List, Optional, Any, Dict
import glob as _glob

def _detect_repo_root() -> Path:
    # Prefer current working directory if it looks like the project root
    cwd = Path.cwd()
    if (cwd / "chat.py").exists() and (cwd / "README.md").exists():
        return cwd
    return Path(__file__).resolve().parent

REPO_ROOT = _detect_repo_root()

# Local imports for config operations
try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # config init will fail gracefully if yaml is missing

try:
    from config import load_config, AppConfig, DEFAULT_CONFIG_PATH  # type: ignore
except Exception:
    # allow running docker subcommands etc. even if local imports fail
    load_config = None  # type: ignore
    AppConfig = None  # type: ignore
    DEFAULT_CONFIG_PATH = os.environ.get(
        "AI_STACK_CONFIG",
        "/Users/onopriychukpavel/Library/Mobile Documents/iCloud~md~obsidian/Documents/Version1/ai_agents_stack.config.yaml",
    )


def _run(cmd: List[str]) -> int:
    try:
        r = subprocess.run(cmd, check=False)
        return r.returncode
    except FileNotFoundError as e:
        print(f"Command not found: {cmd[0]} ({e})")
        return 127


def _append_filters(cmd: List[str], ns: argparse.Namespace) -> None:
    if getattr(ns, "filter_source", None):
        cmd += ["--filter-source", ns.filter_source]
    if getattr(ns, "filter_domain", None):
        cmd += ["--filter-domain", ns.filter_domain]
    if getattr(ns, "filter_date", None):
        cmd += ["--filter-date", ns.filter_date]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AI unified CLI")
    p.add_argument("-v", "--verbose", action="store_true")

    sub = p.add_subparsers(dest="cmd")

    # health
    sp_h = sub.add_parser("health", help="Run local health-check")

    # agents management
    sp_agents = sub.add_parser("agents", help="Manage agents (list, enable/disable, new, validate)")
    sp_agents_sub = sp_agents.add_subparsers(dest="agents_cmd")

    sp_al = sp_agents_sub.add_parser("list", help="List agents from YAML file or glob")
    sp_group = sp_al.add_mutually_exclusive_group()
    sp_group.add_argument("--file", help="Path to YAML with agents list (default: configs/agents/core.yaml)")
    sp_group.add_argument("--glob", help="Glob pattern to multiple YAML files (e.g., 'configs/agents/*.yaml')")
    sp_al.add_argument("--next", action="store_true", help="Show next run time (requires croniter)")
    sp_al.add_argument("--timezone", default=None, help="Timezone for next run (e.g., Europe/Kyiv)")

    sp_ae = sp_agents_sub.add_parser("enable", help="Enable agent by id in file")
    sp_ae.add_argument("--id", required=True)
    sp_ae.add_argument("--file", required=True)

    sp_ad = sp_agents_sub.add_parser("disable", help="Disable agent by id in file")
    sp_ad.add_argument("--id", required=True)
    sp_ad.add_argument("--file", required=True)

    sp_an = sp_agents_sub.add_parser("new", help="Create a new agent YAML skeleton")
    sp_an.add_argument("--id", required=True)
    sp_an.add_argument("--file", required=True, help="Target YAML file to create (or overwrite if exists)")
    sp_an.add_argument("--schedule", default=None, help="Cron schedule (e.g., '0 9 * * *')")
    sp_an.add_argument("--description", default=None)

    sp_av = sp_agents_sub.add_parser("validate", help="Validate that steps used in YAML exist in Registry")
    sp_av.add_argument("--file", required=True)

    # steps list
    sp_steps = sub.add_parser("steps", help="Steps related commands")
    sp_steps_sub = sp_steps.add_subparsers(dest="steps_cmd")
    sp_steps_list = sp_steps_sub.add_parser("list", help="List registered steps")

    # search group
    sp_search = sub.add_parser("search", help="Search commands")
    sp_search_sub = sp_search.add_subparsers(dest="search_cmd")

    sp_sw = sp_search_sub.add_parser("web", help="Web search via chat.py")
    sp_sw.add_argument("query", nargs="+", help="query text")
    sp_sw.add_argument("--save", action="store_true")
    for sp in [sp_sw]:
        sp.add_argument("--filter-source", choices=["DuckDuckGo", "Reddit", "Google News", "test", "obsidian_md"])
        sp.add_argument("--filter-domain")
        sp.add_argument("--filter-date")

    sp_sn = sp_search_sub.add_parser("news", help="News search (Google News)")
    sp_sn.add_argument("query", nargs="+", help="query text")
    sp_sn.add_argument("--save", action="store_true")
    for sp in [sp_sn]:
        sp.add_argument("--filter-source", choices=["DuckDuckGo", "Reddit", "Google News", "test", "obsidian_md"])
        sp.add_argument("--filter-domain")
        sp.add_argument("--filter-date")

    # index results
    sp_index = sub.add_parser("index", help="Index operations")
    sp_index_sub = sp_index.add_subparsers(dest="index_cmd")
    sp_ir = sp_index_sub.add_parser("results", help="Save JSON results to Obsidian Index")
    sp_ir.add_argument("json_file")
    sp_ir.add_argument("--name")

    # summarize group
    sp_sum = sub.add_parser("summarize", help="Summarization")
    sp_sum_sub = sp_sum.add_subparsers(dest="sum_cmd")

    sp_sf = sp_sum_sub.add_parser("file", help="Summarize from results file")
    sp_sf.add_argument("json_file")
    sp_sf.add_argument("--title")

    sp_st = sp_sum_sub.add_parser("topk", help="Vector Top-K search and save")
    sp_st.add_argument("query", nargs="+")
    sp_st.add_argument("--k", type=int, default=10)
    sp_st.add_argument("--title")
    for sp in [sp_st]:
        sp.add_argument("--filter-source", choices=["DuckDuckGo", "Reddit", "Google News", "test", "obsidian_md"])
        sp.add_argument("--filter-domain")
        sp.add_argument("--filter-date")

    # agent
    sp_agent = sub.add_parser("agent", help="Agent operations")
    sp_agent_sub = sp_agent.add_subparsers(dest="agent_cmd")
    sp_ar = sp_agent_sub.add_parser("run", help="Run agent by YAML config")
    sp_ar.add_argument("--config", required=True)
    sp_ar.add_argument("--id")

    # schedule
    sp_sched = sub.add_parser("schedule", help="Scheduler operations")
    sp_sched_sub = sp_sched.add_subparsers(dest="sched_cmd")
    sp_ss = sp_sched_sub.add_parser("start", help="Start scheduler for agents list")
    sp_ss.add_argument("--agents", default="configs/agents/core.yaml")
    sp_ss.add_argument("--timezone")

    # docker
    sp_d = sub.add_parser("docker", help="Docker compose helpers")
    sp_d_sub = sp_d.add_subparsers(dest="docker_cmd")
    sp_du = sp_d_sub.add_parser("up", help="Start qdrant only")
    sp_dua = sp_d_sub.add_parser("up-all", help="Start full stack app+qdrant")
    sp_dd = sp_d_sub.add_parser("down", help="Stop all containers")
    sp_dl = sp_d_sub.add_parser("logs", help="Follow app logs")
    sp_dh = sp_d_sub.add_parser("health", help="Run health inside app container")

    # config
    sp_cfg = sub.add_parser("config", help="Configuration")
    sp_cfg_sub = sp_cfg.add_subparsers(dest="cfg_cmd")
    sp_cfg_show = sp_cfg_sub.add_parser("show", help="Show effective config")
    sp_cfg_init = sp_cfg_sub.add_parser("init", help="Initialize config YAML")
    sp_cfg_init.add_argument("--vault", required=True, help="Path to Obsidian Vault")
    sp_cfg_init.add_argument("--file", default=None, help="Path to config YAML (defaults to AI_STACK_CONFIG or project default)")

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "health":
        cmd = [sys.executable, str(REPO_ROOT / "chat.py"), "--health"]
        if args.verbose:
            cmd.insert(2, "-v")
        return _run(cmd)

    # agents management commands
    if args.cmd == "agents":
        if yaml is None:
            print("PyYAML is required for agents management. Please install it.")
            return 1
        def _abs_path(p: str) -> Path:
            pp = Path(p)
            return pp if pp.is_absolute() else (REPO_ROOT / pp)
        def _load_yaml_list(path: str) -> List[Dict[str, Any]]:
            pth = _abs_path(path)
            with open(pth, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or []
            if isinstance(data, dict):
                data = [data]
            return data
        def _write_yaml_list(path: str, items: List[Dict[str, Any]]) -> None:
            p = _abs_path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                yaml.safe_dump(items if len(items) != 1 else items[0], f, allow_unicode=True, sort_keys=False)
        if args.agents_cmd == "list":
            files: List[str] = []
            if args.file:
                files = [args.file]
            elif args.glob:
                files = sorted(_glob.glob(args.glob))
            else:
                default = str(REPO_ROOT / "configs/agents/core.yaml")
                if Path(default).exists():
                    files = [default]
                else:
                    print("No --file provided and default configs/agents/core.yaml not found.")
                    return 1
            # optional next run computation
            tz = None
            tzname = getattr(args, "timezone", None)
            if tzname:
                try:
                    import pytz as _pytz
                    tz = _pytz.timezone(tzname)
                except Exception:
                    tz = None
            try:
                from croniter import croniter  # type: ignore
                has_cron = True
            except Exception:
                has_cron = False
            count = 0
            for fp in files:
                items = _load_yaml_list(fp)
                for it in items:
                    count += 1
                    aid = it.get("id") or "<no-id>"
                    sched = it.get("schedule") or ""
                    enabled = it.get("enabled")
                    enabled_s = "true" if enabled is not False else "false"
                    line = f"{aid} | enabled={enabled_s}"
                    if sched:
                        line += f" | cron='{sched}'"
                        if args.__dict__.get("next") and has_cron:
                            try:
                                from datetime import datetime as _dt
                                base = _dt.now(tz) if tz else _dt.now()
                                import croniter as _cr
                                itrn = _cr.croniter(sched, base)
                                nx = itrn.get_next(_dt)
                                line += f" | next={nx.isoformat()}"
                            except Exception:
                                line += " | next=?"
                        elif args.__dict__.get("next") and not has_cron:
                            line += " | next=(install croniter)"
                    desc = it.get("description")
                    if desc:
                        line += f" | {desc}"
                    print(line)
            if count == 0:
                print("No agents found.")
            return 0
        if args.agents_cmd in ("enable", "disable"):
            items = _load_yaml_list(args.file)
            target = next((x for x in items if x.get("id") == args.id), None)
            if not target:
                print(f"Agent id not found: {args.id}")
                return 1
            target["enabled"] = True if args.agents_cmd == "enable" else False
            _write_yaml_list(args.file, items)
            print(f"Updated {args.id}: enabled={target['enabled']}")
            return 0
        if args.agents_cmd == "new":
            if Path(args.file).exists():
                print(f"Overwriting existing file: {args.file}")
            skel: Dict[str, Any] = {
                "id": args.id,
                "enabled": True,
                "retries": 2,
                "backoff": 0.5,
                "pipeline": [
                    {"step": "search_web", "with": {"query": "replace me"}},
                    {"step": "save_sources_markdown", "with": {"title": "Agent Sources: replace me"}},
                ],
            }
            if args.schedule:
                skel["schedule"] = args.schedule
            if args.description:
                skel["description"] = args.description
            _write_yaml_list(args.file, [skel])
            print(f"Wrote new agent skeleton to {args.file}")
            return 0
        if args.agents_cmd == "validate":
            # ensure steps exist in Registry without executing
            try:
                from orchestrator.registry import Registry
            except Exception as e:
                print(f"Cannot import Registry: {e}")
                return 1
            try:
                items = _load_yaml_list(args.file)
            except Exception as e:
                print(f"Failed to load YAML: {e}")
                return 1
            ok = True
            for it in items:
                aid = it.get("id") or "<no-id>"
                for step in it.get("pipeline") or []:
                    name = step.get("step")
                    if name not in Registry:
                        print(f"{aid}: Unknown step: {name}")
                        ok = False
            if ok:
                print("OK")
                return 0
            return 2

    if args.cmd == "steps" and args.steps_cmd == "list":
        return _run([sys.executable, str(REPO_ROOT / "chat.py"), "list-steps"]) 

    if args.cmd == "search":
        if args.search_cmd == "web":
            cmd = [sys.executable, str(REPO_ROOT / "chat.py")]
            if args.verbose:
                cmd.append("-v")
            cmd += ["search:web", *args.query]
            if args.save:
                cmd.append("--save")
            _append_filters(cmd, args)
            return _run(cmd)
        if args.search_cmd == "news":
            cmd = [sys.executable, str(REPO_ROOT / "chat.py")]
            if args.verbose:
                cmd.append("-v")
            cmd += ["search:news", *args.query]
            if args.save:
                cmd.append("--save")
            _append_filters(cmd, args)
            return _run(cmd)

    if args.cmd == "index" and args.index_cmd == "results":
        cmd = [sys.executable, str(REPO_ROOT / "chat.py"), "index:results", args.json_file]
        if args.name:
            cmd += ["--name", args.name]
        return _run(cmd)

    if args.cmd == "summarize":
        if args.sum_cmd == "file":
            cmd = [sys.executable, str(REPO_ROOT / "chat.py"), "summarize:file", args.json_file]
            if args.title:
                cmd += ["--title", args.title]
            return _run(cmd)
        if args.sum_cmd == "topk":
            cmd = [sys.executable, str(REPO_ROOT / "chat.py"), "summarize:topk", *args.query]
            cmd += ["--k", str(getattr(args, "k", 10))]
            if args.title:
                cmd += ["--title", args.title]
            _append_filters(cmd, args)
            return _run(cmd)

    if args.cmd == "agent" and args.agent_cmd == "run":
        cmd = [sys.executable, str(REPO_ROOT / "cli.py"), "run-agent", args.config]
        if args.id:
            cmd += ["--id", args.id]
        return _run(cmd)

    if args.cmd == "schedule" and args.sched_cmd == "start":
        cmd = [sys.executable, str(REPO_ROOT / "cli.py"), "run-schedule", "--agents", args.agents]
        if args.timezone:
            cmd += ["--timezone", args.timezone]
        return _run(cmd)

    if args.cmd == "docker":
        if args.docker_cmd == "up":
            return _run(["docker", "compose", "-f", str(REPO_ROOT / "docker-compose.yml"), "--profile", "qdrant", "up", "-d"])
        if args.docker_cmd == "up-all":
            return _run(["docker", "compose", "-f", str(REPO_ROOT / "docker-compose.yml"), "--profile", "all", "up", "-d", "--build"])
        if args.docker_cmd == "down":
            return _run(["docker", "compose", "-f", str(REPO_ROOT / "docker-compose.yml"), "down"])
        if args.docker_cmd == "logs":
            return _run(["docker", "compose", "-f", str(REPO_ROOT / "docker-compose.yml"), "logs", "-f", "app"])
        if args.docker_cmd == "health":
            return _run(["docker", "compose", "-f", str(REPO_ROOT / "docker-compose.yml"), "run", "--rm", "app", "python3", "chat.py", "--health"])

    if args.cmd == "config":
        cfg_path = os.environ.get("AI_STACK_CONFIG", DEFAULT_CONFIG_PATH)
        if args.cfg_cmd == "show":
            if load_config is None:
                print("Config module not available.")
                return 1
            cfg = load_config()
            data = {
                "config_path": cfg_path,
                "vault_path": getattr(cfg, "vault_path", None),
                "folders": getattr(cfg, "folders", None).__dict__ if getattr(cfg, "folders", None) else None,
            }
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        if args.cfg_cmd == "init":
            if yaml is None:
                print("PyYAML is required for config init. Please install it.")
                return 1
            target = args.file or cfg_path
            target_p = Path(target)
            target_p.parent.mkdir(parents=True, exist_ok=True)
            # derive default folders from current defaults
            folders = {
                "sources": "Sources",
                "summaries": "Summaries",
                "entities": "Entities",
                "index": "Index",
                "logs": "Logs",
            }
            try:
                if load_config is not None:
                    # get default folder names if customized in code
                    c = load_config()
                    folders = {
                        "sources": c.folders.sources,
                        "summaries": c.folders.summaries,
                        "entities": c.folders.entities,
                        "index": c.folders.index,
                        "logs": c.folders.logs,
                    }
            except Exception:
                pass
            content = {"vault_path": str(Path(args.vault).expanduser()), "folders": folders}
            with open(target_p, "w", encoding="utf-8") as f:
                yaml.safe_dump(content, f, allow_unicode=True, sort_keys=False)
            print(f"Wrote config: {target_p}")
            return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

