from __future__ import annotations

import argparse
import json
import os
import sys
from uuid import uuid4
from pathlib import Path
from typing import Any

from .contracts import RefreshRequest, ThreadSelection
from .discovery import discover_threads
from .fs_utils import now_iso
from .processor import build_download_archive, process_refresh
from .settings import RuntimeDefaults, load_runtime_defaults, load_runtime_paths
from .settings import UserSettings, load_user_settings, save_user_settings, user_settings_path

DOCKER_RUNTIME_ENV = "TIMELINE_FOR_WINDOWS_CODEX_RUNTIME"
ALLOW_HOST_RUN_ENV = "TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN"
DEFAULT_ITEMS_LIST_PAGE_SIZE = 100
ITEMS_LIST_SORT_FIELDS = ["updated_at", "created_at", "thread_id"]


def main(argv: list[str] | None = None) -> int:
    if not _is_docker_runtime() and not _truthy_env(ALLOW_HOST_RUN_ENV):
        print(
            "\n".join(
                [
                    "Host direct execution is disabled for normal operation.",
                    "Use the repository launcher instead, for example: .\\cli.ps1 settings status",
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
    _add_items_list_arguments(items_list_parser)
    _add_format_argument(items_list_parser)
    items_refresh_parser = items_subparsers.add_parser("refresh")
    _add_refresh_arguments(items_refresh_parser)
    items_refresh_parser.add_argument("--download-to")
    items_refresh_parser.add_argument("--overwrite", action="store_true")
    items_download_parser = items_subparsers.add_parser("download")
    items_download_parser.add_argument("--to", required=True)
    items_download_parser.add_argument("--item-id", action="append", default=[])
    items_download_parser.add_argument("--overwrite", action="store_true")
    _add_format_argument(items_download_parser)

    settings_parser = subparsers.add_parser("settings")
    settings_subparsers = settings_parser.add_subparsers(dest="settings_command", required=True)
    settings_init_parser = settings_subparsers.add_parser("init")
    settings_init_parser.add_argument("--output-root")
    settings_init_parser.add_argument("--force", action="store_true")
    _add_format_argument(settings_init_parser)
    settings_status_parser = settings_subparsers.add_parser("status")
    _add_format_argument(settings_status_parser)

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
                return _handle_items_list(args, defaults)
            if args.items_command == "refresh":
                return _handle_refresh(
                    args,
                    outputs_root,
                    defaults,
                    download_to=args.download_to,
                    overwrite=args.overwrite,
                )
            if args.items_command == "download":
                return _handle_items_download(args, outputs_root)

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


def _add_format_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--json", action="store_const", const="json", dest="format")


def _add_items_list_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--page", type=int)
    parser.add_argument("--page-size", type=int)
    parser.add_argument("--all", action="store_true")


def _add_refresh_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--item-id", action="append", default=[])
    _add_format_argument(parser)


def _handle_items_list(
    args: argparse.Namespace,
    defaults: RuntimeDefaults,
) -> int:
    primary_root, backup_roots = _resolve_source_roots(defaults)
    discovered = discover_threads(primary_root, backup_roots, True)
    all_items = _sort_item_rows([_thread_selection_to_item(thread) for thread in discovered])
    pagination = _resolve_pagination(args, len(all_items))
    page_items = all_items[pagination["offset"]: pagination["range_end"]]
    payload = {
        "schema_version": 1,
        "state": "completed",
        "item_count": len(all_items),
        "total_items": len(all_items),
        "sort": {
            "order": "desc",
            "fields": ITEMS_LIST_SORT_FIELDS,
        },
        "pagination": {
            **pagination,
            "returned_items": len(page_items),
        },
        "items": page_items,
    }
    _print_output(args.format, payload, _format_items_list_text(payload))
    return 0


def _thread_selection_to_item(thread: ThreadSelection) -> dict[str, object]:
    return {
        "item_id": thread.thread_id,
        "thread_id": thread.thread_id,
        "preferred_title": thread.preferred_title,
        "observed_thread_names": [item.to_dict() for item in thread.observed_thread_names],
        "created_at": None,
        "source_root_path": thread.source_root_path,
        "source_root_kind": thread.source_root_kind,
        "session_path": thread.session_path,
        "updated_at": thread.updated_at,
        "cwd": thread.cwd,
        "first_user_message_excerpt": thread.first_user_message_excerpt,
    }


def _sort_item_rows(items: list[Any]) -> list[dict[str, object]]:
    rows = [item for item in items if isinstance(item, dict)]
    return sorted(
        rows,
        key=lambda item: (
            str(item.get("updated_at") or ""),
            str(item.get("created_at") or ""),
            str(item.get("thread_id") or ""),
        ),
        reverse=True,
    )


def _resolve_pagination(args: argparse.Namespace, total_count: int) -> dict[str, object]:
    if args.all or (args.page is None and args.page_size is None):
        return {
            "mode": "all",
            "page": 1,
            "page_size": total_count,
            "total_items": total_count,
            "total_pages": 1 if total_count else 0,
            "offset": 0,
            "range_start": 1 if total_count else 0,
            "range_end": total_count,
            "has_previous": False,
            "has_next": False,
        }

    page = int(args.page or 1)
    page_size = int(args.page_size or DEFAULT_ITEMS_LIST_PAGE_SIZE)
    if page < 1:
        raise ValueError("--page must be 1 or greater.")
    if page_size < 1:
        raise ValueError("--page-size must be 1 or greater.")

    offset = (page - 1) * page_size
    range_end = min(offset + page_size, total_count)
    total_pages = (total_count + page_size - 1) // page_size if total_count else 0
    return {
        "mode": "page",
        "page": page,
        "page_size": page_size,
        "total_items": total_count,
        "total_pages": total_pages,
        "offset": offset,
        "range_start": offset + 1 if offset < total_count else 0,
        "range_end": range_end,
        "has_previous": page > 1 and total_count > 0,
        "has_next": page < total_pages,
    }


def _handle_refresh(
    args: argparse.Namespace,
    outputs_root: Path,
    defaults: RuntimeDefaults,
    *,
    download_to: str | None = None,
    overwrite: bool = False,
) -> int:
    request = _prepare_refresh_request(args, outputs_root, defaults)
    payload = process_refresh(request, outputs_root)
    if download_to:
        payload["download"] = build_download_archive(
            outputs_root,
            _resolve_destination_root(download_to),
            overwrite=overwrite,
            selected_item_ids=_selected_item_ids(args),
        )
    _print_output(args.format, payload, _format_refresh_summary_text(payload))
    return 0


def _prepare_refresh_request(
    args: argparse.Namespace,
    outputs_root: Path,
    defaults: RuntimeDefaults,
) -> RefreshRequest:
    primary_root, backup_roots = _resolve_source_roots(defaults)

    discovered = discover_threads(primary_root, backup_roots, True)
    selected_threads = _select_threads(discovered, _selected_item_ids(args))
    if not selected_threads:
        raise ValueError("No threads matched the current selection.")

    refresh_id = _create_refresh_id(outputs_root)
    request = RefreshRequest(
        refresh_id=refresh_id,
        created_at=now_iso(),
        primary_codex_home_path=primary_root,
        backup_codex_home_paths=backup_roots,
        include_archived_sources=True,
        include_tool_outputs=False,
        include_compaction_recovery=False,
        redaction_profile="none",
        selected_threads=selected_threads,
    )
    return request


def _handle_items_download(args: argparse.Namespace, outputs_root: Path) -> int:
    result_payload = build_download_archive(
        outputs_root,
        _resolve_destination_root(args.to),
        overwrite=args.overwrite,
        selected_item_ids=_selected_item_ids(args),
    )
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

    if args.settings_command == "master":
        return _handle_settings_master(args, runtime, user_settings)

    raise ValueError(f"Unsupported settings command: {args.settings_command}")


def _handle_settings_master(
    args: argparse.Namespace,
    runtime,
    user_settings: UserSettings,
) -> int:
    if args.master_command == "show":
        return _print_settings_master(args, runtime, user_settings)

    if args.master_command == "set":
        user_settings.output_root = _normalize_config_path(args.path)
        save_user_settings(user_settings, runtime)
        return _print_settings_master(args, runtime, user_settings)

    raise ValueError(f"Unsupported settings master command: {args.master_command}")


def _handle_settings_init(
    args: argparse.Namespace,
    runtime,
    user_settings: UserSettings,
) -> int:
    output_root = _normalize_config_path(
        args.output_root
        or str(runtime.outputs_root)
    )
    if args.force or not user_settings.output_root:
        user_settings.output_root = output_root

    save_user_settings(user_settings, runtime)
    return _print_settings(args, runtime, user_settings)


def _format_refresh_summary_text(payload: dict[str, object]) -> str:
    counts = payload["update_counts"] if isinstance(payload.get("update_counts"), dict) else {}
    lines = [
        f"refresh_id: {payload.get('refresh_id') or ''}",
        f"state: {payload.get('state') or ''}",
        f"master_root: {payload.get('master_root') or ''}",
        f"thread_count: {payload.get('thread_count') or 0}",
        f"message_count: {payload.get('message_count') or 0}",
        f"attachment_count: {payload.get('attachment_count') or 0}",
        f"processing_mode: {payload.get('processing_mode') or ''}",
        f"reused_thread_count: {payload.get('reused_thread_count') or 0}",
        f"rendered_thread_count: {payload.get('rendered_thread_count') or 0}",
        "updates: "
        + ", ".join(
            f"{name}={counts.get(name, 0)}"
            for name in ("new", "changed", "unchanged", "missing", "degraded")
        ),
    ]
    download = payload.get("download")
    if isinstance(download, dict):
        lines.append(f"download_destination_path: {download.get('destination_path') or ''}")
    return "\n".join(lines)


def _format_items_download_text(payload: dict[str, object]) -> str:
    return "\n".join(
        [
            f"state: {payload.get('state') or ''}",
            f"destination_path: {payload.get('destination_path') or ''}",
            f"master_root: {payload.get('master_root') or ''}",
            f"thread_count: {payload.get('thread_count') or 0}",
            f"message_count: {payload.get('message_count') or 0}",
        ]
    )


def _format_items_list_text(payload: dict[str, object]) -> str:
    pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
    sort_payload = payload.get("sort") if isinstance(payload.get("sort"), dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    total_items = int(pagination.get("total_items") or payload.get("total_items") or 0)
    returned_items = int(pagination.get("returned_items") or 0)
    start = int(pagination.get("range_start") or 0)
    end = int(pagination.get("range_end") or 0) if returned_items else 0
    sort_text = " ".join(
        [
            ",".join(str(field) for field in sort_payload.get("fields", []) if str(field).strip()),
            str(sort_payload.get("order") or ""),
        ]
    ).strip()
    lines = [
        f"state: {payload.get('state') or ''}",
        f"sort: {sort_text}",
        f"items: {start}-{end} / {total_items}",
    ]
    for item in items:
        if not isinstance(item, dict):
            continue
        lines.append(
            " | ".join(
                [
                    str(item.get("updated_at") or "-"),
                    str(item.get("thread_id") or "-"),
                    str(item.get("preferred_title") or item.get("thread_id") or "-"),
                ]
            )
        )
    return "\n".join(lines)


def _print_settings(
    args: argparse.Namespace,
    runtime,
    user_settings: UserSettings,
) -> int:
    settings_path = user_settings_path(runtime)
    effective_source_roots = _effective_source_roots_for_settings(load_runtime_defaults(runtime))
    payload = {
        "settings_path": str(settings_path),
        "sourceRoots": effective_source_roots,
        "outputRoot": str(_effective_outputs_root(runtime.outputs_root, user_settings)),
    }
    lines = [
        f"settings_path: {settings_path}",
        f"outputRoot: {payload['outputRoot']}",
        "sourceRoots: fixed runtime defaults; not stored in settings.json",
    ]
    lines.extend(f"- {source}" for source in effective_source_roots)
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
        "outputRoot": str(outputs_root),
        "configured": bool((user_settings.output_root or "").strip()),
    }
    _print_output(
        args.format,
        payload,
        "\n".join(
            [
                f"settings_path: {payload['settings_path']}",
                f"outputRoot: {payload['outputRoot']}",
                f"configured: {str(payload['configured']).lower()}",
            ]
        ),
    )
    return 0


def _resolve_source_roots(defaults: RuntimeDefaults) -> tuple[str, list[str]]:
    return defaults.primary_source_root, [
        item.strip() for item in defaults.backup_source_roots or [] if item.strip()
    ]


def _effective_outputs_root(runtime_outputs_root: Path, user_settings: UserSettings) -> Path:
    configured = (user_settings.output_root or "").strip()
    if configured:
        return _config_path_to_runtime_path(configured)
    return runtime_outputs_root


def _effective_source_roots_for_settings(
    defaults: RuntimeDefaults,
) -> list[str]:
    return [
        defaults.primary_source_root,
        *[item.strip() for item in defaults.backup_source_roots or [] if item.strip()],
    ]


def _normalize_config_path(value: str) -> str:
    raw = value.strip()
    if _is_windows_drive_path(raw):
        drive = raw[0].upper()
        rest = raw[3:].replace("/", "\\")
        return f"{drive}:\\{rest}"
    return str(Path(raw).expanduser().resolve())


def _resolve_destination_root(value: str) -> Path:
    normalized = value.strip()
    if normalized.casefold() in {"desktop", "デスクトップ"}:
        return Path("/mnt/c/Users/amano/Desktop")
    return _config_path_to_runtime_path(normalized)


def _config_path_to_runtime_path(value: str) -> Path:
    raw = value.strip()
    if _is_windows_drive_path(raw):
        drive = raw[0].lower()
        rest = raw[3:].replace("\\", "/")
        return Path(f"/mnt/{drive}/{rest}").resolve()
    return Path(raw).expanduser().resolve()


def _is_windows_drive_path(value: str) -> bool:
    return len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"} and value[0].isalpha()


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


def _print_output(format_name: str, payload: object, text_output: str) -> None:
    if format_name == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(text_output)


def _create_refresh_id(outputs_root: Path) -> str:
    outputs_root.mkdir(parents=True, exist_ok=True)
    stamp = now_iso().replace(":", "").replace("-", "")[:15]
    return f"refresh-{stamp}-{uuid4().hex[:8]}"
