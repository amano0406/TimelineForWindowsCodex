from __future__ import annotations

import argparse
import json
import os
import shutil
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
from .settings import UserSettings, load_user_settings, save_user_settings, user_settings_path

DOCKER_RUNTIME_ENV = "TIMELINE_FOR_WINDOWS_CODEX_RUNTIME"
ALLOW_HOST_RUN_ENV = "TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN"


def main(argv: list[str] | None = None) -> int:
    if not _is_docker_runtime() and not _truthy_env(ALLOW_HOST_RUN_ENV):
        print(
            "\n".join(
                [
                    "Host direct execution is disabled for normal operation.",
                    "Use Docker Compose instead, for example: docker compose run --rm worker settings show",
                    f"For automated tests only, set {ALLOW_HOST_RUN_ENV}=1.",
                ]
            ),
            file=sys.stderr,
        )
        return 1

    runtime = load_runtime_paths()
    defaults = load_runtime_defaults(runtime)
    user_settings = load_user_settings(runtime)
    outputs_root = _effective_outputs_root(runtime.outputs_root, user_settings)
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

    refresh_parser = subparsers.add_parser("refresh")
    _add_job_arguments(refresh_parser)
    refresh_parser.add_argument(
        "--include-archived-sources",
        action=argparse.BooleanOptionalAction,
        default=None,
    )

    current_parser = subparsers.add_parser("current")
    current_parser.add_argument("--format", choices=("text", "json"), default="text")

    export_current_parser = subparsers.add_parser("export-current")
    export_current_parser.add_argument("--to", required=True)
    export_current_parser.add_argument("--overwrite", action="store_true")
    export_current_parser.add_argument("--format", choices=("text", "json"), default="text")

    handoff_parser = subparsers.add_parser("handoff")
    handoff_parser.add_argument("--to", required=True)
    handoff_parser.add_argument("--overwrite", action="store_true")
    _add_job_arguments(handoff_parser)
    handoff_parser.add_argument(
        "--include-archived-sources",
        action=argparse.BooleanOptionalAction,
        default=None,
    )

    settings_parser = subparsers.add_parser("settings")
    settings_subparsers = settings_parser.add_subparsers(dest="settings_command", required=True)
    settings_init_parser = settings_subparsers.add_parser("init")
    settings_init_parser.add_argument("--source-root", action="append", default=[])
    settings_init_parser.add_argument("--output-root")
    settings_init_parser.add_argument("--force", action="store_true")
    settings_init_parser.add_argument("--format", choices=("text", "json"), default="text")
    settings_show_parser = settings_subparsers.add_parser("show")
    settings_show_parser.add_argument("--format", choices=("text", "json"), default="text")
    settings_validate_parser = settings_subparsers.add_parser("validate")
    settings_validate_parser.add_argument("--format", choices=("text", "json"), default="text")
    settings_add_source_parser = settings_subparsers.add_parser("add-source")
    settings_add_source_parser.add_argument("path")
    settings_add_source_parser.add_argument("--format", choices=("text", "json"), default="text")
    settings_remove_source_parser = settings_subparsers.add_parser("remove-source")
    settings_remove_source_parser.add_argument("path")
    settings_remove_source_parser.add_argument("--format", choices=("text", "json"), default="text")
    settings_clear_sources_parser = settings_subparsers.add_parser("clear-sources")
    settings_clear_sources_parser.add_argument("--format", choices=("text", "json"), default="text")
    settings_set_output_parser = settings_subparsers.add_parser("set-output")
    settings_set_output_parser.add_argument("path")
    settings_set_output_parser.add_argument("--format", choices=("text", "json"), default="text")

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
            return _handle_discover(args, defaults, user_settings)

        if args.command == "create-job":
            return _handle_create_job(args, outputs_root, defaults, user_settings)

        if args.command == "run":
            return _handle_run(args, outputs_root, defaults, user_settings)

        if args.command == "refresh":
            return _handle_refresh(args, outputs_root, defaults, user_settings)

        if args.command == "current":
            return _handle_current(args, outputs_root)

        if args.command == "export-current":
            return _handle_export_current(args, outputs_root)

        if args.command == "handoff":
            return _handle_handoff(args, runtime, defaults, user_settings, outputs_root)

        if args.command == "settings":
            return _handle_settings(args, runtime, defaults, user_settings)

        if args.command == "list-jobs":
            return _handle_list_jobs(args, outputs_root)

        if args.command == "show-job":
            return _handle_show_job(args, outputs_root)

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


def _is_docker_runtime() -> bool:
    return os.environ.get(DOCKER_RUNTIME_ENV, "").strip().lower() == "docker" or Path("/.dockerenv").exists()


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


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


def _handle_discover(
    args: argparse.Namespace,
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
) -> int:
    primary_root, backup_roots = _resolve_source_roots(args, defaults, user_settings)
    discovered = discover_threads(
        primary_root,
        backup_roots,
        _resolve_include_archived(args.include_archived_sources, defaults, user_settings),
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
    user_settings: UserSettings,
) -> int:
    request, job_dir = _prepare_job(args, outputs_root, defaults, user_settings)
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
    user_settings: UserSettings,
) -> int:
    request, job_dir = _prepare_job(args, outputs_root, defaults, user_settings)
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


def _handle_refresh(
    args: argparse.Namespace,
    outputs_root: Path,
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
) -> int:
    request, job_dir = _prepare_job(args, outputs_root, defaults, user_settings, settings_only=True)
    process_job(job_dir)
    payload = _build_refresh_summary(request, job_dir)
    _print_output(args.format, payload, _format_refresh_summary_text(payload))
    return 0


def _prepare_job(
    args: argparse.Namespace,
    outputs_root: Path,
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
    *,
    settings_only: bool = False,
) -> tuple[JobRequest, Path]:
    date_from = _normalize_date(args.date_from)
    date_to = _normalize_date(args.date_to)
    if date_from and date_to and date_from > date_to:
        raise ValueError("date_from must be on or before date_to.")

    primary_root, backup_roots = _resolve_source_roots(args, defaults, user_settings, settings_only=settings_only)
    include_archived_sources = _resolve_include_archived(
        args.include_archived_sources,
        defaults,
        user_settings,
    )
    include_tool_outputs = _resolve_include_tool_outputs(
        args.include_tool_outputs,
        defaults,
        user_settings,
    )
    redaction_profile = _resolve_redaction_profile(args.redaction_profile, defaults, user_settings)

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


def _handle_current(args: argparse.Namespace, outputs_root: Path) -> int:
    payload = _load_current_summary(outputs_root)
    _print_output(args.format, payload, _format_current_summary_text(payload))
    return 0


def _handle_export_current(args: argparse.Namespace, outputs_root: Path) -> int:
    payload = _load_current_summary(outputs_root)
    result_payload = _copy_current_archive(payload, args.to, overwrite=args.overwrite)
    _print_output(args.format, result_payload, _format_export_current_text(result_payload))
    return 0


def _handle_handoff(
    args: argparse.Namespace,
    runtime,
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
    outputs_root: Path,
) -> int:
    validation = _build_settings_validation(runtime, defaults, user_settings)
    if not validation["ok"]:
        issues = "; ".join(str(issue) for issue in validation.get("issues", []))
        raise ValueError(f"Settings validation failed. Run settings init or fix settings first. {issues}")

    request, job_dir = _prepare_job(args, outputs_root, defaults, user_settings, settings_only=True)
    process_job(job_dir)
    refresh_payload = _build_refresh_summary(request, job_dir)
    current_payload = _load_current_summary(outputs_root)
    export_payload = _copy_current_archive(current_payload, args.to, overwrite=args.overwrite)
    payload = {
        "state": "completed",
        "refresh": refresh_payload,
        "export": export_payload,
    }
    _print_output(
        args.format,
        payload,
        "\n".join(
            [
                "state: completed",
                f"refresh_id: {refresh_payload['refresh_id']}",
                f"archive_path: {refresh_payload['archive_path']}",
                f"destination_path: {export_payload['destination_path']}",
                f"thread_count: {refresh_payload['thread_count']}",
                f"event_count: {refresh_payload['event_count']}",
                f"processing_mode: {refresh_payload.get('processing_mode') or ''}",
                f"reused_thread_count: {refresh_payload['reused_thread_count']}",
                f"rendered_thread_count: {refresh_payload['rendered_thread_count']}",
            ]
        ),
    )
    return 0


def _handle_settings(
    args: argparse.Namespace,
    runtime,
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
) -> int:
    if args.settings_command == "init":
        return _handle_settings_init(args, runtime, user_settings)

    if args.settings_command == "show":
        return _print_settings(args, runtime, user_settings)

    if args.settings_command == "validate":
        return _handle_settings_validate(args, runtime, defaults, user_settings)

    if args.settings_command == "add-source":
        source_path = _normalize_config_path(args.path)
        source_roots = list(user_settings.source_roots or [])
        if source_path not in source_roots:
            source_roots.append(source_path)
        user_settings.source_roots = source_roots
        save_user_settings(user_settings, runtime)
        return _print_settings(args, runtime, user_settings)

    if args.settings_command == "remove-source":
        source_path = _normalize_config_path(args.path)
        user_settings.source_roots = [
            item for item in (user_settings.source_roots or []) if _normalize_config_path(item) != source_path
        ]
        save_user_settings(user_settings, runtime)
        return _print_settings(args, runtime, user_settings)

    if args.settings_command == "clear-sources":
        user_settings.source_roots = []
        save_user_settings(user_settings, runtime)
        return _print_settings(args, runtime, user_settings)

    if args.settings_command == "set-output":
        user_settings.outputs_root = _normalize_config_path(args.path)
        save_user_settings(user_settings, runtime)
        return _print_settings(args, runtime, user_settings)

    raise ValueError(f"Unsupported settings command: {args.settings_command}")


def _handle_settings_init(
    args: argparse.Namespace,
    runtime,
    user_settings: UserSettings,
) -> int:
    requested_sources = [
        _normalize_config_path(path)
        for path in args.source_root
        if str(path).strip()
    ] or _default_init_source_roots()
    existing_sources = list(user_settings.source_roots or [])
    if args.force:
        user_settings.source_roots = requested_sources
    else:
        merged_sources = list(existing_sources)
        for source in requested_sources:
            if source not in merged_sources:
                merged_sources.append(source)
        user_settings.source_roots = merged_sources

    output_root = _normalize_config_path(
        args.output_root
        or "/mnt/c/Codex/archive/TimelineForWindowsCodex/outputs"
    )
    if args.force or not user_settings.outputs_root:
        user_settings.outputs_root = output_root

    save_user_settings(user_settings, runtime)
    return _print_settings(args, runtime, user_settings)


def _load_current_summary(outputs_root: Path) -> dict[str, object]:
    current_path = outputs_root / "current.json"
    if not current_path.exists():
        raise FileNotFoundError(f"Current artifact was not found: {current_path}")

    current = read_json(current_path)
    archive_path = Path(str(current.get("archive_path") or ""))
    update_manifest = _read_optional_json(Path(str(current.get("update_manifest_path") or "")))
    fidelity = _read_optional_json(Path(str(current.get("fidelity_report_path") or "")))
    processing_profile = _read_optional_json(Path(str(current.get("processing_profile_path") or "")))
    warnings = fidelity.get("warnings", []) if isinstance(fidelity.get("warnings"), list) else []
    archive_size_bytes = archive_path.stat().st_size if archive_path.exists() and archive_path.is_file() else 0
    return {
        "state": current.get("state"),
        "job_id": current.get("job_id"),
        "updated_at": current.get("updated_at"),
        "run_directory": current.get("run_directory"),
        "archive_path": str(archive_path),
        "archive_exists": archive_path.exists() and archive_path.is_file(),
        "archive_size_bytes": archive_size_bytes,
        "readme_path": current.get("readme_path"),
        "catalog_path": current.get("catalog_path"),
        "update_manifest_path": current.get("update_manifest_path"),
        "fidelity_report_path": current.get("fidelity_report_path"),
        "processing_profile_path": current.get("processing_profile_path"),
        "processing_mode": current.get("processing_mode"),
        "thread_count": current.get("thread_count", 0),
        "event_count": current.get("event_count", 0),
        "reused_thread_count": current.get("reused_thread_count", 0),
        "rendered_thread_count": current.get("rendered_thread_count", 0),
        "update_counts": update_manifest.get("counts", {}),
        "fidelity_warning_count": len(warnings),
        "slowest_threads": processing_profile.get("slowest_threads", []),
    }


def _build_refresh_summary(request: JobRequest, job_dir: Path) -> dict[str, object]:
    status = load_status(job_dir)
    result = read_json(result_path(job_dir))
    update_manifest = read_json(job_dir / "update_manifest.json") if (job_dir / "update_manifest.json").exists() else {}
    current = read_json(job_dir.parent / "current.json") if (job_dir.parent / "current.json").exists() else {}
    fidelity = read_json(job_dir / "fidelity_report.json") if (job_dir / "fidelity_report.json").exists() else {}
    processing_profile = (
        read_json(job_dir / "processing_profile.json")
        if (job_dir / "processing_profile.json").exists()
        else {}
    )
    return {
        "refresh_id": request.job_id,
        "run_directory": str(job_dir),
        "state": status.state,
        "archive_path": result.get("archive_path"),
        "thread_count": result.get("thread_count", len(request.selected_threads)),
        "event_count": result.get("event_count", 0),
        "processing_mode": update_manifest.get("processing_mode"),
        "reused_thread_count": current.get("reused_thread_count", 0),
        "rendered_thread_count": current.get("rendered_thread_count", 0),
        "source_types": fidelity.get("source_types", []),
        "fidelity_warning_count": len(fidelity.get("warnings", [])) if isinstance(fidelity.get("warnings"), list) else 0,
        "update_counts": update_manifest.get("counts", {}),
        "slowest_threads": processing_profile.get("slowest_threads", []),
    }


def _format_refresh_summary_text(payload: dict[str, object]) -> str:
    counts = payload["update_counts"] if isinstance(payload.get("update_counts"), dict) else {}
    slowest_threads = payload["slowest_threads"] if isinstance(payload.get("slowest_threads"), list) else []
    return "\n".join(
        [
            f"refresh_id: {payload.get('refresh_id') or ''}",
            f"run_directory: {payload.get('run_directory') or ''}",
            f"state: {payload.get('state') or ''}",
            f"archive_path: {payload.get('archive_path') or ''}",
            f"thread_count: {payload.get('thread_count') or 0}",
            f"event_count: {payload.get('event_count') or 0}",
            f"processing_mode: {payload.get('processing_mode') or ''}",
            f"reused_thread_count: {payload.get('reused_thread_count') or 0}",
            f"rendered_thread_count: {payload.get('rendered_thread_count') or 0}",
            "updates: "
            + ", ".join(
                f"{name}={counts.get(name, 0)}"
                for name in ("new", "changed", "unchanged", "missing", "degraded")
            ),
            f"fidelity_warning_count: {payload.get('fidelity_warning_count') or 0}",
            "slowest_threads:",
            *[
                "- "
                + " | ".join(
                    [
                        str(item.get("thread_id") or ""),
                        str(item.get("preferred_title") or ""),
                        f"{item.get('processing_duration_ms', 0)}ms",
                        str(item.get("cache_status") or ""),
                    ]
                )
                for item in slowest_threads[:5]
                if isinstance(item, dict)
            ],
        ]
    )


def _copy_current_archive(
    current_payload: dict[str, object],
    destination: str,
    *,
    overwrite: bool,
) -> dict[str, object]:
    archive_path = Path(str(current_payload.get("archive_path") or ""))
    if not archive_path.exists() or not archive_path.is_file():
        raise FileNotFoundError(f"Current archive was not found: {archive_path}")

    destination_root = _resolve_destination_root(destination)
    destination_root.mkdir(parents=True, exist_ok=True)
    destination_path = destination_root / archive_path.name
    if destination_path.exists() and not overwrite:
        raise ValueError(f"Destination already exists. Pass --overwrite to replace it: {destination_path}")
    shutil.copy2(archive_path, destination_path)

    return {
        "state": "completed",
        "source_archive_path": str(archive_path),
        "destination_path": str(destination_path),
        "thread_count": current_payload.get("thread_count", 0),
        "event_count": current_payload.get("event_count", 0),
        "updated_at": current_payload.get("updated_at"),
    }


def _format_export_current_text(payload: dict[str, object]) -> str:
    return "\n".join(
        [
            f"state: {payload.get('state') or ''}",
            f"destination_path: {payload.get('destination_path') or ''}",
            f"source_archive_path: {payload.get('source_archive_path') or ''}",
            f"thread_count: {payload.get('thread_count') or 0}",
            f"event_count: {payload.get('event_count') or 0}",
        ]
    )


def _read_optional_json(path: Path) -> dict[str, object]:
    if not str(path) or not path.exists() or not path.is_file():
        return {}
    try:
        payload = read_json(path)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _format_current_summary_text(payload: dict[str, object]) -> str:
    counts = payload.get("update_counts") if isinstance(payload.get("update_counts"), dict) else {}
    slowest_threads = payload.get("slowest_threads") if isinstance(payload.get("slowest_threads"), list) else []
    lines = [
        f"state: {payload.get('state') or ''}",
        f"job_id: {payload.get('job_id') or ''}",
        f"updated_at: {payload.get('updated_at') or ''}",
        f"archive_path: {payload.get('archive_path') or ''}",
        f"archive_exists: {str(bool(payload.get('archive_exists'))).lower()}",
        f"archive_size_bytes: {payload.get('archive_size_bytes') or 0}",
        f"thread_count: {payload.get('thread_count') or 0}",
        f"event_count: {payload.get('event_count') or 0}",
        f"processing_mode: {payload.get('processing_mode') or ''}",
        f"reused_thread_count: {payload.get('reused_thread_count') or 0}",
        f"rendered_thread_count: {payload.get('rendered_thread_count') or 0}",
        "updates: "
        + ", ".join(
            f"{name}={counts.get(name, 0)}"
            for name in ("new", "changed", "unchanged", "missing", "degraded")
        ),
        f"fidelity_warning_count: {payload.get('fidelity_warning_count') or 0}",
        "slowest_threads:",
    ]
    lines.extend(
        "- "
        + " | ".join(
            [
                str(item.get("thread_id") or ""),
                str(item.get("preferred_title") or ""),
                f"{item.get('processing_duration_ms', 0)}ms",
                str(item.get("cache_status") or ""),
            ]
        )
        for item in slowest_threads[:5]
        if isinstance(item, dict)
    )
    return "\n".join(lines)


def _print_settings(
    args: argparse.Namespace,
    runtime,
    user_settings: UserSettings,
) -> int:
    settings_path = user_settings_path(runtime)
    effective_source_roots = _effective_source_roots_for_settings(load_runtime_defaults(runtime), user_settings)
    payload = {
        "settings_path": str(settings_path),
        "source_roots": list(user_settings.source_roots or []),
        "effective_source_roots": effective_source_roots,
        "outputs_root": str(_effective_outputs_root(runtime.outputs_root, user_settings)),
        "redaction_profile": user_settings.redaction_profile or None,
        "include_archived_sources": user_settings.include_archived_sources,
        "include_tool_outputs": user_settings.include_tool_outputs,
        "using_default_source_roots": not bool(user_settings.source_roots),
    }
    lines = [
        f"settings_path: {settings_path}",
        f"outputs_root: {payload['outputs_root']}",
        f"using_default_source_roots: {str(payload['using_default_source_roots']).lower()}",
        "source_roots:",
    ]
    lines.extend(f"- {source}" for source in payload["source_roots"])
    if not payload["source_roots"]:
        lines.append("- (not configured; runtime defaults will be used)")
        lines.append("effective_source_roots:")
        lines.extend(f"- {source}" for source in effective_source_roots)
    _print_output(args.format, payload, "\n".join(lines))
    return 0


def _handle_settings_validate(
    args: argparse.Namespace,
    runtime,
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
) -> int:
    payload = _build_settings_validation(runtime, defaults, user_settings)
    lines = [
        f"state: {'ok' if payload['ok'] else 'ng'}",
        f"settings_path: {payload['settings_path']}",
        f"outputs_root: {payload['outputs_root']['path']}",
        f"outputs_root_ready: {str(payload['outputs_root']['ready']).lower()}",
        "source_roots:",
    ]
    for source in payload["source_roots"]:
        lines.append(
            "- "
            + " | ".join(
                [
                    str(source["path"]),
                    f"exists={str(source['exists']).lower()}",
                    f"readable={str(source['readable']).lower()}",
                    f"kind={source['kind']}",
                ]
            )
        )
    if payload["issues"]:
        lines.append("issues:")
        lines.extend(f"- {issue}" for issue in payload["issues"])
    _print_output(args.format, payload, "\n".join(lines))
    return 0 if payload["ok"] else 1


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


def _resolve_source_roots(
    args: argparse.Namespace,
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
    *,
    settings_only: bool = False,
) -> tuple[str, list[str]]:
    if not settings_only and (getattr(args, "primary_root", None) or getattr(args, "backup_root", [])):
        return (
            _resolve_primary_root(getattr(args, "primary_root", None), defaults),
            _resolve_backup_roots(getattr(args, "backup_root", []), defaults),
        )

    configured = [item.strip() for item in (user_settings.source_roots or []) if item.strip()]
    if configured:
        return configured[0], configured[1:]

    return defaults.default_primary_codex_home_path, [
        item.strip() for item in defaults.default_backup_codex_home_paths or [] if item.strip()
    ]


def _resolve_include_archived(
    value: bool | None,
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
) -> bool:
    if value is not None:
        return bool(value)
    if user_settings.include_archived_sources is not None:
        return user_settings.include_archived_sources
    return defaults.default_include_archived_sources


def _resolve_include_tool_outputs(
    value: bool | None,
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
) -> bool:
    if value is not None:
        return bool(value)
    if user_settings.include_tool_outputs is not None:
        return user_settings.include_tool_outputs
    return defaults.default_include_tool_outputs


def _resolve_redaction_profile(
    value: str | None,
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
) -> str:
    profile = (
        value
        or user_settings.redaction_profile
        or defaults.default_redaction_profile
        or "strict"
    ).strip().lower()
    return "loose" if profile == "loose" else "strict"


def _effective_outputs_root(runtime_outputs_root: Path, user_settings: UserSettings) -> Path:
    configured = (user_settings.outputs_root or "").strip()
    if configured:
        return Path(configured).resolve()
    return runtime_outputs_root


def _effective_source_roots_for_settings(
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
) -> list[str]:
    configured = [item.strip() for item in (user_settings.source_roots or []) if item.strip()]
    if configured:
        return configured
    return [
        defaults.default_primary_codex_home_path,
        *[item.strip() for item in defaults.default_backup_codex_home_paths or [] if item.strip()],
    ]


def _default_init_source_roots() -> list[str]:
    candidates = [
        Path("/mnt/c/Users/amano/.codex"),
        Path("/mnt/c/Codex/archive/migration-backup-2026-03-27/codex-home"),
    ]
    existing = [
        str(path.resolve())
        for path in candidates
        if path.exists() and path.is_dir()
    ]
    return existing or [str(candidates[0])]


def _build_settings_validation(
    runtime,
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
) -> dict[str, object]:
    source_roots = _effective_source_roots_for_settings(defaults, user_settings)
    issues: list[str] = []
    source_rows: list[dict[str, object]] = []
    for index, source in enumerate(source_roots):
        path = Path(source).expanduser().resolve()
        exists = path.exists()
        is_dir = path.is_dir()
        readable = bool(exists and is_dir and os.access(path, os.R_OK))
        if not exists:
            issues.append(f"Source root does not exist: {path}")
        elif not is_dir:
            issues.append(f"Source root is not a directory: {path}")
        elif not readable:
            issues.append(f"Source root is not readable: {path}")
        source_rows.append(
            {
                "path": str(path),
                "kind": "primary" if index == 0 else "backup",
                "exists": exists,
                "is_directory": is_dir,
                "readable": readable,
            }
        )

    outputs_root = _effective_outputs_root(runtime.outputs_root, user_settings)
    output_parent = _nearest_existing_parent(outputs_root)
    output_ready = bool(output_parent is not None and os.access(output_parent, os.W_OK))
    if output_parent is None:
        issues.append(f"No existing parent directory for outputs_root: {outputs_root}")
    elif not output_ready:
        issues.append(f"Output root parent is not writable: {output_parent}")

    return {
        "ok": not issues,
        "settings_path": str(user_settings_path(runtime)),
        "using_default_source_roots": not bool(user_settings.source_roots),
        "source_roots": source_rows,
        "outputs_root": {
            "path": str(outputs_root),
            "exists": outputs_root.exists(),
            "is_directory": outputs_root.is_dir(),
            "nearest_existing_parent": str(output_parent) if output_parent is not None else "",
            "ready": output_ready,
        },
        "issues": issues,
    }


def _nearest_existing_parent(path: Path) -> Path | None:
    current = path
    while True:
        if current.exists():
            return current if current.is_dir() else current.parent
        if current.parent == current:
            return None
        current = current.parent


def _normalize_config_path(value: str) -> str:
    return str(Path(value).expanduser().resolve())


def _resolve_destination_root(value: str) -> Path:
    normalized = value.strip()
    if normalized.casefold() in {"desktop", "デスクトップ"}:
        return Path("/mnt/c/Users/amano/Desktop")
    return Path(normalized).expanduser().resolve()


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
