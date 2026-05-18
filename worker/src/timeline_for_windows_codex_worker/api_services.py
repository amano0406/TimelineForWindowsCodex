from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .contracts import ThreadSelection
from .settings import RuntimeDefaults
from .settings import UserSettings

DEFAULT_ITEMS_LIST_PAGE_SIZE = 100
ITEMS_LIST_SORT_FIELDS = ["updated_at", "created_at", "thread_id"]


def thread_selection_to_item(thread: ThreadSelection) -> dict[str, object]:
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


def sort_item_rows(items: list[Any]) -> list[dict[str, object]]:
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


def resolve_pagination(page: int | None, page_size: int | None, total_count: int) -> dict[str, object]:
    effective_page = int(page or 1)
    effective_page_size = int(page_size or DEFAULT_ITEMS_LIST_PAGE_SIZE)
    if effective_page < 1:
        raise ValueError("page must be 1 or greater.")
    if effective_page_size < 1:
        raise ValueError("page_size must be 1 or greater.")

    offset = (effective_page - 1) * effective_page_size
    range_end = min(offset + effective_page_size, total_count)
    total_pages = (total_count + effective_page_size - 1) // effective_page_size if total_count else 0
    return {
        "mode": "page",
        "page": effective_page,
        "page_size": effective_page_size,
        "total_items": total_count,
        "total_pages": total_pages,
        "offset": offset,
        "range_start": offset + 1 if offset < total_count else 0,
        "range_end": range_end,
        "has_previous": effective_page > 1 and total_count > 0,
        "has_next": effective_page < total_pages,
    }


def resolve_source_roots(defaults: RuntimeDefaults) -> tuple[str, list[str]]:
    return defaults.primary_source_root, [
        item.strip() for item in defaults.backup_source_roots or [] if item.strip()
    ]


def effective_outputs_root(runtime_outputs_root: Path, user_settings: UserSettings) -> Path:
    configured = (user_settings.output_root or "").strip()
    if configured:
        return config_path_to_runtime_path(configured)
    return runtime_outputs_root


def resolve_destination_root(value: str) -> Path:
    normalized = value.strip()
    if normalized.casefold() == "desktop":
        if os.name == "nt":
            return Path.home() / "Desktop"
        return Path("/mnt/c/Users/amano/Desktop")
    return config_path_to_runtime_path(normalized)


def config_path_to_runtime_path(value: str) -> Path:
    raw = value.strip()
    if os.name != "nt" and is_windows_drive_path(raw):
        drive = raw[0].lower()
        rest = raw[3:].replace("\\", "/")
        return Path(f"/mnt/{drive}/{rest}").resolve()
    return Path(raw).expanduser().resolve()


def runtime_path_to_config_text(value: str | Path) -> str:
    raw = str(value or "").strip()
    if os.name == "nt" or not raw:
        return raw

    normalized = raw.replace("\\", "/")
    if len(normalized) >= 7 and normalized.startswith("/mnt/") and normalized[5].isalpha() and normalized[6] == "/":
        drive = normalized[5].upper()
        rest = normalized[7:].replace("/", "\\")
        return f"{drive}:\\{rest}" if rest else f"{drive}:\\"
    return raw


def is_windows_drive_path(value: str) -> bool:
    return len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"} and value[0].isalpha()


def select_threads(
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
