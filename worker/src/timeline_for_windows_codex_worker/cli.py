from __future__ import annotations

import argparse
import time
from pathlib import Path

from .job_store import collect_jobs_by_state
from .processor import process_job
from .settings import load_runtime_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="timeline-for-windows-codex-worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    daemon_parser = subparsers.add_parser("daemon")
    daemon_parser.add_argument("--poll-interval", type=int, default=5)
    daemon_parser.add_argument("--once", action="store_true")

    process_parser = subparsers.add_parser("process-job")
    process_parser.add_argument("job_dir")

    args = parser.parse_args(argv)

    if args.command == "process-job":
        process_job(Path(args.job_dir).resolve())
        return 0

    if args.command == "daemon":
        return run_daemon(poll_interval=max(1, args.poll_interval), once=args.once)

    parser.error("Unsupported command.")
    return 2


def run_daemon(*, poll_interval: int, once: bool) -> int:
    runtime = load_runtime_paths()

    while True:
        running_jobs = collect_jobs_by_state(runtime.outputs_root, "running")
        if running_jobs:
            if once:
                return 0
            time.sleep(poll_interval)
            continue

        pending_jobs = collect_jobs_by_state(runtime.outputs_root, "pending")
        if pending_jobs:
            process_job(pending_jobs[0])
            if once:
                return 0
            continue

        if once:
            return 0
        time.sleep(poll_interval)
