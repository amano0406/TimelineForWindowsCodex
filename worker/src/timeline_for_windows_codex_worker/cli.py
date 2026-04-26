from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .contracts import JobRequest, ThreadSelection
from .discovery import discover_threads
from .fs_utils import now_iso, read_json
from .job_store import (
    collect_jobs_by_state,
    create_job,
    create_job_id,
    iter_run_dirs,
    load_request,
    load_status,
    manifest_path,
    request_path,
    result_path,
)
from .processor import process_job
from .settings import RuntimeDefaults, load_runtime_defaults, load_runtime_paths


def main(argv: list[str] | None = None) -> int:
    runtime = load_runtime_paths()
    defaults = load_runtime_defaults(runtime)
    parser = argparse.ArgumentParser(prog="timeline-for-windows-codex-worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover_parser = subparsers.add_parser("discover")
    _add_source_arguments(discover_parser)
    discover_parser.add_argument("--format", choices=("text", "json"), default="text")

    create_job_parser = subparsers.add_parser("create-job")
    _add_source_arguments(create_job_parser)
    _add_job_arguments(create_job_parser)

    run_parser = subparsers.add_parser("run")
    _add_source_arguments(run_parser)
    _add_job_arguments(run_parser)

    list_jobs_parser = subparsers.add_parser("list-jobs")
    list_jobs_parser.add_argument("--format", choices=("text", "json"), default="text")

    show_job_parser = subparsers.add_parser("show-job")
    show_job_parser.add_argument("job")
    show_job_parser.add_argument("--format", choices=("text", "json"), default="text")

    daemon_parser = subparsers.add_parser("daemon")
    daemon_parser.add_argument("--poll-interval", type=int, default=5)
    daemon_parser.add_argument("--once", action="store_true")

    process_parser = subparsers.add_parser("process-job")
    process_parser.add_argument("job_dir")

    args = parser.parse_args(argv)

    try:
        if args.command == "discover":
            return _handle_discover(args, defaults)

        if args.command == "create-job":
            return _handle_create_job(args, runtime.outputs_root, defaults)

        if args.command == "run":
            return _handle_run(args, runtime.outputs_root, defaults)

        if args.command == "list-jobs":
            return _handle_list_jobs(args, runtime.outputs_root)

        if args.command == "show-job":
            return _handle_show_job(args, runtime.outputs_root)

        if args.command == "process-job":
            process_job(Path(args.job_dir).resolve())
            return 0

        if args.command == "daemon":
            return run_daemon(poll_interval=max(1, args.poll_interval), once=args.once)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.error("Unsupported command.")
    return 2


def _add_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--primary-root")
    parser.add_argument("--backup-root", action="append", default=[])
    parser.add_argument(
        "--include-archived-sources",
        action=argparse.BooleanOptionalAction,
        default=None,
    )


def _add_job_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--thread-id", action="append", default=[])
    parser.add_argument(
        "--include-tool-outputs",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("--redaction-profile", choices=("strict", "loose"))
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    parser.add_argument("--format", choices=("text", "json"), default="text")


def _handle_discover(args: argparse.Namespace, defaults: RuntimeDefaults) -> int:
    discovered = discover_threads(
        _resolve_primary_root(args.primary_root, defaults),
        _resolve_backup_roots(args.backup_root, defaults),
        _resolve_include_archived(args.include_archived_sources, defaults),
    )
    payload = [
        {
            "thread_id": thread.thread_id,
            "preferred_title": thread.preferred_title,
            "observed_thread_names": [item.to_dict() for item in thread.observed_thread_names],
            "source_root_path": thread.source_root_path,
            "source_root_kind": thread.source_root_kind,
            "session_path": thread.session_path,
            "updated_at": thread.updated_at,
            "cwd": thread.cwd,
            "first_user_message_excerpt": thread.first_user_message_excerpt,
        }
        for thread in discovered
    ]
    _print_output(args.format, payload, _format_discovery_text(discovered))
    return 0


def _handle_create_job(
    args: argparse.Namespace,
    outputs_root: Path,
    defaults: RuntimeDefaults,
) -> int:
    request, job_dir = _prepare_job(args, outputs_root, defaults)
    payload = {
        "job_id": request.job_id,
        "run_directory": str(job_dir),
        "thread_count": len(request.selected_threads),
        "selected_thread_ids": [thread.thread_id for thread in request.selected_threads],
    }
    _print_output(
        args.format,
        payload,
        "\n".join(
            [
                f"job_id: {request.job_id}",
                f"run_directory: {job_dir}",
                f"thread_count: {len(request.selected_threads)}",
            ]
        ),
    )
    return 0


def _handle_run(
    args: argparse.Namespace,
    outputs_root: Path,
    defaults: RuntimeDefaults,
) -> int:
    request, job_dir = _prepare_job(args, outputs_root, defaults)
    process_job(job_dir)
    status = load_status(job_dir)
    result = read_json(result_path(job_dir))
    payload = {
        "job_id": request.job_id,
        "run_directory": str(job_dir),
        "state": status.state,
        "archive_path": result.get("archive_path"),
        "thread_count": result.get("thread_count", len(request.selected_threads)),
        "event_count": result.get("event_count", 0),
        "segment_count": result.get("segment_count", 0),
    }
    _print_output(
        args.format,
        payload,
        "\n".join(
            [
                f"job_id: {request.job_id}",
                f"run_directory: {job_dir}",
                f"state: {status.state}",
                f"archive_path: {result.get('archive_path') or ''}",
                f"thread_count: {payload['thread_count']}",
                f"event_count: {payload['event_count']}",
            ]
        ),
    )
    return 0


def _prepare_job(
    args: argparse.Namespace,
    outputs_root: Path,
    defaults: RuntimeDefaults,
) -> tuple[JobRequest, Path]:
    date_from = _normalize_date(args.date_from)
    date_to = _normalize_date(args.date_to)
    if date_from and date_to and date_from > date_to:
        raise ValueError("date_from must be on or before date_to.")

    primary_root = _resolve_primary_root(args.primary_root, defaults)
    backup_roots = _resolve_backup_roots(args.backup_root, defaults)
    include_archived_sources = _resolve_include_archived(args.include_archived_sources, defaults)
    include_tool_outputs = _resolve_include_tool_outputs(args.include_tool_outputs, defaults)
    redaction_profile = _resolve_redaction_profile(args.redaction_profile, defaults)

    discovered = discover_threads(primary_root, backup_roots, include_archived_sources)
    selected_threads = _select_threads(discovered, args.thread_id)
    if not selected_threads:
        raise ValueError("No threads matched the current selection.")

    job_id = create_job_id(outputs_root)
    request = JobRequest(
        job_id=job_id,
        created_at=now_iso(),
        primary_codex_home_path=primary_root,
        backup_codex_home_paths=backup_roots,
        include_archived_sources=include_archived_sources,
        include_tool_outputs=include_tool_outputs,
        redaction_profile=redaction_profile,
        date_from=date_from,
        date_to=date_to,
        selected_threads=selected_threads,
    )
    job_dir = outputs_root / job_id
    create_job(job_dir, request)
    return request, job_dir


def _handle_list_jobs(args: argparse.Namespace, outputs_root: Path) -> int:
    rows = []
    for job_dir in reversed(iter_run_dirs(outputs_root)):
        request = load_request(job_dir)
        status = load_status(job_dir)
        result = read_json(result_path(job_dir)) if result_path(job_dir).exists() else {}
        rows.append(
            {
                "job_id": request.job_id,
                "state": status.state,
                "current_stage": status.current_stage,
                "created_at": request.created_at,
                "updated_at": status.updated_at,
                "thread_count": len(request.selected_threads),
                "threads_done": status.threads_done,
                "archive_path": result.get("archive_path"),
            }
        )

    _print_output(args.format, rows, _format_list_jobs_text(rows))
    return 0


def _handle_show_job(args: argparse.Namespace, outputs_root: Path) -> int:
    job_dir = _resolve_job_dir(args.job, outputs_root)
    if not request_path(job_dir).exists():
        raise FileNotFoundError(f"Job was not found: {args.job}")

    request = load_request(job_dir)
    status = load_status(job_dir)
    result = read_json(result_path(job_dir)) if result_path(job_dir).exists() else {}
    manifest = read_json(manifest_path(job_dir)) if manifest_path(job_dir).exists() else {}
    payload = {
        "job_id": request.job_id,
        "run_directory": str(job_dir),
        "status": status.to_dict(),
        "result": result,
        "manifest": manifest,
        "selected_threads": [thread.to_dict() for thread in request.selected_threads],
    }
    _print_output(args.format, payload, _format_show_job_text(job_dir, request, status, result))
    return 0


def _resolve_primary_root(value: str | None, defaults: RuntimeDefaults) -> str:
    return (value or defaults.default_primary_codex_home_path).strip()


def _resolve_backup_roots(values: list[str], defaults: RuntimeDefaults) -> list[str]:
    if values:
        return [item.strip() for item in values if item.strip()]
    return [item.strip() for item in defaults.default_backup_codex_home_paths or [] if item.strip()]


def _resolve_include_archived(value: bool | None, defaults: RuntimeDefaults) -> bool:
    return defaults.default_include_archived_sources if value is None else bool(value)


def _resolve_include_tool_outputs(value: bool | None, defaults: RuntimeDefaults) -> bool:
    return defaults.default_include_tool_outputs if value is None else bool(value)


def _resolve_redaction_profile(value: str | None, defaults: RuntimeDefaults) -> str:
    profile = (value or defaults.default_redaction_profile or "strict").strip().lower()
    return "loose" if profile == "loose" else "strict"


def _normalize_date(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _select_threads(
    discovered: list[ThreadSelection],
    selected_ids: list[str],
) -> list[ThreadSelection]:
    normalized_ids = [item.strip() for item in selected_ids if item and item.strip()]
    if not normalized_ids:
        return discovered

    selected_map = {thread.thread_id.casefold(): thread for thread in discovered}
    missing = [item for item in normalized_ids if item.casefold() not in selected_map]
    if missing:
        raise ValueError(f"Unknown thread ids: {', '.join(missing)}")

    rows: list[ThreadSelection] = []
    seen: set[str] = set()
    for thread_id in normalized_ids:
        key = thread_id.casefold()
        if key in seen:
            continue
        seen.add(key)
        rows.append(selected_map[key])
    return rows


def _resolve_job_dir(job: str, outputs_root: Path) -> Path:
    candidate = Path(job)
    if candidate.is_absolute():
        return candidate.resolve()
    outputs_candidate = (outputs_root / job).resolve()
    if outputs_candidate.exists():
        return outputs_candidate
    return candidate.resolve()


def _print_output(format_name: str, payload: object, text_output: str) -> None:
    if format_name == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(text_output)


def _format_discovery_text(discovered: list[ThreadSelection]) -> str:
    if not discovered:
        return "No threads discovered."
    return "\n".join(
        " | ".join(
            [
                thread.thread_id,
                thread.preferred_title or thread.thread_id,
                thread.updated_at or "-",
                thread.session_path or "-",
            ]
        )
        for thread in discovered
    )


def _format_list_jobs_text(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "No jobs found."
    return "\n".join(
        " | ".join(
            [
                str(row.get("job_id") or ""),
                str(row.get("state") or ""),
                f"{row.get('threads_done', 0)}/{row.get('thread_count', 0)} threads",
                str(row.get("updated_at") or "-"),
            ]
        )
        for row in rows
    )


def _format_show_job_text(
    job_dir: Path,
    request: JobRequest,
    status,
    result: dict[str, object],
) -> str:
    lines = [
        f"job_id: {request.job_id}",
        f"run_directory: {job_dir}",
        f"state: {status.state}",
        f"current_stage: {status.current_stage}",
        f"archive_path: {result.get('archive_path') or ''}",
        f"thread_count: {len(request.selected_threads)}",
        "selected_threads:",
    ]
    lines.extend(
        f"- {thread.thread_id} | {thread.preferred_title or thread.thread_id}"
        for thread in request.selected_threads
    )
    return "\n".join(lines)


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
