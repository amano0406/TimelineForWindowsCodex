from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from .contracts import JobRequest, ThreadSelection
from .discovery import discover_threads
from .fs_utils import now_iso, read_json
from .job_store import (
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
                    "Use Docker Compose instead, for example: docker compose run --rm worker settings status",
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

    items_parser = subparsers.add_parser("items")
    items_subparsers = items_parser.add_subparsers(dest="items_command", required=True)
    items_list_parser = items_subparsers.add_parser("list")
    _add_source_arguments(items_list_parser)
    _add_format_argument(items_list_parser)
    items_refresh_parser = items_subparsers.add_parser("refresh")
    _add_source_arguments(items_refresh_parser)
    _add_job_arguments(items_refresh_parser)
    items_refresh_parser.add_argument("--download-to")
    items_refresh_parser.add_argument("--overwrite", action="store_true")
    items_download_parser = items_subparsers.add_parser("download")
    items_download_parser.add_argument("--to", required=True)
    items_download_parser.add_argument("--overwrite", action="store_true")
    _add_format_argument(items_download_parser)

    runs_parser = subparsers.add_parser("runs")
    runs_subparsers = runs_parser.add_subparsers(dest="runs_command", required=True)
    runs_list_parser = runs_subparsers.add_parser("list")
    _add_format_argument(runs_list_parser)
    runs_show_parser = runs_subparsers.add_parser("show")
    runs_show_parser.add_argument("--run-id", required=True)
    _add_format_argument(runs_show_parser)

    settings_parser = subparsers.add_parser("settings")
    settings_subparsers = settings_parser.add_subparsers(dest="settings_command", required=True)
    settings_init_parser = settings_subparsers.add_parser("init")
    settings_init_parser.add_argument("--source-root", action="append", default=[])
    settings_init_parser.add_argument("--output-root")
    settings_init_parser.add_argument("--force", action="store_true")
    _add_format_argument(settings_init_parser)
    settings_status_parser = settings_subparsers.add_parser("status")
    _add_format_argument(settings_status_parser)

    settings_inputs_parser = settings_subparsers.add_parser("inputs")
    settings_inputs_subparsers = settings_inputs_parser.add_subparsers(dest="inputs_command", required=True)
    settings_inputs_list_parser = settings_inputs_subparsers.add_parser("list")
    _add_format_argument(settings_inputs_list_parser)
    settings_inputs_add_parser = settings_inputs_subparsers.add_parser("add")
    settings_inputs_add_parser.add_argument("path")
    _add_format_argument(settings_inputs_add_parser)
    settings_inputs_remove_parser = settings_inputs_subparsers.add_parser("remove")
    settings_inputs_remove_parser.add_argument("input")
    _add_format_argument(settings_inputs_remove_parser)
    settings_inputs_clear_parser = settings_inputs_subparsers.add_parser("clear")
    _add_format_argument(settings_inputs_clear_parser)

    settings_master_parser = settings_subparsers.add_parser("master")
    settings_master_subparsers = settings_master_parser.add_subparsers(dest="master_command", required=True)
    settings_master_show_parser = settings_master_subparsers.add_parser("show")
    _add_format_argument(settings_master_show_parser)
    settings_master_set_parser = settings_master_subparsers.add_parser("set")
    settings_master_set_parser.add_argument("path")
    _add_format_argument(settings_master_set_parser)

    args = parser.parse_args(argv)

    try:
        if args.command == "items":
            if args.items_command == "list":
                return _handle_items_list(args, defaults, user_settings)
            if args.items_command == "refresh":
                return _handle_refresh(
                    args,
                    outputs_root,
                    defaults,
                    user_settings,
                    settings_only=not _has_explicit_source_args(args),
                    download_to=args.download_to,
                    overwrite=args.overwrite,
                )
            if args.items_command == "download":
                return _handle_items_download(args, outputs_root)

        if args.command == "runs":
            if args.runs_command == "list":
                return _handle_list_jobs(args, outputs_root)
            if args.runs_command == "show":
                return _handle_show_job(args, outputs_root, args.run_id)

        if args.command == "settings":
            return _handle_settings(args, runtime, defaults, user_settings)
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


def _add_format_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--json", action="store_const", const="json", dest="format")


def _add_job_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--item-id", action="append", default=[])
    parser.add_argument(
        "--include-tool-outputs",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--include-compaction-recovery",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("--redaction-profile", choices=("strict", "loose"))
    _add_format_argument(parser)


def _has_explicit_source_args(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "primary_root", None) or getattr(args, "backup_root", []))


def _handle_items_list(
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
            "item_id": thread.thread_id,
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


def _handle_refresh(
    args: argparse.Namespace,
    outputs_root: Path,
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
    *,
    settings_only: bool = True,
    download_to: str | None = None,
    overwrite: bool = False,
) -> int:
    request, job_dir = _prepare_job(args, outputs_root, defaults, user_settings, settings_only=settings_only)
    process_job(job_dir)
    payload = _build_refresh_summary(request, job_dir)
    if download_to:
        current_payload = _load_current_summary(outputs_root)
        payload["download"] = _copy_current_archive(current_payload, download_to, overwrite=overwrite)
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
    include_compaction_recovery = _resolve_include_compaction_recovery(
        args.include_compaction_recovery,
        defaults,
        user_settings,
    )
    redaction_profile = _resolve_redaction_profile(args.redaction_profile, defaults, user_settings)

    discovered = discover_threads(primary_root, backup_roots, include_archived_sources)
    selected_threads = _select_threads(discovered, _selected_item_ids(args))
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
        include_compaction_recovery=include_compaction_recovery,
        redaction_profile=redaction_profile,
        selected_threads=selected_threads,
    )
    job_dir = outputs_root / job_id
    create_job(job_dir, request)
    return request, job_dir


def _handle_items_download(args: argparse.Namespace, outputs_root: Path) -> int:
    payload = _load_current_summary(outputs_root)
    result_payload = _copy_current_archive(payload, args.to, overwrite=args.overwrite)
    _print_output(args.format, result_payload, _format_items_download_text(result_payload))
    return 0


def _handle_settings(
    args: argparse.Namespace,
    runtime,
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
) -> int:
    if args.settings_command == "init":
        return _handle_settings_init(args, runtime, user_settings)

    if args.settings_command in {"show", "status"}:
        return _print_settings(args, runtime, user_settings)

    if args.settings_command == "inputs":
        return _handle_settings_inputs(args, runtime, user_settings)

    if args.settings_command == "master":
        return _handle_settings_master(args, runtime, user_settings)

    raise ValueError(f"Unsupported settings command: {args.settings_command}")


def _handle_settings_inputs(
    args: argparse.Namespace,
    runtime,
    user_settings: UserSettings,
) -> int:
    if args.inputs_command == "list":
        return _print_settings_inputs(args, runtime, user_settings)

    if args.inputs_command == "add":
        source_path = _normalize_config_path(args.path)
        source_roots = list(user_settings.source_roots or [])
        if source_path not in source_roots:
            source_roots.append(source_path)
        user_settings.source_roots = source_roots
        save_user_settings(user_settings, runtime)
        return _print_settings_inputs(args, runtime, user_settings)

    if args.inputs_command == "remove":
        selector = str(args.input).strip()
        source_roots = list(user_settings.source_roots or [])
        remaining = [
            item
            for item in source_roots
            if _source_input_id(item) != selector and _normalize_config_path(item) != _normalize_selector_path(selector)
        ]
        if len(remaining) == len(source_roots):
            raise ValueError(f"Input source was not found: {selector}")
        user_settings.source_roots = remaining
        save_user_settings(user_settings, runtime)
        return _print_settings_inputs(args, runtime, user_settings)

    if args.inputs_command == "clear":
        user_settings.source_roots = []
        save_user_settings(user_settings, runtime)
        return _print_settings_inputs(args, runtime, user_settings)

    raise ValueError(f"Unsupported settings inputs command: {args.inputs_command}")


def _handle_settings_master(
    args: argparse.Namespace,
    runtime,
    user_settings: UserSettings,
) -> int:
    if args.master_command == "show":
        return _print_settings_master(args, runtime, user_settings)

    if args.master_command == "set":
        user_settings.outputs_root = _normalize_config_path(args.path)
        save_user_settings(user_settings, runtime)
        return _print_settings_master(args, runtime, user_settings)

    raise ValueError(f"Unsupported settings master command: {args.master_command}")


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
        "run_id": current.get("job_id"),
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
        "run_id": request.job_id,
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
    lines = [
        f"run_id: {payload.get('run_id') or payload.get('refresh_id') or ''}",
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
    ]
    download = payload.get("download")
    if isinstance(download, dict):
        lines.append(f"download_destination_path: {download.get('destination_path') or ''}")
    lines.extend(
        [
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
    return "\n".join(lines)


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


def _format_items_download_text(payload: dict[str, object]) -> str:
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
        "include_compaction_recovery": user_settings.include_compaction_recovery,
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


def _print_settings_inputs(
    args: argparse.Namespace,
    runtime,
    user_settings: UserSettings,
) -> int:
    defaults = load_runtime_defaults(runtime)
    configured_roots = [item.strip() for item in (user_settings.source_roots or []) if item.strip()]
    effective_roots = _effective_source_roots_for_settings(defaults, user_settings)
    payload = {
        "settings_path": str(user_settings_path(runtime)),
        "configured": bool(configured_roots),
        "inputs": _source_input_rows(configured_roots),
        "effective_inputs": _source_input_rows(effective_roots),
    }
    lines = [
        f"settings_path: {payload['settings_path']}",
        f"configured: {str(payload['configured']).lower()}",
        "inputs:",
    ]
    rows = payload["inputs"] if configured_roots else payload["effective_inputs"]
    if configured_roots:
        lines.extend(
            f"- {row['input_id']} | {row['kind']} | {row['path']}"
            for row in rows
            if isinstance(row, dict)
        )
    else:
        lines.append("- (not configured; runtime defaults will be used)")
        lines.append("effective_inputs:")
        lines.extend(
            f"- {row['input_id']} | {row['kind']} | {row['path']}"
            for row in rows
            if isinstance(row, dict)
        )
    _print_output(args.format, payload, "\n".join(lines))
    return 0


def _print_settings_master(
    args: argparse.Namespace,
    runtime,
    user_settings: UserSettings,
) -> int:
    outputs_root = _effective_outputs_root(runtime.outputs_root, user_settings)
    payload = {
        "settings_path": str(user_settings_path(runtime)),
        "master_root": str(outputs_root),
        "configured": bool((user_settings.outputs_root or "").strip()),
    }
    _print_output(
        args.format,
        payload,
        "\n".join(
            [
                f"settings_path: {payload['settings_path']}",
                f"master_root: {payload['master_root']}",
                f"configured: {str(payload['configured']).lower()}",
            ]
        ),
    )
    return 0


def _handle_list_jobs(args: argparse.Namespace, outputs_root: Path) -> int:
    rows = []
    for job_dir in reversed(iter_run_dirs(outputs_root)):
        request = load_request(job_dir)
        status = load_status(job_dir)
        result = read_json(result_path(job_dir)) if result_path(job_dir).exists() else {}
        rows.append(
            {
                "run_id": request.job_id,
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


def _handle_show_job(args: argparse.Namespace, outputs_root: Path, run_id: str) -> int:
    job_dir = _resolve_job_dir(run_id, outputs_root)
    if not request_path(job_dir).exists():
        raise FileNotFoundError(f"Run was not found: {run_id}")

    request = load_request(job_dir)
    status = load_status(job_dir)
    result = read_json(result_path(job_dir)) if result_path(job_dir).exists() else {}
    manifest = read_json(manifest_path(job_dir)) if manifest_path(job_dir).exists() else {}
    payload = {
        "run_id": request.job_id,
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


def _resolve_include_compaction_recovery(
    value: bool | None,
    defaults: RuntimeDefaults,
    user_settings: UserSettings,
) -> bool:
    if value is not None:
        return bool(value)
    if user_settings.include_compaction_recovery is not None:
        return user_settings.include_compaction_recovery
    return defaults.default_include_compaction_recovery


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


def _source_input_rows(source_roots: list[str]) -> list[dict[str, object]]:
    return [
        {
            "input_id": _source_input_id(source),
            "path": _normalize_config_path(source),
            "kind": "primary" if index == 0 else "backup",
        }
        for index, source in enumerate(source_roots)
    ]


def _source_input_id(path: str) -> str:
    normalized = _normalize_config_path(path).casefold()
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]
    return f"input-{digest}"


def _normalize_selector_path(value: str) -> str:
    return _normalize_config_path(value)


def _normalize_config_path(value: str) -> str:
    return str(Path(value).expanduser().resolve())


def _resolve_destination_root(value: str) -> Path:
    normalized = value.strip()
    if normalized.casefold() in {"desktop", "デスクトップ"}:
        return Path("/mnt/c/Users/amano/Desktop")
    return Path(normalized).expanduser().resolve()


def _select_threads(
    discovered: list[ThreadSelection],
    selected_ids: list[str],
) -> list[ThreadSelection]:
    normalized_ids = [
        item.strip()
        for selected_id in selected_ids
        for item in str(selected_id).split(",")
        if item.strip()
    ]
    if not normalized_ids:
        return discovered

    selected_map = {thread.thread_id.casefold(): thread for thread in discovered}
    missing = [item for item in normalized_ids if item.casefold() not in selected_map]
    if missing:
        raise ValueError(f"Unknown item ids: {', '.join(missing)}")

    rows: list[ThreadSelection] = []
    seen: set[str] = set()
    for thread_id in normalized_ids:
        key = thread_id.casefold()
        if key in seen:
            continue
        seen.add(key)
        rows.append(selected_map[key])
    return rows


def _selected_item_ids(args: argparse.Namespace) -> list[str]:
    return [str(item) for item in getattr(args, "item_id", []) or []]


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
        return "No items discovered."
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
        return "No runs found."
    return "\n".join(
        " | ".join(
            [
                str(row.get("run_id") or ""),
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
        f"run_id: {request.job_id}",
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
