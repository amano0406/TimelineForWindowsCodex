from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .discovery import discover_threads
from .fs_utils import now_iso
from .api_services import effective_outputs_root
from .api_services import resolve_destination_root
from .api_services import resolve_pagination
from .api_services import resolve_source_roots
from .api_services import select_threads
from .api_services import sort_item_rows
from .api_services import thread_selection_to_item
from .processor import build_download_archive
from .processor import process_refresh
from .processor import remove_master_items
from .settings import UserSettings
from .settings import load_runtime_defaults
from .settings import load_runtime_paths
from .settings import load_user_settings
from .settings import save_user_settings
from .settings import user_settings_path
from .contracts import RefreshRequest


def handle_request(method: str, path: str, request: dict[str, Any] | None) -> tuple[int, Any]:
    route = path.rstrip("/") or "/"
    if method == "GET" and route == "/health":
        return HTTPStatus.OK, True
    if method != "POST":
        return HTTPStatus.NOT_FOUND, error_payload(f"Endpoint not found: {method} {path}")

    try:
        payload = request or {}
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
    _runtime, defaults, _user_settings, _outputs_root = runtime_context()
    primary_root, backup_roots = resolve_source_roots(defaults)
    discovered = discover_threads(primary_root, backup_roots, True)
    all_items = sort_item_rows([thread_selection_to_item(thread) for thread in discovered])
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


def items_refresh_payload(request: dict[str, Any]) -> dict[str, Any]:
    _runtime, defaults, _user_settings, outputs_root = runtime_context()
    primary_root, backup_roots = resolve_source_roots(defaults)
    discovered = discover_threads(primary_root, backup_roots, True)
    selected_threads = select_threads(discovered, get_item_ids(request))
    if not selected_threads:
        raise ValueError("No threads matched the current selection.")
    refresh_id = f"refresh-{now_iso().replace(':', '').replace('-', '')[:15]}-{os.urandom(4).hex()}"
    refresh_request = RefreshRequest(
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
    result = process_refresh(refresh_request, outputs_root)
    download_to = get_string_any(request, ["downloadTo", "download_to", "to"])
    if download_to:
        result["download"] = build_download_archive(
            outputs_root,
            resolve_destination_root(download_to),
            overwrite=get_bool_any(request, ["overwrite"], False),
            selected_item_ids=get_item_ids(request),
        )
    return result


def items_download_payload(request: dict[str, Any]) -> dict[str, Any]:
    _runtime, _defaults, _user_settings, outputs_root = runtime_context()
    destination = get_string_any(request, ["to", "downloadTo", "download_to", "outputPath", "output_path"])
    if not destination:
        raise ValueError("Download destination is required.")
    return build_download_archive(
        outputs_root,
        resolve_destination_root(destination),
        overwrite=get_bool_any(request, ["overwrite"], False),
        selected_item_ids=get_item_ids(request),
    )


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
