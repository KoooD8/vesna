#!/usr/bin/env python3
"""
Simple APScheduler-based scheduler that reads agents list (YAML) and runs those with cron schedules.
Usage:
  python scheduler.py --agents configs/agents/core.yaml
"""
import argparse
import time
import os
import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from datetime import datetime
import pytz

from orchestrator.runner import run_agent
import pipelines.steps  # ensure steps are registered


def load_agents(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    if isinstance(data, dict):
        data = [data]
    return data


def main():
    ap = argparse.ArgumentParser(description="AI Agents Scheduler")
    ap.add_argument("--agents", default="configs/agents/core.yaml", help="Path to agents YAML (list)")
    ap.add_argument("--timezone", default=None, help="Timezone, e.g., Europe/Moscow; overrides AI_STACK_TZ env")
    args = ap.parse_args()

    agents = load_agents(args.agents)

    tzname = args.timezone or os.environ.get("AI_STACK_TZ")
    tz = pytz.timezone(tzname) if tzname else None

    jobstores = {"default": MemoryJobStore()}
    executors = {"default": ThreadPoolExecutor(max_workers=4)}
    job_defaults = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}
    sched = BackgroundScheduler(jobstores=jobstores, executors=executors, job_defaults=job_defaults, timezone=tz)

    for ag in agents:
        # skip disabled agents
        if ag.get("enabled") is False:
            print(f"Skip {ag.get('id')} (disabled)")
            continue
        cron = ag.get("schedule")
        if isinstance(cron, dict):
            cron = cron.get("cron")
        if not cron or not isinstance(cron, str):
            continue
        fields = cron.split()
        if len(fields) != 5:
            print(f"Skip {ag.get('id')} invalid cron: {cron}")
            continue
        minute, hour, day, month, dow = fields
        def _job(cfg=ag):
            attempts = 0
            max_attempts = int(cfg.get("retries", 2)) + 1
            backoff = float(cfg.get("backoff", 0.5))
            while attempts < max_attempts:
                try:
                    print(f"[Scheduler] Run {cfg.get('id')} (attempt {attempts+1}/{max_attempts}) @ {datetime.now(tz).isoformat() if tz else datetime.now().isoformat()}")
                    run_agent(cfg)
                    return
                except Exception as e:
                    attempts += 1
                    print(f"[Scheduler] Error {cfg.get('id')}: {e}")
                    if attempts < max_attempts:
                        import time as _t
                        _t.sleep(backoff * (2 ** (attempts-1)))
        sched.add_job(_job, 'cron', minute=minute, hour=hour, day=day, month=month, day_of_week=dow, id=ag.get('id'))
        print(f"Scheduled {ag.get('id')} @ {cron} tz={tzname or 'system'}")

    sched.start()
    print("Scheduler started. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sched.shutdown()

if __name__ == "__main__":
    main()

