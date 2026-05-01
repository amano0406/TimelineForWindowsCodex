from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .contracts import RefreshRequest, ThreadSelection
from .fs_utils import ensure_dir, now_iso, read_json, write_json_atomic
from .parse_sessions import (
    parse_thread_transcript_entries,
    resolve_thread_session_path,
)
from .timeline import (
    THREAD_CONVERT_FILE_NAME,
    THREAD_FINAL_FILE_NAME,
    build_thread_convert_payload,
    build_thread_conversation_payload,
    export_thread_dir_name,
)

PARSER_VERSION = 2
RENDER_CONTRACT_VERSION = 3
THREAD_CACHE_SCHEMA_VERSION = 2


def process_refresh(request: RefreshRequest, outputs_root: Path) -> dict[str, object]:
    """Refresh the fixed master artifact root.

    The master root is intentionally not a run database. It only stores the
    latest normalized item artifacts under <master>/<thread_id>/.
    """

    ensure_dir(outputs_root)
    started = time.perf_counter()
    completed_at = now_iso()
    rows: list[dict[str, object]] = []
    update_counts = {
        "new": 0,
        "changed": 0,
        "unchanged": 0,
        "missing": 0,
        "degraded": 0,
    }
    total_messages = 0
    total_attachments = 0
    reused_thread_count = 0
    rendered_thread_count = 0

    for thread in request.selected_threads:
        thread_started = time.perf_counter()
        row = refresh_thread_item(
            request=request,
            thread=thread,
            outputs_root=outputs_root,
            converted_at=completed_at,
        )
        row["processing_duration_ms"] = round((time.perf_counter() - thread_started) * 1000.0, 3)
        rows.append(row)

        status = str(row.get("update_status") or "changed")
        if status not in update_counts:
            status = "changed"
        update_counts[status] += 1
        if row.get("cache_status") == "unchanged":
            reused_thread_count += 1
        else:
            rendered_thread_count += 1
        total_messages += int(row.get("message_count") or 0)
        total_attachments += int(row.get("attachment_count") or 0)

    return {
        "schema_version": 1,
        "refresh_id": request.refresh_id,
        "state": "completed",
        "master_root": str(outputs_root),
        "completed_at": completed_at,
        "thread_count": len(rows),
        "item_count": len(rows),
        "message_count": total_messages,
        "attachment_count": total_attachments,
        "reused_thread_count": reused_thread_count,
        "rendered_thread_count": rendered_thread_count,
        "processing_mode": "incremental_reuse" if reused_thread_count else "full_rebuild",
        "update_counts": update_counts,
        "processing_duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "items": sorted(rows, key=lambda item: str(item.get("thread_id") or "")),
    }


def refresh_thread_item(
    *,
    request: RefreshRequest,
    thread: ThreadSelection,
    outputs_root: Path,
    converted_at: str,
) -> dict[str, object]:
    resolved_session_path = resolve_thread_session_path(thread)
    if resolved_session_path is not None:
        thread.session_path = str(resolved_session_path)

    source_fingerprint = _file_fingerprint(resolved_session_path)
    source_type = _source_type_from_path(resolved_session_path)
    cache_key = build_thread_cache_key(request, thread, source_fingerprint)
    export_thread_dir = export_thread_dir_name(thread.thread_id)
    item_dir = ensure_dir(outputs_root / export_thread_dir)
    thread_path = item_dir / THREAD_FINAL_FILE_NAME
    convert_path = item_dir / THREAD_CONVERT_FILE_NAME
    legacy_convert_path = item_dir / "convert.json"
    existed_before = thread_path.exists() or convert_path.exists()

    existing_convert = _read_optional_json(convert_path)
    if (
        _convert_cache_key(existing_convert) == cache_key
        and thread_path.exists()
        and convert_path.exists()
    ):
        thread_payload = read_json(thread_path)
        return {
            "thread_id": thread.thread_id,
            "title": _payload_title(thread_payload, thread),
            "update_status": "unchanged",
            "cache_status": "unchanged",
            "source_type": source_type,
            "source_session_path": str(resolved_session_path) if resolved_session_path is not None else "",
            "message_count": _message_count(existing_convert, thread_payload),
            "attachment_count": _attachment_count(existing_convert, thread_payload),
            "thread_path": str(thread_path),
            "convert_info_path": str(convert_path),
            "cache_key": cache_key,
        }

    transcript_entries = parse_thread_transcript_entries(
        thread,
        redaction_profile=request.redaction_profile,
        include_compaction_recovery=request.include_compaction_recovery,
    )
    limitations = _build_thread_limitations(
        resolved_session_path=resolved_session_path,
        transcript_entries=transcript_entries,
    )
    thread_payload = build_thread_conversation_payload(
        thread=thread,
        transcript_rows=transcript_entries,
        limitations=limitations,
    )
    convert_payload = build_thread_convert_payload(
        thread=thread,
        transcript_rows=transcript_entries,
        source_fingerprint=source_fingerprint,
        source_type=source_type,
        limitations=limitations,
        cache_key=cache_key,
        parser_version=PARSER_VERSION,
        render_contract_version=RENDER_CONTRACT_VERSION,
    )
    convert_payload["converted_at"] = converted_at
    convert_payload["thread_path"] = str(thread_path)

    write_json_atomic(thread_path, thread_payload)
    write_json_atomic(convert_path, convert_payload)
    if legacy_convert_path.exists() and legacy_convert_path != convert_path:
        legacy_convert_path.unlink()

    status = "changed" if existed_before else "new"
    return {
        "thread_id": thread.thread_id,
        "title": _payload_title(thread_payload, thread),
        "update_status": status,
        "cache_status": "rendered",
        "source_type": source_type,
        "source_session_path": str(resolved_session_path) if resolved_session_path is not None else "",
        "message_count": len(transcript_entries),
        "attachment_count": _attachment_count(convert_payload, thread_payload),
        "thread_path": str(thread_path),
        "convert_info_path": str(convert_path),
        "cache_key": cache_key,
        "known_gaps": limitations,
    }


def build_download_archive(
    outputs_root: Path,
    destination_root: Path,
    *,
    overwrite: bool,
    selected_item_ids: list[str] | None = None,
) -> dict[str, object]:
    rows = collect_master_items(outputs_root, selected_item_ids or [])
    if not rows:
        raise FileNotFoundError(f"No master items were found. Run items refresh first: {outputs_root}")

    ensure_dir(destination_root)
    archive_path = destination_root / f"TimelineForWindowsCodex-export-{_timestamp_for_filename()}.zip"
    if archive_path.exists() and not overwrite:
        raise ValueError(f"Destination already exists. Pass --overwrite to replace it: {archive_path}")

    readme_text = render_download_readme(rows)
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("README.md", readme_text)
        for row in rows:
            item_dir_name = str(row["item_dir_name"])
            archive.write(Path(str(row["convert_info_path"])), f"items/{item_dir_name}/{THREAD_CONVERT_FILE_NAME}")
            archive.write(Path(str(row["thread_path"])), f"items/{item_dir_name}/{THREAD_FINAL_FILE_NAME}")

    return {
        "schema_version": 1,
        "state": "completed",
        "destination_path": str(archive_path),
        "master_root": str(outputs_root),
        "thread_count": len(rows),
        "item_count": len(rows),
        "message_count": sum(int(row.get("message_count") or 0) for row in rows),
        "attachment_count": sum(int(row.get("attachment_count") or 0) for row in rows),
        "items": rows,
    }


def collect_master_items(outputs_root: Path, selected_item_ids: list[str] | None = None) -> list[dict[str, object]]:
    if not outputs_root.exists():
        return []

    normalized_selection = {
        value.strip().casefold()
        for selected_id in selected_item_ids or []
        for value in str(selected_id).split(",")
        if value.strip()
    }
    rows: list[dict[str, object]] = []
    for item_dir in sorted(path for path in outputs_root.iterdir() if path.is_dir()):
        convert_path = item_dir / THREAD_CONVERT_FILE_NAME
        thread_path = item_dir / THREAD_FINAL_FILE_NAME
        if not convert_path.exists() or not thread_path.exists():
            continue
        payload = _read_optional_json(convert_path)
        thread_id = str(payload.get("thread_id") or item_dir.name)
        if normalized_selection and thread_id.casefold() not in normalized_selection and item_dir.name.casefold() not in normalized_selection:
            continue
        thread_payload = _read_optional_json(thread_path)
        rows.append(
            {
                "thread_id": thread_id,
                "item_dir_name": item_dir.name,
                "title": _payload_title(thread_payload, ThreadSelection(thread_id=thread_id, preferred_title=thread_id)),
                "message_count": _message_count(payload, thread_payload),
                "attachment_count": _attachment_count(payload, thread_payload),
                "convert_info_path": str(convert_path),
                "thread_path": str(thread_path),
            }
        )

    if normalized_selection:
        found = {str(row["thread_id"]).casefold() for row in rows} | {str(row["item_dir_name"]).casefold() for row in rows}
        missing = sorted(item for item in normalized_selection if item not in found)
        if missing:
            raise ValueError(f"Unknown item ids in master: {', '.join(missing)}")
    return rows


def render_download_readme(rows: list[dict[str, object]]) -> str:
    message_count = sum(int(row.get("message_count") or 0) for row in rows)
    return "\n".join(
        [
            "# TimelineForWindowsCodex Export",
            "",
            "This package was generated by TimelineForWindowsCodex.",
            "",
            "It contains normalized Windows Codex thread items converted from local Codex Desktop history.",
            "",
            f"- Item count: {len(rows)}",
            f"- Message count: {message_count}",
            "",
            "## Layout",
            "",
            "- `items/<thread_id>/convert_info.json`: conversion metadata",
            "- `items/<thread_id>/thread.json`: normalized user/assistant/system messages",
            "",
        ]
    )


def build_thread_cache_key(
    request: RefreshRequest,
    thread: ThreadSelection,
    source_fingerprint: dict[str, object] | None,
) -> str:
    payload = {
        "schema_version": THREAD_CACHE_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "render_contract_version": RENDER_CONTRACT_VERSION,
        "request": {
            "include_compaction_recovery": request.include_compaction_recovery,
            "redaction_profile": request.redaction_profile,
        },
        "thread": {
            "thread_id": thread.thread_id,
            "preferred_title": thread.preferred_title,
            "observed_thread_names": [item.to_dict() for item in thread.observed_thread_names],
            "source_root_kind": thread.source_root_kind,
            "session_path": thread.session_path,
            "updated_at": thread.updated_at,
            "cwd": thread.cwd,
            "first_user_message_excerpt": thread.first_user_message_excerpt,
        },
        "source": _source_fingerprint_for_cache(source_fingerprint),
    }
    return _stable_payload_sha256(payload)


def _build_thread_limitations(
    *,
    resolved_session_path: Path | None,
    transcript_entries: list[dict[str, object]],
) -> list[str]:
    rows: list[str] = []
    if resolved_session_path is None:
        rows.append("Source file could not be resolved for this thread.")
        return rows

    if resolved_session_path.suffix.lower() == ".json":
        rows.append("Archived thread_reads source is in use. Rich item coverage may be incomplete.")

    if not transcript_entries:
        rows.append("No transcript messages were available for the selected filters.")

    if any(
        isinstance(entry.get("attachments"), list) and entry.get("attachments")
        for entry in transcript_entries
    ):
        rows.append("Attachment labels were preserved, but binary attachment contents were not exported.")

    if any(str(entry.get("source") or "") == "compaction_replacement_history" for entry in transcript_entries):
        rows.append(
            "Some transcript messages were recovered from compaction replacement_history. "
            "Their timestamps are compaction observation times, not original send times."
        )

    return rows


def _file_fingerprint(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.exists() or not path.is_file():
        return None

    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _sha256(path),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_type_from_path(path: Path | None) -> str:
    if path is None:
        return "missing"
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return "session_jsonl"
    if suffix == ".json":
        return "thread_read_json"
    return "unknown"


def _source_fingerprint_for_cache(
    source_fingerprint: dict[str, object] | None,
) -> dict[str, object] | None:
    if source_fingerprint is None:
        return None

    return {
        "size_bytes": source_fingerprint.get("size_bytes"),
        "sha256": source_fingerprint.get("sha256"),
    }


def _stable_payload_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _convert_cache_key(payload: dict[str, object]) -> str:
    conversion = payload.get("conversion")
    if isinstance(conversion, dict):
        return str(conversion.get("cache_key") or "")
    return ""


def _read_optional_json(path: Path) -> dict[str, object]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = read_json(path)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _message_count(convert_payload: dict[str, object], thread_payload: dict[str, object]) -> int:
    value = convert_payload.get("message_count")
    if value is None and isinstance(convert_payload.get("counts"), dict):
        value = dict(convert_payload["counts"]).get("message_count")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        messages = thread_payload.get("messages") if isinstance(thread_payload, dict) else []
        return len(messages) if isinstance(messages, list) else 0


def _attachment_count(convert_payload: dict[str, object], thread_payload: dict[str, object]) -> int:
    value = convert_payload.get("attachment_count")
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    messages = thread_payload.get("messages") if isinstance(thread_payload, dict) else []
    if not isinstance(messages, list):
        return 0
    return sum(
        len(message.get("attachments") or [])
        for message in messages
        if isinstance(message, dict) and isinstance(message.get("attachments"), list)
    )


def _payload_title(thread_payload: dict[str, object], thread: ThreadSelection) -> str:
    title = str(thread_payload.get("title") or "").strip()
    return title or thread.preferred_title or thread.thread_id


def _timestamp_for_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
