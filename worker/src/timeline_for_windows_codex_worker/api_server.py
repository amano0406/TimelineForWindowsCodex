from __future__ import annotations

import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .discovery import discover_threads
from .fs_utils import ensure_dir
from .fs_utils import now_iso
from .fs_utils import write_json_atomic
from .api_services import effective_outputs_root
from .api_services import resolve_destination_root
from .api_services import resolve_pagination
from .api_services import resolve_source_roots
from .api_services import runtime_path_to_config_text
from .api_services import select_threads
from .api_services import sort_item_rows
from .processor import build_download_archive
from .processor import collect_master_items
from .processor import process_refresh
from .processor import remove_master_items
from .settings import UserSettings
from .settings import load_runtime_defaults
from .settings import load_runtime_paths
from .settings import load_user_settings
from .settings import save_user_settings
from .settings import user_settings_path
from .contracts import RefreshRequest


PRODUCT_ID = "windows-codex"
PRODUCT_NAME = "TimelineForWindowsCodex"
JOB_SCHEMA_VERSION = 1
ACTIVE_JOBS: dict[str, threading.Thread] = {}
ACTIVE_JOBS_LOCK = threading.Lock()


def handle_request(method: str, path: str, request: dict[str, Any] | None) -> tuple[int, Any]:
    route = path.rstrip("/") or "/"
    if method == "GET" and route == "/health":
        return HTTPStatus.OK, True
    if method == "GET" and route == "/jobs":
        return HTTPStatus.OK, jobs_list_payload()
    if method == "GET" and route == "/jobs/active":
        return HTTPStatus.OK, jobs_active_payload()
    if method == "GET" and route.startswith("/jobs/"):
        return HTTPStatus.OK, job_status_payload(route.removeprefix("/jobs/"))
    if method != "POST":
        return HTTPStatus.NOT_FOUND, error_payload(f"Endpoint not found: {method} {path}")

    try:
        payload = request or {}
        if route == "/jobs":
            return HTTPStatus.OK, jobs_start_payload(payload)
        if route == "/settings/init":
            return HTTPStatus.OK, settings_init_payload(payload)
        if route == "/settings/status":
            return HTTPStatus.OK, settings_status_payload()
        if route == "/items/list":
            return HTTPStatus.OK, items_list_payload(payload)
        if route == "/items/refresh":
            return HTTPStatus.OK, items_refresh_payload(payload)
        if route == "/items/detail":
            return HTTPStatus.OK, items_detail_payload(payload)
        if route == "/items/download":
            return HTTPStatus.OK, items_download_payload(payload)
        if route == "/items/remove":
            return HTTPStatus.OK, items_remove_payload(payload)
    except Exception as exc:
        return HTTPStatus.INTERNAL_SERVER_ERROR, error_payload(str(exc), exc.__class__.__name__)

    return HTTPStatus.NOT_FOUND, error_payload(f"Endpoint not found: {method} {path}")


def runtime_context() -> tuple[Any, Any, UserSettings, Path]:
    runtime = load_runtime_paths()
    defaults = load_runtime_defaults(runtime)
    user_settings = load_user_settings(runtime)
    outputs_root = effective_outputs_root(runtime.outputs_root, user_settings)
    return runtime, defaults, user_settings, outputs_root


def settings_init_payload(request: dict[str, Any]) -> dict[str, Any]:
    runtime, defaults, user_settings, _outputs_root = runtime_context()
    if get_bool_any(request, ["force"], False) or not user_settings.output_root:
        output_root = get_string_any(request, ["outputRoot", "output_root", "outputsRoot", "outputs_root"])
        user_settings.output_root = output_root or str(runtime.outputs_root)
        save_user_settings(user_settings, runtime)
    return settings_status_payload(defaults=defaults, runtime=runtime, user_settings=user_settings)


def settings_status_payload(
    *,
    defaults: Any | None = None,
    runtime: Any | None = None,
    user_settings: UserSettings | None = None,
) -> dict[str, Any]:
    if runtime is None or defaults is None or user_settings is None:
        runtime, defaults, user_settings, _outputs_root = runtime_context()
    outputs_root = effective_outputs_root(runtime.outputs_root, user_settings)
    source_roots = [defaults.primary_source_root, *[item for item in defaults.backup_source_roots if item]]
    return {
        "settings_path": str(user_settings_path(runtime)),
        "sourceRoots": source_roots,
        "source_roots": source_roots,
        "effective_source_roots": source_roots,
        "outputRoot": str(outputs_root),
        "outputs_root": str(outputs_root),
        "redaction_profile": "",
        "include_archived_sources": True,
        "include_tool_outputs": False,
        "include_compaction_recovery": False,
        "using_default_source_roots": True,
    }


def items_list_payload(request: dict[str, Any]) -> dict[str, Any]:
    _runtime, _defaults, _user_settings, outputs_root = runtime_context()
    all_items = sort_item_rows(list_master_item_rows(outputs_root))
    pagination = resolve_pagination(
        get_optional_positive_int(request, ["page"]),
        get_optional_positive_int(request, ["pageSize", "page_size"]),
        len(all_items),
    )
    page_items = all_items[int(pagination["offset"]) : int(pagination["range_end"])]
    return {
        "schema_version": 1,
        "state": "completed",
        "item_count": len(all_items),
        "total_items": len(all_items),
        "source": "master",
        "master_root": str(outputs_root),
        "sort": {
            "order": "desc",
            "fields": ["updated_at", "created_at", "thread_id"],
        },
        "pagination": {
            **pagination,
            "returned_items": len(page_items),
        },
        "items": page_items,
    }


def list_master_item_rows(outputs_root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in collect_master_items(outputs_root):
        item_id = str(row.get("thread_id") or row.get("item_dir_name") or "").strip()
        directory_path = str(row.get("directory_path") or row.get("item_dir") or "")
        rows.append(
            {
                **row,
                "item_id": item_id,
                "thread_id": item_id,
                "directory_path": directory_path,
                "directoryPath": directory_path,
                "timelinePath": row.get("timeline_path") or "",
                "convertInfoPath": row.get("convert_info_path") or "",
            }
        )
    return rows


def items_refresh_payload(request: dict[str, Any]) -> dict[str, Any]:
    refresh_id = get_string_any(request, ["refreshId", "refresh_id", "jobId", "job_id"])
    if not refresh_id:
        refresh_id = new_job_id("refresh")
    refresh_request, outputs_root = build_refresh_request(request, refresh_id)
    result = process_refresh(refresh_request, outputs_root)
    append_optional_download(result, request, outputs_root)
    return result


def build_refresh_request(request: dict[str, Any], refresh_id: str) -> tuple[RefreshRequest, Path]:
    _runtime, defaults, _user_settings, outputs_root = runtime_context()
    primary_root, backup_roots = resolve_source_roots(defaults)
    discovered = discover_threads(primary_root, backup_roots, True)
    selected_threads = select_threads(discovered, get_item_ids(request))
    if not selected_threads:
        raise ValueError("No threads matched the current selection.")
    return (
        RefreshRequest(
            refresh_id=refresh_id,
            created_at=now_iso(),
            primary_codex_home_path=primary_root,
            backup_codex_home_paths=backup_roots,
            include_archived_sources=True,
            include_tool_outputs=False,
            include_compaction_recovery=False,
            redaction_profile="none",
            selected_threads=selected_threads,
        ),
        outputs_root,
    )


def append_optional_download(result: dict[str, object], request: dict[str, Any], outputs_root: Path) -> None:
    download_to = get_string_any(request, ["downloadTo", "download_to", "to"])
    if download_to:
        result["download"] = normalize_download_response(
            build_download_archive(
                outputs_root,
                resolve_destination_root(download_to),
                overwrite=get_bool_any(request, ["overwrite"], False),
                selected_item_ids=get_item_ids(request),
            )
        )


def jobs_start_payload(request: dict[str, Any]) -> dict[str, Any]:
    if get_string_any(request, ["type"]) not in {"", "refresh"}:
        raise ValueError("Unsupported job type.")

    active_status = get_first_active_job_status()
    if active_status is not None:
        return active_status

    options_node = request.get("options")
    options = dict(options_node) if isinstance(options_node, dict) else dict(request)
    job_id = get_string_any(request, ["jobId", "job_id", "refreshId", "refresh_id"])
    if not job_id:
        job_id = new_job_id("job")
    job_id = sanitize_job_id(job_id)
    options["refreshId"] = job_id

    write_job_status(
        job_id,
        state="queued",
        phase="refresh",
        stage="queued",
        message="Windows Codex refresh is queued.",
        progress={"percent": 0, "current": 0, "total": 0, "unit": "threads", "currentItem": ""},
    )
    thread = threading.Thread(target=run_refresh_job, args=(job_id, options), daemon=True)
    with ACTIVE_JOBS_LOCK:
        ACTIVE_JOBS[job_id] = thread
    thread.start()
    return read_job_status(job_id) or make_job_status(job_id, state="queued", message="Windows Codex refresh is queued.")


def jobs_active_payload() -> dict[str, Any]:
    status = get_first_active_job_status()
    if status is not None:
        return status
    return make_job_status(
        "",
        state="none",
        phase="idle",
        stage="idle",
        message="No Windows Codex refresh job is active.",
        progress={"percent": 0, "current": 0, "total": 0, "unit": "threads", "currentItem": ""},
    )


def jobs_list_payload() -> dict[str, Any]:
    mark_stale_jobs_interrupted(active_job_ids())
    statuses = []
    for path in sorted(jobs_root().glob("*/status.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        status = read_json_object(path)
        if status is not None:
            statuses.append(normalize_job_status(status))
    return {
        "schemaVersion": JOB_SCHEMA_VERSION,
        "productId": PRODUCT_ID,
        "productName": PRODUCT_NAME,
        "jobs": statuses,
    }


def job_status_payload(job_id: str) -> dict[str, Any]:
    normalized_id = sanitize_job_id(job_id)
    mark_stale_jobs_interrupted(active_job_ids())
    status = read_job_status(normalized_id)
    if status is None:
        raise ValueError("Job was not found.")
    return status


def run_refresh_job(job_id: str, options: dict[str, Any]) -> None:
    try:
        update_job_status(
            job_id,
            state="running",
            phase="refresh",
            stage="discover",
            message="Discovering Windows Codex threads.",
            startedAt=now_iso(),
        )
        refresh_request, outputs_root = build_refresh_request(options, job_id)
        total = len(refresh_request.selected_threads)
        update_job_status(
            job_id,
            state="running",
            phase="refresh",
            stage="convert",
            message="Refreshing Windows Codex threads.",
            progress={"percent": 0, "current": 0, "total": total, "unit": "threads", "currentItem": ""},
        )

        def on_progress(progress: dict[str, object]) -> None:
            current = int(progress.get("current") or 0)
            progress_total = int(progress.get("total") or total)
            percent = round((current / progress_total) * 95, 2) if progress_total > 0 else 0
            update_job_status(
                job_id,
                state="running",
                phase="refresh",
                stage=str(progress.get("stage") or "convert"),
                message=str(progress.get("message") or "Refreshing Windows Codex threads."),
                progress={
                    "percent": percent,
                    "current": current,
                    "total": progress_total,
                    "unit": "threads",
                    "currentItem": str(progress.get("current_item") or progress.get("currentItem") or ""),
                },
            )

        result = process_refresh(refresh_request, outputs_root, progress_callback=on_progress)
        if get_string_any(options, ["downloadTo", "download_to", "to"]):
            update_job_status(
                job_id,
                state="running",
                phase="refresh",
                stage="download",
                message="Creating Windows Codex download archive.",
                progress={"percent": 96, "current": total, "total": total, "unit": "threads", "currentItem": ""},
            )
            append_optional_download(result, options, outputs_root)
        update_job_status(
            job_id,
            state="completed",
            phase="refresh",
            stage="completed",
            message="Windows Codex refresh completed.",
            completedAt=now_iso(),
            progress={"percent": 100, "current": total, "total": total, "unit": "threads", "currentItem": ""},
            error="",
            result=result,
        )
    except Exception as exc:
        update_job_status(
            job_id,
            state="failed",
            phase="refresh",
            stage="failed",
            message="Windows Codex refresh failed.",
            completedAt=now_iso(),
            error=str(exc),
        )
    finally:
        with ACTIVE_JOBS_LOCK:
            ACTIVE_JOBS.pop(job_id, None)


def get_first_active_job_status() -> dict[str, Any] | None:
    active_ids = active_job_ids()
    mark_stale_jobs_interrupted(active_ids)
    for job_id in sorted(active_ids):
        status = read_job_status(job_id)
        if status is not None:
            return status
    return None


def active_job_ids() -> set[str]:
    with ACTIVE_JOBS_LOCK:
        dead = [job_id for job_id, thread in ACTIVE_JOBS.items() if not thread.is_alive()]
        for job_id in dead:
            ACTIVE_JOBS.pop(job_id, None)
        return set(ACTIVE_JOBS)


def mark_stale_jobs_interrupted(active_ids: set[str]) -> None:
    for path in jobs_root().glob("*/status.json"):
        status = read_json_object(path)
        if status is None:
            continue
        job_id = str(status.get("jobId") or path.parent.name)
        if job_id in active_ids:
            continue
        state = str(status.get("state") or "").lower()
        if state not in {"queued", "running"}:
            continue
        update_job_status(
            job_id,
            state="interrupted",
            phase=str(status.get("phase") or "refresh"),
            stage="interrupted",
            message="Windows Codex refresh was interrupted before completion.",
            completedAt=now_iso(),
            error="The worker process stopped or the in-memory job was lost before the refresh completed.",
        )


def write_job_status(
    job_id: str,
    *,
    state: str,
    phase: str = "refresh",
    stage: str = "",
    message: str = "",
    progress: dict[str, object] | None = None,
    error: str = "",
    result: dict[str, object] | None = None,
) -> dict[str, Any]:
    status = make_job_status(job_id, state=state, phase=phase, stage=stage, message=message, progress=progress, error=error, result=result)
    write_json_atomic(job_status_path(job_id), status)
    return status


def update_job_status(job_id: str, **fields: Any) -> dict[str, Any]:
    status = read_job_status(job_id) or make_job_status(job_id, state="queued", message="Windows Codex refresh is queued.")
    for key, value in fields.items():
        if value is not None:
            status[key] = value
    status["updatedAt"] = now_iso()
    if status.get("state") in {"completed", "failed", "interrupted"} and not status.get("completedAt"):
        status["completedAt"] = now_iso()
    write_json_atomic(job_status_path(job_id), status)
    return normalize_job_status(status)


def make_job_status(
    job_id: str,
    *,
    state: str,
    phase: str = "refresh",
    stage: str = "",
    message: str = "",
    progress: dict[str, object] | None = None,
    error: str = "",
    result: dict[str, object] | None = None,
) -> dict[str, Any]:
    now = now_iso()
    return {
        "schemaVersion": JOB_SCHEMA_VERSION,
        "productId": PRODUCT_ID,
        "productName": PRODUCT_NAME,
        "type": "refresh",
        "jobId": job_id,
        "state": state,
        "phase": phase,
        "stage": stage,
        "message": message,
        "progress": progress or {"percent": 0, "current": 0, "total": 0, "unit": "threads", "currentItem": ""},
        "startedAt": now if state in {"running", "completed", "failed", "interrupted"} else "",
        "updatedAt": now,
        "completedAt": now if state in {"completed", "failed", "interrupted"} else "",
        "error": error,
        "warnings": [],
        "result": result,
    }


def normalize_job_status(status: dict[str, Any]) -> dict[str, Any]:
    progress = status.get("progress")
    if not isinstance(progress, dict):
        progress = {"percent": 0, "current": 0, "total": 0, "unit": "threads", "currentItem": ""}
    normalized = {
        "schemaVersion": int(status.get("schemaVersion") or JOB_SCHEMA_VERSION),
        "productId": str(status.get("productId") or PRODUCT_ID),
        "productName": str(status.get("productName") or PRODUCT_NAME),
        "type": str(status.get("type") or "refresh"),
        "jobId": str(status.get("jobId") or ""),
        "state": str(status.get("state") or ""),
        "phase": str(status.get("phase") or ""),
        "stage": str(status.get("stage") or ""),
        "message": str(status.get("message") or ""),
        "progress": {
            "percent": float(progress.get("percent") or 0),
            "current": int(progress.get("current") or 0),
            "total": int(progress.get("total") or 0),
            "unit": str(progress.get("unit") or "threads"),
            "currentItem": str(progress.get("currentItem") or progress.get("current_item") or ""),
        },
        "startedAt": str(status.get("startedAt") or ""),
        "updatedAt": str(status.get("updatedAt") or ""),
        "completedAt": str(status.get("completedAt") or ""),
        "error": str(status.get("error") or ""),
        "warnings": status.get("warnings") if isinstance(status.get("warnings"), list) else [],
        "result": status.get("result"),
    }
    if normalized["state"] == "interrupted" and not normalized["error"]:
        normalized["error"] = normalized["message"]
    return normalized


def read_job_status(job_id: str) -> dict[str, Any] | None:
    payload = read_json_object(job_status_path(job_id))
    return normalize_job_status(payload) if payload is not None else None


def job_status_path(job_id: str) -> Path:
    return jobs_root() / sanitize_job_id(job_id) / "status.json"


def jobs_root() -> Path:
    runtime = load_runtime_paths()
    return ensure_dir(runtime.appdata_root / "jobs")


def new_job_id(prefix: str) -> str:
    return f"{prefix}-{now_iso().replace(':', '').replace('-', '')[:15]}-{os.urandom(4).hex()}"


def sanitize_job_id(job_id: str) -> str:
    text = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in str(job_id or "").strip())
    text = text.strip("-_.")
    if not text:
        raise ValueError("Job id is required.")
    return text[:160]


def items_download_payload(request: dict[str, Any]) -> dict[str, Any]:
    _runtime, _defaults, _user_settings, outputs_root = runtime_context()
    destination = get_string_any(request, ["to", "downloadTo", "download_to", "outputPath", "output_path"])
    if not destination:
        raise ValueError("Download destination is required.")
    return normalize_download_response(
        build_download_archive(
            outputs_root,
            resolve_destination_root(destination),
            overwrite=get_bool_any(request, ["overwrite"], False),
            selected_item_ids=get_item_ids(request),
        )
    )


def normalize_download_response(payload: dict[str, object]) -> dict[str, object]:
    normalized = dict(payload)
    destination_path = normalized.get("destination_path")
    if destination_path:
        normalized["destination_path"] = runtime_path_to_config_text(str(destination_path))
    return normalized


def items_remove_payload(request: dict[str, Any]) -> dict[str, Any]:
    _runtime, _defaults, _user_settings, outputs_root = runtime_context()
    return remove_master_items(outputs_root, get_item_ids(request))


def items_detail_payload(request: dict[str, Any]) -> dict[str, Any]:
    item_id = get_string_any(request, ["itemId", "item_id", "threadId", "thread_id", "conversationId", "conversation_id", "id"])
    if not item_id:
        return unavailable_thread_detail("", "", "", "", "Item id is required.")
    _runtime, _defaults, _user_settings, outputs_root = runtime_context()
    try:
        item_dir = safe_child_directory(outputs_root, item_id)
    except ValueError as exc:
        return unavailable_thread_detail(item_id, str(outputs_root), "", "", str(exc))
    timeline_path = item_dir / "timeline.json"
    convert_info_path = item_dir / "convert_info.json"
    if not timeline_path.exists():
        return unavailable_thread_detail(item_id, str(item_dir), str(timeline_path), str(convert_info_path), "Thread was not found.", item_id)
    timeline = read_json_object(timeline_path)
    if timeline is None:
        return unavailable_thread_detail(item_id, str(item_dir), str(timeline_path), str(convert_info_path), "Thread could not be read.", item_id)
    messages = [
        convert_thread_message(message, index)
        for index, message in enumerate(timeline.get("messages") or [])
        if isinstance(message, dict)
    ]
    resolved_item_id = get_string_from_mapping(timeline, ["thread_id", "conversation_id", "item_id", "id"], item_id)
    title = get_string_from_mapping(timeline, ["preferred_title", "title"], resolved_item_id)
    return {
        "available": True,
        "itemId": resolved_item_id,
        "title": title,
        "createdAt": get_string_from_mapping(timeline, ["created_at", "createdAt"], ""),
        "updatedAt": get_string_from_mapping(timeline, ["updated_at", "updatedAt"], ""),
        "messageCount": len(messages),
        "messages": messages,
        "directoryPath": str(item_dir),
        "timelinePath": str(timeline_path),
        "convertInfoPath": str(convert_info_path),
        "message": "",
    }


def convert_thread_message(message: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "role": get_string_from_mapping(message, ["role", "actor"], ""),
        "createdAt": get_string_from_mapping(message, ["created_at", "createdAt"], ""),
        "text": get_string_from_mapping(message, ["text", "content"], ""),
    }


def unavailable_thread_detail(item_id: str, directory_path: str, timeline_path: str, convert_info_path: str, message: str, title: str = "") -> dict[str, Any]:
    return {
        "available": False,
        "itemId": item_id,
        "title": title,
        "createdAt": "",
        "updatedAt": "",
        "messageCount": 0,
        "messages": [],
        "directoryPath": directory_path,
        "timelinePath": timeline_path,
        "convertInfoPath": convert_info_path,
        "message": message,
    }


def safe_child_directory(root: Path, child_name: str) -> Path:
    full_root = root.expanduser().resolve()
    candidate = (full_root / child_name.replace("\\", "/").strip("/")).resolve()
    try:
        candidate.relative_to(full_root)
    except ValueError as exc:
        raise ValueError("Invalid item id.") from exc
    return candidate


def read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def get_item_ids(request: dict[str, Any]) -> list[str]:
    values = get_string_array_any(request, ["itemIds", "item_ids", "itemId", "item_id"])
    item_ids: list[str] = []
    for value in values:
        for part in value.split(","):
            stripped = part.strip()
            if stripped and stripped not in item_ids:
                item_ids.append(stripped)
    return item_ids


def get_optional_positive_int(request: dict[str, Any], names: list[str]) -> int | None:
    for name in names:
        value = get_node(request, name)
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, str):
            try:
                parsed = int(value)
            except ValueError:
                continue
            return parsed if parsed > 0 else None
    return None


def get_bool_any(request: dict[str, Any], names: list[str], fallback: bool) -> bool:
    for name in names:
        value = get_node(request, name)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
    return fallback


def get_string_any(request: dict[str, Any], names: list[str]) -> str:
    for name in names:
        value = get_node(request, name)
        if value is not None:
            text = convert_json_text(value)
            if text:
                return text
    return ""


def get_string_array_any(request: dict[str, Any], names: list[str]) -> list[str]:
    for name in names:
        value = get_node(request, name)
        if value is None:
            continue
        if isinstance(value, list):
            rows = [convert_json_text(item) for item in value if convert_json_text(item)]
        else:
            text = convert_json_text(value)
            rows = [part.strip() for part in text.replace("\r", ",").replace("\n", ",").split(",") if part.strip()]
        if rows:
            return rows
    return []


def get_string_from_mapping(source: dict[str, Any], names: list[str], fallback: str) -> str:
    for name in names:
        value = source.get(name)
        if value is not None:
            text = convert_json_text(value)
            if text:
                return text
    lowered = {key.lower(): value for key, value in source.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            text = convert_json_text(value)
            if text:
                return text
    return fallback


def get_node(request: dict[str, Any], name: str) -> Any:
    if name in request:
        return request[name]
    lowered = name.lower()
    for key, value in request.items():
        if key.lower() == lowered:
            return value
    return None


def convert_json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(value, ensure_ascii=False).strip()


def error_payload(message: str, error_type: str = "Error") -> dict[str, Any]:
    return {"ok": False, "error": {"type": error_type, "message": message}}


class TimelineForWindowsCodexApiHandler(BaseHTTPRequestHandler):
    server_version = "TimelineForWindowsCodexWorkerApi/1.0"

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _handle(self) -> None:
        try:
            request = self._read_json()
            status_code, payload = handle_request(self.command, self.path.split("?", 1)[0], request)
        except Exception as exc:
            status_code, payload = HTTPStatus.INTERNAL_SERVER_ERROR, error_payload(str(exc), exc.__class__.__name__)
        self._write_json(status_code, payload)

    def _read_json(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        if not raw.strip():
            return None
        loaded = json.loads(raw.decode("utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("JSON request body must be an object.")
        return loaded

    def _write_json(self, status_code: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status_code))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    host = os.environ.get("TIMELINE_FOR_WINDOWS_CODEX_API_BIND_HOST", "0.0.0.0")
    port = int(os.environ.get("TIMELINE_FOR_WINDOWS_CODEX_API_BIND_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), TimelineForWindowsCodexApiHandler)
    print(f"TimelineForWindowsCodex worker API listening on http://{host}:{port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
