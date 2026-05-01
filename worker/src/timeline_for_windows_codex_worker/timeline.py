from __future__ import annotations

from typing import Any

from .contracts import ThreadSelection

THREAD_CONVERT_INFO_FILE_NAME = "convert_info.json"
THREAD_CONVERT_FILE_NAME = THREAD_CONVERT_INFO_FILE_NAME
THREAD_FINAL_FILE_NAME = "timeline.json"


def export_thread_dir_name(thread_id: str) -> str:
    return _safe_thread_id_filename(thread_id)


def build_thread_conversation_payload(
    *,
    thread: ThreadSelection,
    transcript_rows: list[dict[str, Any]],
    limitations: list[str],
) -> dict[str, Any]:
    messages = _thread_messages(transcript_rows)
    first_message_at = next((str(message.get("created_at") or "") for message in messages if message.get("created_at")), "")
    last_message_at = next(
        (
            str(message.get("created_at") or "")
            for message in reversed(messages)
            if message.get("created_at")
        ),
        "",
    )
    return {
        "schema_version": 1,
        "application": "TimelineForWindowsCodex",
        "thread_id": thread.thread_id,
        "title": thread.preferred_title or thread.thread_id,
        "created_at": first_message_at or thread.updated_at,
        "updated_at": thread.updated_at or last_message_at or first_message_at,
        "messages": messages,
    }


def build_thread_convert_payload(
    *,
    thread: ThreadSelection,
    transcript_rows: list[dict[str, Any]],
    source_fingerprint: dict[str, object] | None,
    source_type: str,
    limitations: list[str],
    cache_key: str,
    parser_version: int,
    render_contract_version: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "application": "TimelineForWindowsCodex",
        "thread_id": thread.thread_id,
        "title": thread.preferred_title or thread.thread_id,
        "source_session": {
            "type": source_type,
            **(_stable_source_fingerprint(source_fingerprint) or {}),
        },
        "source_root_path": thread.source_root_path,
        "source_root_kind": thread.source_root_kind,
        "message_count": len(transcript_rows),
        "attachment_count": sum(
            len(row.get("attachments") or [])
            for row in transcript_rows
            if isinstance(row.get("attachments"), list)
        ),
        "converted_at": None,
        "conversion": {
            "parser_version": parser_version,
            "render_contract_version": render_contract_version,
            "cache_key": cache_key,
            "redaction_note": "Content is redacted according to the active redaction profile before export.",
        },
        "known_gaps": limitations,
    }


def _normalize_message_for_item(row: dict[str, Any]) -> dict[str, Any]:
    actor = str(row.get("actor") or "").strip().lower()
    payload: dict[str, Any] = {
        "role": actor or "unknown",
        "created_at": row.get("timestamp"),
        "text": str(row.get("raw_text") or row.get("text") or ""),
    }
    mode = row.get("mode")
    if mode:
        payload["mode"] = mode
    attachments = row.get("attachments") if isinstance(row.get("attachments"), list) else []
    if attachments:
        payload["attachments"] = attachments
    source = str(row.get("source") or "").strip()
    if source:
        payload["source"] = source
    return payload


def _thread_messages(transcript_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _normalize_message_for_item(row)
        for row in sorted(transcript_rows, key=_transcript_row_sort_key)
    ]


def _transcript_row_sort_key(row: dict[str, Any]) -> tuple[str, int, str]:
    sequence = row.get("sequence")
    sequence_value = sequence if isinstance(sequence, int) else 0
    return (
        str(row.get("timestamp") or ""),
        sequence_value,
        str(row.get("actor") or ""),
    )


def _stable_source_fingerprint(source_fingerprint: dict[str, object] | None) -> dict[str, object] | None:
    if source_fingerprint is None:
        return None
    return {
        "path": source_fingerprint.get("path"),
        "size_bytes": source_fingerprint.get("size_bytes"),
        "sha256": source_fingerprint.get("sha256"),
    }


def _safe_thread_id_filename(thread_id: str) -> str:
    text = str(thread_id or "").strip()
    return text.replace("/", "_").replace("\\", "_") or "thread"
