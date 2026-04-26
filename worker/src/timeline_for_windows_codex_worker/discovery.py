from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .contracts import ObservedThreadName, ThreadSelection
from .parse_sessions import normalize_local_path, sanitize_text

_SESSION_RECORD_START_RE = re.compile(r'^\{"timestamp":')
_SESSION_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


@dataclass
class MutableThread:
    thread_id: str
    preferred_title: str
    observed_thread_names: list[ObservedThreadName] = field(default_factory=list)
    source_root_path: str = ""
    source_root_kind: str = ""
    session_path: str = ""
    updated_at: str | None = None
    cwd: str | None = None
    first_user_message_excerpt: str | None = None
    priority: int = 1_000_000


def discover_threads(
    primary_root_path: str,
    backup_root_paths: Iterable[str],
    include_archived_sources: bool = True,
) -> list[ThreadSelection]:
    roots = _build_roots(primary_root_path, backup_root_paths)
    threads: dict[str, MutableThread] = {}

    for root_path, root_kind, priority in roots:
        _merge_session_index(root_path, root_kind, priority, threads)
        _merge_state_catalog(root_path, root_kind, priority, threads)
        _merge_session_files(root_path, root_kind, priority, threads, include_archived_sources)
        if include_archived_sources:
            _merge_thread_read_files(root_path, root_kind, priority, threads)

    rows = [
        ThreadSelection(
            thread_id=thread.thread_id,
            preferred_title=thread.preferred_title or thread.thread_id,
            observed_thread_names=list(thread.observed_thread_names),
            source_root_path=thread.source_root_path,
            source_root_kind=thread.source_root_kind,
            session_path=thread.session_path,
            updated_at=thread.updated_at,
            cwd=thread.cwd,
            first_user_message_excerpt=thread.first_user_message_excerpt,
        )
        for thread in threads.values()
    ]

    return sorted(
        rows,
        key=lambda item: (
            _parse_updated_at(item.updated_at),
            (item.preferred_title or item.thread_id).casefold(),
        ),
        reverse=True,
    )


def _build_roots(
    primary_root_path: str,
    backup_root_paths: Iterable[str],
) -> list[tuple[Path, str, int]]:
    roots: list[tuple[Path, str, int]] = []
    seen: set[str] = set()

    def add_root(raw_path: str, kind: str, priority: int) -> None:
        if not raw_path.strip():
            return
        normalized = normalize_local_path(raw_path.strip()).resolve()
        key = str(normalized).casefold()
        if key in seen or not normalized.exists():
            return
        seen.add(key)
        roots.append((normalized, kind, priority))

    add_root(primary_root_path, "primary", 0)
    for index, raw_path in enumerate(backup_root_paths, start=1):
        add_root(raw_path, f"backup_{index}", index)

    return roots


def _merge_session_index(
    root_path: Path,
    root_kind: str,
    priority: int,
    threads: dict[str, MutableThread],
) -> None:
    session_index_path = root_path / "session_index.jsonl"
    if not session_index_path.exists():
        return

    for raw_line in session_index_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw_line.strip():
            continue

        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        thread_id = str(payload.get("id") or "").strip()
        if not thread_id:
            continue

        updated_at = str(payload.get("updated_at") or "").strip() or None
        observed_name = sanitize_text(
            str(payload.get("thread_name") or ""),
            profile="strict",
            max_length=120,
        )

        thread = _get_or_create(thread_id, root_path, root_kind, priority, threads)
        _add_observed_thread_name(thread, observed_name, updated_at, "session_index.jsonl")
        if updated_at and _parse_updated_at(updated_at) >= _parse_updated_at(thread.updated_at):
            thread.updated_at = updated_at


def _merge_state_catalog(
    root_path: Path,
    root_kind: str,
    priority: int,
    threads: dict[str, MutableThread],
) -> None:
    state_database_path = root_path / "state_5.sqlite"
    if not state_database_path.exists():
        return

    try:
        connection = sqlite3.connect(f"file:{state_database_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return

    with connection:
        try:
            cursor = connection.execute(
                """
                SELECT
                    id,
                    rollout_path,
                    updated_at,
                    cwd,
                    first_user_message
                FROM threads
                """
            )
        except sqlite3.Error:
            return

        for row in cursor:
            thread_id = str(row[0] or "").strip()
            if not thread_id:
                continue

            rollout_path = str(row[1] or "").strip()
            updated_at = _to_iso_from_unix(row[2]) if row[2] is not None else None
            cwd = str(row[3] or "").strip() or None
            first_user_message = sanitize_text(
                str(row[4] or ""),
                profile="strict",
                max_length=240,
            ) or None

            thread = _get_or_create(thread_id, root_path, root_kind, priority, threads)

            if (not thread.session_path or not Path(thread.session_path).exists()) and rollout_path:
                thread.source_root_path = str(root_path)
                thread.source_root_kind = root_kind
                thread.session_path = rollout_path
                thread.priority = min(thread.priority, priority)

            if not thread.cwd and cwd:
                thread.cwd = cwd
            if not thread.first_user_message_excerpt and first_user_message:
                thread.first_user_message_excerpt = first_user_message
            if updated_at and _parse_updated_at(updated_at) >= _parse_updated_at(thread.updated_at):
                thread.updated_at = updated_at


def _merge_session_files(
    root_path: Path,
    root_kind: str,
    priority: int,
    threads: dict[str, MutableThread],
    include_archived_sources: bool,
) -> None:
    paths: list[Path] = []
    sessions_root = root_path / "sessions"
    if sessions_root.exists():
        paths.extend(sorted(sessions_root.rglob("*.jsonl")))

    archived_sessions_root = root_path / "archived_sessions"
    if include_archived_sources and archived_sessions_root.exists():
        paths.extend(sorted(archived_sessions_root.glob("*.jsonl")))

    seen: set[str] = set()
    for session_path in paths:
        key = str(session_path).casefold()
        if key in seen:
            continue
        seen.add(key)

        preview = _read_session_preview(session_path)
        thread_id = preview.get("thread_id")
        if not thread_id:
            continue

        thread = _get_or_create(str(thread_id), root_path, root_kind, priority, threads)
        if priority < thread.priority or not thread.session_path or not Path(thread.session_path).exists():
            thread.source_root_path = str(root_path)
            thread.source_root_kind = root_kind
            thread.session_path = str(session_path)
            thread.priority = priority
            thread.cwd = thread.cwd or preview.get("cwd")
            thread.first_user_message_excerpt = (
                thread.first_user_message_excerpt or preview.get("first_user_message_excerpt")
            )

        updated_at = preview.get("updated_at") or _to_iso_from_datetime(
            datetime.fromtimestamp(session_path.stat().st_mtime, timezone.utc)
        )
        if updated_at and _parse_updated_at(str(updated_at)) >= _parse_updated_at(thread.updated_at):
            thread.updated_at = str(updated_at)

        if not thread.preferred_title:
            thread.preferred_title = thread.thread_id


def _merge_thread_read_files(
    root_path: Path,
    root_kind: str,
    priority: int,
    threads: dict[str, MutableThread],
) -> None:
    for thread_read_root in _enumerate_thread_read_roots(root_path):
        for thread_read_path in sorted(thread_read_root.glob("*.json")):
            preview = _read_thread_read_preview(thread_read_path)
            thread_id = preview.get("thread_id")
            if not thread_id:
                continue

            thread = _get_or_create(str(thread_id), root_path, root_kind, priority, threads)
            if priority < thread.priority or not thread.session_path or not Path(thread.session_path).exists():
                thread.source_root_path = str(root_path)
                thread.source_root_kind = root_kind
                thread.session_path = str(thread_read_path)
                thread.priority = priority

            observed_name = sanitize_text(
                str(preview.get("name") or ""),
                profile="strict",
                max_length=120,
            )
            _add_observed_thread_name(thread, observed_name, preview.get("updated_at"), "thread_reads")

            if not thread.cwd and preview.get("cwd"):
                thread.cwd = str(preview["cwd"])
            if not thread.first_user_message_excerpt and preview.get("first_user_message_excerpt"):
                thread.first_user_message_excerpt = str(preview["first_user_message_excerpt"])
            if preview.get("updated_at") and _parse_updated_at(str(preview["updated_at"])) >= _parse_updated_at(
                thread.updated_at
            ):
                thread.updated_at = str(preview["updated_at"])


def _get_or_create(
    thread_id: str,
    root_path: Path,
    root_kind: str,
    priority: int,
    threads: dict[str, MutableThread],
) -> MutableThread:
    if thread_id not in threads:
        threads[thread_id] = MutableThread(
            thread_id=thread_id,
            preferred_title=thread_id,
            source_root_path=str(root_path),
            source_root_kind=root_kind,
            priority=priority,
        )
    return threads[thread_id]


def _add_observed_thread_name(
    thread: MutableThread,
    raw_name: str | None,
    observed_at: str | None,
    source: str,
) -> None:
    if not raw_name or not raw_name.strip():
        return

    name = raw_name.strip()
    if any(
        item.name == name and item.observed_at == observed_at and item.source == source
        for item in thread.observed_thread_names
    ):
        return

    thread.observed_thread_names.append(
        ObservedThreadName(name=name, observed_at=observed_at, source=source)
    )

    if (
        not thread.preferred_title
        or thread.preferred_title == thread.thread_id
        or _parse_updated_at(observed_at) >= _parse_updated_at(thread.updated_at)
    ):
        thread.preferred_title = name


def _read_session_preview(session_path: Path) -> dict[str, str | None]:
    thread_id: str | None = None
    updated_at: str | None = None
    cwd: str | None = None
    first_user_message_excerpt: str | None = None

    for payload_root in _iter_session_jsonl_payload_roots(session_path):
        item_type = str(payload_root.get("type") or "")
        payload = payload_root.get("payload") or {}
        if not isinstance(payload, dict):
            continue

        if item_type == "session_meta":
            thread_id = str(payload.get("id") or "").strip() or thread_id
            cwd = str(payload.get("cwd") or "").strip() or cwd
            updated_at = str(payload.get("timestamp") or "").strip() or updated_at
        elif item_type == "event_msg" and str(payload.get("type") or "") == "user_message":
            first_user_message_excerpt = sanitize_text(
                str(payload.get("message") or ""),
                profile="strict",
                max_length=240,
            ) or first_user_message_excerpt

        if thread_id and first_user_message_excerpt:
            break

    if not thread_id:
        match = _SESSION_ID_RE.search(session_path.name)
        if match:
            thread_id = match.group(0)

    return {
        "thread_id": thread_id,
        "updated_at": updated_at,
        "cwd": cwd,
        "first_user_message_excerpt": first_user_message_excerpt,
    }


def _iter_session_jsonl_payload_roots(session_path: Path) -> Iterable[dict[str, Any]]:
    buffer: list[str] = []
    for raw_line in session_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw_line.strip():
            continue

        if buffer and _SESSION_RECORD_START_RE.match(raw_line):
            payload_root = _try_load_session_payload_root("\n".join(buffer))
            if payload_root is not None:
                yield payload_root
            buffer = [raw_line]
            payload_root = _try_load_session_payload_root(raw_line)
            if payload_root is not None:
                yield payload_root
                buffer = []
            continue

        buffer.append(raw_line)
        payload_root = _try_load_session_payload_root("\n".join(buffer))
        if payload_root is not None:
            yield payload_root
            buffer = []

    if buffer:
        payload_root = _try_load_session_payload_root("\n".join(buffer))
        if payload_root is not None:
            yield payload_root


def _try_load_session_payload_root(raw_text: str) -> dict[str, Any] | None:
    try:
        payload_root = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    return payload_root if isinstance(payload_root, dict) else None


def _enumerate_thread_read_roots(root_path: Path) -> list[Path]:
    candidates = [
        root_path / "thread_reads",
        root_path / "_codex_tools" / "thread_reads",
    ]
    if root_path.name.lower() == "thread_reads":
        candidates.append(root_path)

    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key in seen or not candidate.exists():
            continue
        seen.add(key)
        roots.append(candidate)
    return roots


def _read_thread_read_preview(thread_read_path: Path) -> dict[str, str | None]:
    try:
        payload_root = json.loads(thread_read_path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload_root, dict):
        return {}

    thread = _try_get_thread_read_thread(payload_root)
    if not isinstance(thread, dict):
        return {}

    thread_id = str(thread.get("id") or "").strip() or None
    preview = str(thread.get("preview") or "").strip()
    name = str(thread.get("name") or "").strip() or None
    updated_at = _to_iso_from_unknown(thread.get("updatedAt"))
    cwd = str(thread.get("cwd") or "").strip() or None
    first_user_message_excerpt = (
        sanitize_text(preview, profile="strict", max_length=240)
        if preview
        else _extract_first_user_excerpt(thread)
    )

    return {
        "thread_id": thread_id,
        "name": name,
        "updated_at": updated_at,
        "cwd": cwd,
        "first_user_message_excerpt": first_user_message_excerpt,
    }


def _try_get_thread_read_thread(payload_root: dict[str, Any]) -> dict[str, Any]:
    result = payload_root.get("result")
    if isinstance(result, dict):
        thread = result.get("thread")
        if isinstance(thread, dict):
            return thread

    thread = payload_root.get("thread")
    if isinstance(thread, dict):
        return thread

    return {}


def _extract_first_user_excerpt(thread: dict[str, Any]) -> str | None:
    turns = thread.get("turns")
    if not isinstance(turns, list):
        return None

    for turn in turns:
        if not isinstance(turn, dict):
            continue
        items = turn.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or str(item.get("type") or "") != "userMessage":
                continue

            content = item.get("content")
            if not isinstance(content, list):
                continue
            parts = [
                str(content_item.get("text") or "")
                for content_item in content
                if isinstance(content_item, dict)
            ]
            combined = " ".join(part for part in parts if part.strip())
            excerpt = sanitize_text(combined, profile="strict", max_length=240)
            if excerpt:
                return excerpt

    return None


def _parse_updated_at(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _to_iso_from_unknown(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return _to_iso_from_unix(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return _to_iso_from_datetime(parsed)
    return None


def _to_iso_from_unix(value: Any) -> str:
    return _to_iso_from_datetime(datetime.fromtimestamp(int(value), timezone.utc))


def _to_iso_from_datetime(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")
