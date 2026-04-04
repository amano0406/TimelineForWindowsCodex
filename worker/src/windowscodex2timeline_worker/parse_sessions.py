from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import ThreadSelection

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s)\]>]+", re.IGNORECASE)
_PASSWORD_RE = re.compile(r"(?i)(password\s*[:=]\s*)\S+")
_TOKEN_RE = re.compile(r"(?i)(token\s*[:=]\s*)\S+")
_KEY_RE = re.compile(r"(?i)(api[_ -]?key\s*[:=]\s*)\S+")
_WHITESPACE_RE = re.compile(r"\s+")
_WINDOWS_PATH_RE = re.compile(r"^(?P<drive>[A-Za-z]):[\\/](?P<rest>.*)$")


def sanitize_text(raw_text: str | None, *, profile: str = "strict", max_length: int = 2000) -> str:
    if not raw_text:
        return ""

    text = raw_text.replace("\r", " ").replace("\n", " ").strip()
    text = _EMAIL_RE.sub("[email]", text)
    text = _URL_RE.sub("[url]", text)

    if profile == "strict":
        text = _PASSWORD_RE.sub(r"\1[redacted]", text)
        text = _TOKEN_RE.sub(r"\1[redacted]", text)
        text = _KEY_RE.sub(r"\1[redacted]", text)

    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text[: max_length - 3] + "..." if len(text) > max_length else text


def _date_key(iso_timestamp: str | None) -> str | None:
    if not iso_timestamp:
        return None
    try:
        return datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _within_date_range(
    timestamp: str | None,
    *,
    date_from: str | None,
    date_to: str | None,
) -> bool:
    if not date_from and not date_to:
        return True

    event_date = _date_key(timestamp)
    if event_date is None:
        return False
    if date_from and event_date < date_from:
        return False
    if date_to and event_date > date_to:
        return False
    return True


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

    candidate_roots = [
        source_root / "sessions",
        source_root / "archived_sessions",
    ]
    pattern = f"*{thread.thread_id}*.jsonl"

    for candidate_root in candidate_roots:
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
    date_from: str | None,
    date_to: str | None,
) -> list[dict[str, Any]]:
    session_path = resolve_thread_session_path(thread)
    if session_path is None:
        return []

    rows: list[dict[str, Any]] = []
    sequence = 0

    for raw_line in session_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw_line.strip():
            continue

        payload_root = json.loads(raw_line)
        timestamp = payload_root.get("timestamp")
        if not _within_date_range(timestamp, date_from=date_from, date_to=date_to):
            continue

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
