from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .contracts import ThreadSelection

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s)\]>]+", re.IGNORECASE)
_PASSWORD_RE = re.compile(r"(?i)(password\s*[:=]\s*)\S+")
_TOKEN_RE = re.compile(r"(?i)(token\s*[:=]\s*)\S+")
_KEY_RE = re.compile(r"(?i)(api[_ -]?key\s*[:=]\s*)\S+")
_WHITESPACE_RE = re.compile(r"\s+")
_WINDOWS_PATH_RE = re.compile(r"^(?P<drive>[A-Za-z]):[\\/](?P<rest>.*)$")
_SESSION_RECORD_START_RE = re.compile(r'^\{"timestamp":')


def sanitize_text(raw_text: str | None, *, profile: str = "strict", max_length: int = 2000) -> str:
    if not raw_text:
        return ""

    text = raw_text.replace("\r", " ").replace("\n", " ").strip()
    text = _apply_redaction(text, profile=profile)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text[: max_length - 3] + "..." if len(text) > max_length else text


def sanitize_multiline_text(raw_text: str | None, *, profile: str = "strict", max_length: int = 8000) -> str:
    if not raw_text:
        return ""

    text = _normalize_raw_text(raw_text).strip()
    text = _apply_redaction(text, profile=profile)
    return text[: max_length - 3] + "..." if len(text) > max_length else text


def _apply_redaction(text: str, *, profile: str) -> str:
    if profile == "none":
        return text

    text = _EMAIL_RE.sub("[email]", text)
    text = _URL_RE.sub("[url]", text)

    if profile == "strict":
        text = _PASSWORD_RE.sub(r"\1[redacted]", text)
        text = _TOKEN_RE.sub(r"\1[redacted]", text)
        text = _KEY_RE.sub(r"\1[redacted]", text)

    return text


def _extract_text_from_message_payload(payload: dict[str, Any], *, profile: str) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if item_type in {"output_text", "input_text"}:
            parts.append(str(item.get("text") or ""))
    return sanitize_text(" ".join(parts), profile=profile, max_length=2400)


def _extract_reasoning_summary(payload: dict[str, Any], *, profile: str) -> str:
    summary = payload.get("summary")
    if not isinstance(summary, list):
        return ""

    parts: list[str] = []
    for item in summary:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") == "summary_text":
            parts.append(str(item.get("text") or ""))
    return sanitize_text(" ".join(parts), profile=profile, max_length=1200)


def _classify_tool(name: str) -> str:
    lowered = name.lower()
    if lowered in {"exec_command", "write_stdin", "shell_command"}:
        return "terminal"
    if lowered in {"apply_patch"}:
        return "file_edit"
    if lowered.startswith("browser_") or "playwright" in lowered:
        return "browser"
    if lowered.startswith("mcp__"):
        return "mcp"
    return "tool"


def normalize_local_path(raw_path: str) -> Path:
    match = _WINDOWS_PATH_RE.match(raw_path.strip())
    if not match:
        return Path(raw_path)

    drive = match.group("drive").lower()
    rest = match.group("rest").replace("\\", "/")
    return Path(f"/mnt/{drive}/{rest}")


def resolve_thread_session_path(thread: ThreadSelection) -> Path | None:
    normalized_session_path = normalize_local_path(thread.session_path)
    if thread.session_path.strip() and normalized_session_path.is_file():
        return normalized_session_path

    source_root = normalize_local_path(thread.source_root_path)
    if not source_root.exists():
        return None

    for candidate_root, pattern in _candidate_source_roots(source_root, thread.thread_id):
        if not candidate_root.exists():
            continue

        for candidate in sorted(candidate_root.rglob(pattern)):
            if candidate.is_file():
                return candidate

    return normalized_session_path if normalized_session_path.is_file() else None


def parse_thread_events(
    thread: ThreadSelection,
    *,
    include_tool_outputs: bool,
    redaction_profile: str,
) -> list[dict[str, Any]]:
    source_path = resolve_thread_session_path(thread)
    if source_path is None:
        return []

    if source_path.suffix.lower() == ".json":
        return _parse_thread_read_events(
            source_path,
            thread,
            redaction_profile=redaction_profile,
        )

    return _parse_session_jsonl_events(
        source_path,
        thread,
        include_tool_outputs=include_tool_outputs,
        redaction_profile=redaction_profile,
    )


def parse_thread_transcript_entries(
    thread: ThreadSelection,
    *,
    redaction_profile: str,
    include_compaction_recovery: bool,
) -> list[dict[str, Any]]:
    source_path = resolve_thread_session_path(thread)
    if source_path is None:
        return []

    if source_path.suffix.lower() == ".json":
        return _parse_thread_read_transcript_entries(
            source_path,
            thread,
            redaction_profile=redaction_profile,
        )

    return _parse_session_jsonl_transcript_entries(
        source_path,
        thread,
        redaction_profile=redaction_profile,
        include_compaction_recovery=include_compaction_recovery,
    )


def parse_thread_environment_observations(
    thread: ThreadSelection,
) -> list[dict[str, Any]]:
    source_path = resolve_thread_session_path(thread)
    if source_path is None:
        return []

    if source_path.suffix.lower() == ".json":
        return _parse_thread_read_environment_observations(
            source_path,
            thread,
        )

    return _parse_session_jsonl_environment_observations(
        source_path,
        thread,
    )


def _candidate_source_roots(source_root: Path, thread_id: str) -> list[tuple[Path, str]]:
    roots: list[tuple[Path, str]] = [
        (source_root / "sessions", f"*{thread_id}*.jsonl"),
        (source_root / "archived_sessions", f"*{thread_id}*.jsonl"),
    ]

    if source_root.name.lower() == "sessions":
        roots.append((source_root, f"*{thread_id}*.jsonl"))
    if source_root.name.lower() == "archived_sessions":
        roots.append((source_root, f"*{thread_id}*.jsonl"))

    for candidate in [
        source_root / "thread_reads",
        source_root / "_codex_tools" / "thread_reads",
    ]:
        roots.append((candidate, f"{thread_id}.json"))

    if source_root.name.lower() == "thread_reads":
        roots.append((source_root, f"{thread_id}.json"))

    deduped: list[tuple[Path, str]] = []
    seen: set[tuple[str, str]] = set()
    for candidate_root, pattern in roots:
        key = (str(candidate_root), pattern)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((candidate_root, pattern))
    return deduped


def _iter_session_jsonl_payload_roots(
    session_path: Path,
    *,
    include_compacted: bool = False,
    include_diagnostics: bool = False,
) -> Iterator[dict[str, Any]]:
    buffer: list[str] = []

    with session_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            raw_line = raw_line.rstrip("\n")
            if not raw_line.strip():
                continue

            # Compaction records can contain a very large replacement_history. Avoid
            # materializing that JSON unless a deep compaction recovery run asked for it.
            if not include_compacted and _SESSION_RECORD_START_RE.match(raw_line) and _is_compacted_record_line(raw_line):
                if buffer:
                    payload_root = _try_load_session_payload_root("\n".join(buffer))
                    if payload_root is not None:
                        yield payload_root
                    buffer = []
                continue

            if not include_diagnostics and _SESSION_RECORD_START_RE.match(raw_line) and _is_diagnostic_record_line(raw_line):
                if buffer:
                    payload_root = _try_load_session_payload_root("\n".join(buffer))
                    if payload_root is not None:
                        yield payload_root
                    buffer = []
                continue

            # Some Codex logs include raw multi-line tool output inside a JSON string.
            # When that happens, keep appending until the record becomes valid, or drop the
            # malformed buffered record once the next clear record start is encountered.
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


def _is_compacted_record_line(raw_line: str) -> bool:
    return '"type":"compacted"' in raw_line or '"type": "compacted"' in raw_line


def _is_diagnostic_record_line(raw_line: str) -> bool:
    diagnostic_types = (
        '"type":"reasoning"',
        '"type": "reasoning"',
        '"type":"function_call"',
        '"type": "function_call"',
        '"type":"custom_tool_call"',
        '"type": "custom_tool_call"',
        '"type":"function_call_output"',
        '"type": "function_call_output"',
        '"type":"custom_tool_call_output"',
        '"type": "custom_tool_call_output"',
    )
    is_response_item = '"type":"response_item"' in raw_line or '"type": "response_item"' in raw_line
    return is_response_item and any(item in raw_line for item in diagnostic_types)


def _try_load_session_payload_root(raw_text: str) -> dict[str, Any] | None:
    try:
        payload_root = json.loads(raw_text)
    except json.JSONDecodeError:
        return None
    return payload_root if isinstance(payload_root, dict) else None


def _parse_session_jsonl_events(
    session_path: Path,
    thread: ThreadSelection,
    *,
    include_tool_outputs: bool,
    redaction_profile: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sequence = 0

    for payload_root in _iter_session_jsonl_payload_roots(
        session_path,
        include_diagnostics=include_tool_outputs,
    ):
        timestamp = payload_root.get("timestamp")
        item_type = str(payload_root.get("type") or "")
        payload = payload_root.get("payload") or {}
        if not isinstance(payload, dict):
            continue

        event: dict[str, Any] | None = None

        if item_type == "session_meta":
            cwd = sanitize_text(
                str(payload.get("cwd") or ""),
                profile=redaction_profile,
                max_length=400,
            )
            event = {
                "timestamp": timestamp,
                "sequence": sequence,
                "thread_id": thread.thread_id,
                "actor": "system",
                "kind": "session_meta",
                "phase": "meta",
                "cwd": cwd,
                "text": sanitize_text(
                    f"cwd={payload.get('cwd') or ''} cli={payload.get('cli_version') or ''} source={payload.get('source') or ''}",
                    profile=redaction_profile,
                    max_length=400,
                ),
            }
        elif item_type == "event_msg":
            event_type = str(payload.get("type") or "")
            if event_type == "user_message":
                event = {
                    "timestamp": timestamp,
                    "sequence": sequence,
                    "thread_id": thread.thread_id,
                    "actor": "user",
                    "kind": "message",
                    "phase": "conversation",
                    "text": sanitize_text(
                        str(payload.get("message") or ""),
                        profile=redaction_profile,
                    ),
                }
            elif event_type == "agent_message":
                event = {
                    "timestamp": timestamp,
                    "sequence": sequence,
                    "thread_id": thread.thread_id,
                    "actor": "assistant",
                    "kind": "message",
                    "phase": str(payload.get("phase") or "conversation"),
                    "text": sanitize_text(
                        str(payload.get("message") or ""),
                        profile=redaction_profile,
                    ),
                }
            elif event_type in {"task_started", "task_complete"}:
                event = {
                    "timestamp": timestamp,
                    "sequence": sequence,
                    "thread_id": thread.thread_id,
                    "actor": "system",
                    "kind": event_type,
                    "phase": "lifecycle",
                    "text": sanitize_text(
                        json.dumps(payload, ensure_ascii=False),
                        profile=redaction_profile,
                        max_length=500,
                    ),
                }
            elif event_type == "token_count":
                total_usage = ((payload.get("info") or {}).get("total_token_usage") or {})
                event = {
                    "timestamp": timestamp,
                    "sequence": sequence,
                    "thread_id": thread.thread_id,
                    "actor": "system",
                    "kind": "token_count",
                    "phase": "metrics",
                    "text": sanitize_text(
                        " ".join(
                            [
                                f"input={total_usage.get('input_tokens', 0)}",
                                f"output={total_usage.get('output_tokens', 0)}",
                                f"reasoning={total_usage.get('reasoning_output_tokens', 0)}",
                                f"total={total_usage.get('total_tokens', 0)}",
                            ]
                        ),
                        profile=redaction_profile,
                        max_length=240,
                    ),
                }
        elif item_type == "response_item":
            response_type = str(payload.get("type") or "")
            if response_type == "reasoning":
                summary = _extract_reasoning_summary(payload, profile=redaction_profile)
                if summary:
                    event = {
                        "timestamp": timestamp,
                        "sequence": sequence,
                        "thread_id": thread.thread_id,
                        "actor": "assistant",
                        "kind": "reasoning",
                        "phase": str(payload.get("phase") or "commentary"),
                        "text": summary,
                    }
            elif response_type in {"function_call", "custom_tool_call"}:
                tool_name = str(payload.get("name") or payload.get("tool_name") or "tool")
                event = {
                    "timestamp": timestamp,
                    "sequence": sequence,
                    "thread_id": thread.thread_id,
                    "actor": "tool",
                    "kind": "tool_call",
                    "phase": str(payload.get("phase") or "tooling"),
                    "tool_name": tool_name,
                    "tool_family": _classify_tool(tool_name),
                    "call_id": payload.get("call_id"),
                    "text": sanitize_text(
                        str(payload.get("arguments") or payload.get("input") or ""),
                        profile=redaction_profile,
                        max_length=1600,
                    ),
                }
            elif include_tool_outputs and response_type in {
                "function_call_output",
                "custom_tool_call_output",
            }:
                call_id = str(payload.get("call_id") or "")
                event = {
                    "timestamp": timestamp,
                    "sequence": sequence,
                    "thread_id": thread.thread_id,
                    "actor": "tool",
                    "kind": "tool_output",
                    "phase": str(payload.get("phase") or "tooling"),
                    "call_id": call_id,
                    "text": sanitize_text(
                        str(payload.get("output") or payload.get("content") or ""),
                        profile=redaction_profile,
                        max_length=1800,
                    ),
                }
        if event and event.get("text"):
            sequence += 1
            event["sequence"] = sequence
            rows.append(event)

    return rows


def _parse_session_jsonl_transcript_entries(
    session_path: Path,
    thread: ThreadSelection,
    *,
    redaction_profile: str,
    include_compaction_recovery: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sequence = 0
    current_mode: str | None = None
    normal_keys: set[tuple[str, str, tuple[str, ...]]] = set()
    seen_recovered_keys: set[tuple[str, str, tuple[str, ...]]] = set()

    for payload_root in _iter_session_jsonl_payload_roots(
        session_path,
        include_compacted=include_compaction_recovery,
        include_diagnostics=False,
    ):
        timestamp = payload_root.get("timestamp")
        item_type = str(payload_root.get("type") or "")
        payload = payload_root.get("payload") or {}
        if not isinstance(payload, dict):
            continue

        if item_type == "turn_context":
            collaboration_mode = payload.get("collaboration_mode")
            if isinstance(collaboration_mode, dict):
                current_mode = str(collaboration_mode.get("mode") or "").strip().lower() or None
            continue

        if item_type == "compacted" and include_compaction_recovery:
            compacted_rows, sequence = _extract_compaction_transcript_rows(
                payload,
                thread,
                timestamp=timestamp,
                redaction_profile=redaction_profile,
                start_sequence=sequence,
                skip_keys=normal_keys,
                seen_recovered_keys=seen_recovered_keys,
            )
            rows.extend(compacted_rows)
            continue

        if item_type == "response_item":
            response_type = str(payload.get("type") or "")
            role = str(payload.get("role") or "").strip().lower()
            if response_type == "message" and role in {"user", "assistant"}:
                raw_text, attachments = _extract_response_message_transcript_parts(payload)
                if _should_skip_transcript_message(role, raw_text):
                    continue
                if raw_text or attachments:
                    dedupe_key = _make_transcript_dedupe_key(role, raw_text, attachments)
                    normal_keys.add(dedupe_key)
                    sequence += 1
                    rows.append(
                        {
                            "timestamp": timestamp,
                            "sequence": sequence,
                            "thread_id": thread.thread_id,
                            "actor": role,
                            "phase": str(payload.get("phase") or "conversation"),
                            "mode": current_mode if role == "user" else None,
                            "text": sanitize_multiline_text(raw_text, profile=redaction_profile),
                            "attachments": attachments,
                            "_dedupe_key": dedupe_key,
                        }
                    )
                continue

        if item_type == "event_msg":
            event_type = str(payload.get("type") or "")
            if event_type in {"user_message", "agent_message"}:
                role = "user" if event_type == "user_message" else "assistant"
                raw_text = str(payload.get("message") or "")
                attachments = _extract_event_message_attachments(payload)
                dedupe_key = _make_transcript_dedupe_key(role, raw_text, attachments)
                normal_keys.add(dedupe_key)
                sequence += 1
                rows.append(
                    {
                        "timestamp": timestamp,
                        "sequence": sequence,
                        "thread_id": thread.thread_id,
                        "actor": role,
                        "phase": str(payload.get("phase") or "conversation"),
                        "mode": current_mode if event_type == "user_message" else None,
                        "text": sanitize_multiline_text(raw_text, profile=redaction_profile),
                        "attachments": attachments,
                        "_dedupe_key": dedupe_key,
                    }
                )

    return _dedupe_transcript_rows(
        sorted(
            [
                row
                for row in rows
                if not _is_compaction_recovered_row(row) or _transcript_row_key(row) not in normal_keys
            ],
            key=lambda row: (
                str(row.get("timestamp") or ""),
                1 if _is_compaction_recovered_row(row) else 0,
                int(row.get("sequence") or 0),
            ),
        )
    )


def _extract_compaction_transcript_rows(
    payload: dict[str, Any],
    thread: ThreadSelection,
    *,
    timestamp: Any,
    redaction_profile: str,
    start_sequence: int,
    skip_keys: set[tuple[str, str, tuple[str, ...]]],
    seen_recovered_keys: set[tuple[str, str, tuple[str, ...]]],
) -> tuple[list[dict[str, Any]], int]:
    replacement_history = payload.get("replacement_history")
    if not isinstance(replacement_history, list):
        return [], start_sequence

    rows: list[dict[str, Any]] = []
    sequence = start_sequence
    for item in replacement_history:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "message":
            continue

        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue

        raw_text, attachments = _extract_response_message_transcript_parts(item)
        if _should_skip_transcript_message(role, raw_text):
            continue
        if not raw_text and not attachments:
            continue
        key = _make_transcript_dedupe_key(role, raw_text, attachments)
        if key in skip_keys or key in seen_recovered_keys:
            continue
        seen_recovered_keys.add(key)

        sequence += 1
        rows.append(
            {
                "timestamp": timestamp,
                "sequence": sequence,
                "thread_id": thread.thread_id,
                "actor": role,
                "phase": str(item.get("phase") or "conversation"),
                "mode": None,
                "text": sanitize_multiline_text(raw_text, profile=redaction_profile),
                "attachments": attachments,
                "source": "compaction_replacement_history",
                "timestamp_kind": "compaction_observed_at",
                "_dedupe_key": key,
            }
        )

    return rows, sequence


def _dedupe_transcript_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normal_keys = {
        _transcript_row_key(row)
        for row in rows
        if not _is_compaction_recovered_row(row)
    }
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    deduped: list[dict[str, Any]] = []

    for row in rows:
        key = _transcript_row_key(row)
        if _is_compaction_recovered_row(row) and key in normal_keys:
            continue
        if key in seen:
            continue
        seen.add(key)
        cleaned_row = dict(row)
        cleaned_row.pop("_dedupe_key", None)
        deduped.append(cleaned_row)

    for index, row in enumerate(deduped, start=1):
        row["sequence"] = index
    return deduped


def _transcript_row_key(row: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    dedupe_key = row.get("_dedupe_key")
    if (
        isinstance(dedupe_key, tuple)
        and len(dedupe_key) == 3
        and isinstance(dedupe_key[0], str)
        and isinstance(dedupe_key[1], str)
        and isinstance(dedupe_key[2], tuple)
    ):
        return dedupe_key

    attachments = row.get("attachments") or []
    normalized_attachments = tuple(
        str(item or "").strip()
        for item in attachments
        if str(item or "").strip()
    ) if isinstance(attachments, list) else ()
    return (
        str(row.get("actor") or "").strip().lower(),
        _normalize_raw_text(str(row.get("text") or "")).strip(),
        normalized_attachments,
    )


def _make_transcript_dedupe_key(
    actor: str,
    raw_text: str,
    attachments: list[str],
) -> tuple[str, str, tuple[str, ...]]:
    normalized_text = _normalize_raw_text(raw_text).strip()
    text_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    normalized_attachments = tuple(
        str(item or "").strip()
        for item in attachments
        if str(item or "").strip()
    )
    return (actor.strip().lower(), text_hash, normalized_attachments)


def _is_compaction_recovered_row(row: dict[str, Any]) -> bool:
    return str(row.get("source") or "") == "compaction_replacement_history"


def _parse_session_jsonl_environment_observations(
    session_path: Path,
    thread: ThreadSelection,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for payload_root in _iter_session_jsonl_payload_roots(session_path):
        timestamp = payload_root.get("timestamp")
        item_type = str(payload_root.get("type") or "")
        payload = payload_root.get("payload") or {}
        if not isinstance(payload, dict):
            continue

        if item_type == "session_meta":
            runtime_payload = {
                "cli_version": str(payload.get("cli_version") or payload.get("cliVersion") or "").strip(),
                "originator": str(payload.get("originator") or "").strip(),
                "source": str(payload.get("source") or "").strip(),
                "model_provider": str(payload.get("model_provider") or payload.get("modelProvider") or "").strip(),
            }
            if any(runtime_payload.values()):
                rows.append(
                    {
                        "timestamp": timestamp,
                        "thread_id": thread.thread_id,
                        "thread_name": thread.preferred_title,
                        "session_path": str(session_path),
                        "kind": "client_runtime",
                        "fingerprint": _fingerprint_payload(runtime_payload),
                        **runtime_payload,
                    }
                )
            continue

        if item_type != "turn_context":
            continue

        turn_id = str(payload.get("turn_id") or "").strip() or None
        user_instructions = _normalize_raw_text(str(payload.get("user_instructions") or ""))
        if user_instructions.strip():
            rows.append(
                {
                    "timestamp": timestamp,
                    "thread_id": thread.thread_id,
                    "thread_name": thread.preferred_title,
                    "session_path": str(session_path),
                    "turn_id": turn_id,
                    "kind": "custom_instruction",
                    "fingerprint": _fingerprint_text(user_instructions),
                    "text": user_instructions,
                }
            )

        collaboration_mode = payload.get("collaboration_mode")
        collaboration_settings = collaboration_mode.get("settings") if isinstance(collaboration_mode, dict) else {}
        if not isinstance(collaboration_settings, dict):
            collaboration_settings = {}

        model_profile = {
            "model": str(payload.get("model") or collaboration_settings.get("model") or "").strip(),
            "reasoning_effort": str(
                collaboration_settings.get("reasoning_effort")
                or payload.get("effort")
                or ""
            ).strip(),
            "personality": str(payload.get("personality") or "").strip(),
            "collaboration_mode": str(
                (collaboration_mode or {}).get("mode") if isinstance(collaboration_mode, dict) else ""
            ).strip(),
        }
        if any(model_profile.values()):
            rows.append(
                {
                    "timestamp": timestamp,
                    "thread_id": thread.thread_id,
                    "thread_name": thread.preferred_title,
                    "session_path": str(session_path),
                    "turn_id": turn_id,
                    "kind": "model_profile",
                    "fingerprint": _fingerprint_payload(model_profile),
                    **model_profile,
                }
            )

    return rows


def _parse_thread_read_events(
    source_path: Path,
    thread: ThreadSelection,
    *,
    redaction_profile: str,
) -> list[dict[str, Any]]:
    payload_root = json.loads(source_path.read_text(encoding="utf-8", errors="replace"))
    thread_payload = _extract_thread_read_thread(payload_root)
    if not isinstance(thread_payload, dict):
        return []

    base_timestamp = _coerce_timestamp(
        thread_payload.get("createdAt"),
        fallback=thread_payload.get("updatedAt"),
    )
    sequence = 0
    rows: list[dict[str, Any]] = []

    def append_event(event: dict[str, Any] | None) -> None:
        nonlocal sequence
        if not event:
            return

        sequence += 1
        timestamp = _offset_timestamp(base_timestamp, sequence - 1)
        event["timestamp"] = timestamp
        event["sequence"] = sequence
        event["thread_id"] = thread.thread_id
        if event.get("text"):
            rows.append(event)

    append_event(
        {
            "actor": "system",
            "kind": "session_meta",
            "phase": "meta",
            "cwd": sanitize_text(
                str(thread_payload.get("cwd") or ""),
                profile=redaction_profile,
                max_length=400,
            ),
            "text": sanitize_text(
                " ".join(
                    [
                        f"cwd={thread_payload.get('cwd') or ''}",
                        f"cli={thread_payload.get('cliVersion') or ''}",
                        f"source={thread_payload.get('source') or ''}",
                        f"path={thread_payload.get('path') or ''}",
                    ]
                ),
                profile=redaction_profile,
                max_length=400,
            ),
        }
    )

    turns = thread_payload.get("turns")
    if not isinstance(turns, list):
        return rows

    for turn in turns:
        if not isinstance(turn, dict):
            continue
        items = turn.get("items")
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            if item_type in {"userMessage", "user_message"}:
                raw_text, attachments = _extract_thread_read_message_parts(item)
                append_event(
                    {
                        "actor": "user",
                        "kind": "message",
                        "phase": "conversation",
                        "text": sanitize_text(
                            raw_text or _format_attachment_summary(attachments),
                            profile=redaction_profile,
                        ),
                    }
                )
            elif item_type in {"agentMessage", "assistantMessage", "assistant_message"}:
                raw_text, attachments = _extract_thread_read_message_parts(item)
                append_event(
                    {
                        "actor": "assistant",
                        "kind": "message",
                        "phase": str(item.get("phase") or "conversation"),
                        "text": sanitize_text(
                            raw_text or _format_attachment_summary(attachments),
                            profile=redaction_profile,
                        ),
                    }
                )
            elif item_type == "reasoning":
                append_event(
                    {
                        "actor": "assistant",
                        "kind": "reasoning",
                        "phase": "commentary",
                        "text": sanitize_text(
                            _extract_thread_read_reasoning_text(item),
                            profile=redaction_profile,
                            max_length=1200,
                        ),
                    }
                )
            elif item_type == "plan":
                append_event(
                    {
                        "actor": "assistant",
                        "kind": "plan",
                        "phase": "planning",
                        "text": sanitize_text(
                            str(item.get("text") or ""),
                            profile=redaction_profile,
                            max_length=2400,
                        ),
                    }
                )
            elif item_type == "contextCompaction":
                append_event(
                    {
                        "actor": "system",
                        "kind": "context_compaction",
                        "phase": "compaction",
                        "text": "Context compacted.",
                    }
                )

    return rows


def _parse_thread_read_transcript_entries(
    source_path: Path,
    thread: ThreadSelection,
    *,
    redaction_profile: str,
) -> list[dict[str, Any]]:
    payload_root = json.loads(source_path.read_text(encoding="utf-8", errors="replace"))
    thread_payload = _extract_thread_read_thread(payload_root)
    if not isinstance(thread_payload, dict):
        return []

    base_timestamp = _coerce_timestamp(
        thread_payload.get("createdAt"),
        fallback=thread_payload.get("updatedAt"),
    )
    sequence = 0
    rows: list[dict[str, Any]] = []

    def append_entry(entry: dict[str, Any] | None) -> None:
        nonlocal sequence
        if not entry:
            return

        timestamp = _offset_timestamp(base_timestamp, sequence)
        sequence += 1
        entry["timestamp"] = timestamp
        entry["sequence"] = sequence
        entry["thread_id"] = thread.thread_id
        rows.append(entry)

    turns = thread_payload.get("turns")
    if not isinstance(turns, list):
        return rows

    for turn in turns:
        if not isinstance(turn, dict):
            continue
        items = turn.get("items")
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            item_type = str(item.get("type") or "")
            if item_type in {"userMessage", "user_message"}:
                raw_text, attachments = _extract_thread_read_message_parts(item)
                if raw_text or attachments:
                    append_entry(
                        {
                            "actor": "user",
                            "phase": "conversation",
                            "mode": None,
                            "text": sanitize_multiline_text(raw_text, profile=redaction_profile),
                            "attachments": attachments,
                        }
                    )
            elif item_type in {"agentMessage", "assistantMessage", "assistant_message"}:
                raw_text, attachments = _extract_thread_read_message_parts(item)
                if raw_text or attachments:
                    append_entry(
                        {
                            "actor": "assistant",
                            "phase": str(item.get("phase") or "conversation"),
                            "mode": None,
                            "text": sanitize_multiline_text(raw_text, profile=redaction_profile),
                            "attachments": attachments,
                        }
                    )

    return rows


def _parse_thread_read_environment_observations(
    source_path: Path,
    thread: ThreadSelection,
) -> list[dict[str, Any]]:
    payload_root = json.loads(source_path.read_text(encoding="utf-8", errors="replace"))
    thread_payload = _extract_thread_read_thread(payload_root)
    if not isinstance(thread_payload, dict):
        return []

    timestamp = _coerce_timestamp(
        thread_payload.get("createdAt"),
        fallback=thread_payload.get("updatedAt"),
    )
    runtime_payload = {
        "cli_version": str(thread_payload.get("cliVersion") or "").strip(),
        "originator": "",
        "source": str(thread_payload.get("source") or "").strip(),
        "model_provider": str(thread_payload.get("modelProvider") or "").strip(),
    }
    if not any(runtime_payload.values()):
        return []

    return [
        {
            "timestamp": timestamp,
            "thread_id": thread.thread_id,
            "thread_name": thread.preferred_title,
            "session_path": str(source_path),
            "kind": "client_runtime",
            "fingerprint": _fingerprint_payload(runtime_payload),
            **runtime_payload,
        }
    ]


def _extract_thread_read_thread(payload_root: dict[str, Any]) -> dict[str, Any]:
    result = payload_root.get("result")
    if isinstance(result, dict):
        thread = result.get("thread")
        if isinstance(thread, dict):
            return thread

    thread = payload_root.get("thread")
    if isinstance(thread, dict):
        return thread

    return payload_root if isinstance(payload_root, dict) else {}


def _extract_thread_read_user_text(item: dict[str, Any]) -> str:
    return _extract_thread_read_message_parts(item)[0]


def _extract_thread_read_reasoning_text(item: dict[str, Any]) -> str:
    summary = item.get("summary")
    if not isinstance(summary, list):
        return ""

    parts: list[str] = []
    for summary_item in summary:
        if isinstance(summary_item, str):
            parts.append(summary_item)
        elif isinstance(summary_item, dict) and isinstance(summary_item.get("text"), str):
            parts.append(str(summary_item.get("text") or ""))
    return " ".join(parts)


def _extract_response_message_transcript_parts(payload: dict[str, Any]) -> tuple[str, list[str]]:
    content = payload.get("content")
    if not isinstance(content, list):
        return "", []

    text_parts: list[str] = []
    attachments: list[str] = []

    for item in content:
        if not isinstance(item, dict):
            continue

        item_type = str(item.get("type") or "")
        if item_type in {"input_text", "output_text"}:
            text = str(item.get("text") or "")
            if text.strip() in {"<image>", "<file>"}:
                continue
            text_parts.append(text)
            continue

        attachment_label = _extract_attachment_label(item)
        if attachment_label:
            attachments.append(attachment_label)

    return _normalize_raw_text("".join(text_parts)), attachments


def _extract_event_message_attachments(payload: dict[str, Any]) -> list[str]:
    attachments: list[str] = []

    images = payload.get("images")
    if isinstance(images, list):
        attachments.extend(_extract_attachment_label({"type": "input_image", "image_url": image}) for image in images)

    local_images = payload.get("local_images")
    if isinstance(local_images, list):
        for image in local_images:
            attachments.append(_file_label_from_unknown_payload(image, fallback="image attached"))

    text_elements = payload.get("text_elements")
    if isinstance(text_elements, list):
        for element in text_elements:
            label = _file_label_from_unknown_payload(element, fallback="text element attached")
            if label:
                attachments.append(label)

    return [item for item in attachments if item]


def _extract_thread_read_message_parts(item: dict[str, Any]) -> tuple[str, list[str]]:
    content = item.get("content")
    text_parts: list[str] = []
    attachments: list[str] = []

    if isinstance(content, list):
        for content_item in content:
            if not isinstance(content_item, dict):
                continue

            item_type = str(content_item.get("type") or "")
            if item_type in {"text", "input_text", "output_text"} or isinstance(content_item.get("text"), str):
                text = str(content_item.get("text") or "")
                if text.strip() not in {"", "<image>", "<file>"}:
                    text_parts.append(text)

            attachment_label = _extract_attachment_label(content_item)
            if attachment_label:
                attachments.append(attachment_label)

    if not text_parts and isinstance(item.get("text"), str):
        fallback_text = str(item.get("text") or "")
        if fallback_text.strip() and fallback_text.strip() not in {"<image>", "<file>"}:
            text_parts.append(fallback_text)

    attachments.extend(_extract_event_message_attachments(item))

    raw_attachments = item.get("attachments")
    if isinstance(raw_attachments, list):
        for raw_attachment in raw_attachments:
            attachments.append(_file_label_from_unknown_payload(raw_attachment, fallback="file attached"))

    return _normalize_raw_text("".join(text_parts)), _dedupe_labels(attachments)


def _dedupe_labels(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for label in labels:
        normalized = str(label or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        rows.append(normalized)
    return rows


def _format_attachment_summary(attachments: list[str]) -> str:
    if not attachments:
        return ""
    return "Attachments: " + ", ".join(attachments)


def _extract_thread_read_attachments(item: dict[str, Any]) -> list[str]:
    return _extract_thread_read_message_parts(item)[1]


def _extract_attachment_label(item: dict[str, Any]) -> str:
    item_type = str(item.get("type") or "")
    if item_type in {"input_image", "image_url", "local_image"}:
        return _file_label_from_unknown_payload(item, fallback="image attached")
    if item_type in {"input_file", "local_file", "file"}:
        return _file_label_from_unknown_payload(item, fallback="file attached")
    return ""


def _file_label_from_unknown_payload(value: Any, *, fallback: str) -> str:
    if isinstance(value, str):
        return _file_label_from_string(value, fallback=fallback)

    if not isinstance(value, dict):
        return fallback

    for key in ("filename", "file_name", "name", "path", "file_path", "local_path"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return _file_label_from_string(candidate, fallback=fallback)

    image_url = value.get("image_url")
    if isinstance(image_url, str) and image_url.strip():
        return _file_label_from_string(image_url, fallback=fallback)

    return fallback


def _file_label_from_string(value: str, *, fallback: str) -> str:
    text = value.strip()
    if not text:
        return fallback

    if text.startswith("data:image/"):
        return "image attached"
    if text.startswith("data:"):
        return fallback

    normalized = text.replace("\\", "/").rstrip("/")
    if "/" in normalized:
        leaf = normalized.rsplit("/", 1)[-1]
        return leaf or fallback
    return normalized


def _normalize_raw_text(raw_text: str | None) -> str:
    if not raw_text:
        return ""
    return raw_text.replace("\r\n", "\n").replace("\r", "\n")


def _fingerprint_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _fingerprint_payload(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _fingerprint_text(serialized)


def _should_skip_transcript_message(role: str, raw_text: str) -> bool:
    if role != "user":
        return False

    text = raw_text.lstrip()
    if text.startswith("# AGENTS.md instructions for "):
        return True
    if "<INSTRUCTIONS>" in text and "Global Operating Rules" in text:
        return True
    return False


def _coerce_timestamp(value: Any, *, fallback: Any = None) -> str | None:
    for candidate in (value, fallback):
        if isinstance(candidate, (int, float)):
            return datetime.fromtimestamp(float(candidate), tz=timezone.utc).isoformat().replace("+00:00", "Z")
        if isinstance(candidate, str) and candidate.strip():
            text = candidate.strip()
            if text.isdigit():
                return datetime.fromtimestamp(float(text), tz=timezone.utc).isoformat().replace("+00:00", "Z")
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            except ValueError:
                continue
    return None


def _offset_timestamp(base_timestamp: str | None, offset_seconds: int) -> str | None:
    if not base_timestamp:
        return None
    try:
        base_dt = datetime.fromisoformat(base_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return base_timestamp
    return (base_dt + timedelta(seconds=offset_seconds)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
