from __future__ import annotations

from collections import Counter
from typing import Any

from .contracts import ThreadSelection
from .fs_utils import slugify


def build_segments(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not events:
        return []

    segments: list[dict[str, Any]] = []
    current_events: list[dict[str, Any]] = []
    current_bucket: str | None = None

    for event in events:
        bucket = _segment_bucket(event)
        if current_events and bucket != current_bucket:
            segments.append(_make_segment(len(segments) + 1, current_bucket or "misc", current_events))
            current_events = []
        current_bucket = bucket
        current_events.append(event)

    if current_events:
        segments.append(_make_segment(len(segments) + 1, current_bucket or "misc", current_events))

    return segments


def render_thread_timeline(
    thread: ThreadSelection,
    events: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> str:
    lines = [
        f"# {thread.preferred_title or thread.thread_id}",
        "",
        f"- Thread ID: `{thread.thread_id}`",
        f"- Source: `{thread.source_root_kind}`",
        f"- Session: `{thread.session_path}`",
        f"- Updated At: `{thread.updated_at or ''}`",
        f"- CWD: `{thread.cwd or ''}`",
        f"- Events: `{len(events)}`",
        f"- Segments: `{len(segments)}`",
        "",
    ]

    if thread.first_user_message_excerpt:
        lines.extend(["## First prompt", "", thread.first_user_message_excerpt, ""])

    if not events:
        lines.extend(["## Timeline", "", "No events were available for the selected filters.", ""])
        return "\n".join(lines).strip() + "\n"

    lines.extend(["## Timeline", ""])
    for segment in segments:
        lines.append(f"### {segment['label']}")
        lines.append("")
        for event in segment["events"]:
            lines.append(_render_event_line(event))
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_timeline_index(job_id: str, thread_rows: list[dict[str, Any]]) -> str:
    lines = [
        f"# {job_id}",
        "",
        "## Thread timelines",
        "",
    ]
    for row in thread_rows:
        lines.append(
            f"- `{row['thread_id']}` {row['preferred_title']} -> `{row['timeline_path']}` ({row['event_count']} events)"
        )
    lines.append("")
    return "\n".join(lines)


def render_handoff_md(job_id: str, thread_rows: list[dict[str, Any]], total_events: int, total_segments: int) -> str:
    lines = [
        f"# windowscodex2timeline handoff {job_id}",
        "",
        f"- Thread count: `{len(thread_rows)}`",
        f"- Event count: `{total_events}`",
        f"- Segment count: `{total_segments}`",
        "",
        "## Threads",
        "",
    ]
    for row in thread_rows:
        lines.extend(
            [
                f"### {row['preferred_title']}",
                "",
                f"- Thread ID: `{row['thread_id']}`",
                f"- Events: `{row['event_count']}`",
                f"- Segments: `{row['segment_count']}`",
                f"- Timeline: `{row['timeline_path']}`",
                f"- Source: `{row['source_root_kind']}`",
                f"- CWD: `{row.get('cwd') or ''}`",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def export_timeline_name(preferred_title: str, thread_id: str) -> str:
    return f"{slugify(preferred_title) or slugify(thread_id)}.md"


def _segment_bucket(event: dict[str, Any]) -> str:
    kind = str(event.get("kind") or "")
    if kind in {"message", "reasoning"}:
        return "conversation"
    if kind in {"tool_call", "tool_output"}:
        return str(event.get("tool_family") or "tooling")
    return "system"


def _make_segment(index: int, bucket: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    label = _segment_label(bucket, events)
    return {
        "segment_id": f"seg-{index:03d}",
        "bucket": bucket,
        "label": label,
        "started_at": events[0].get("timestamp"),
        "ended_at": events[-1].get("timestamp"),
        "event_count": len(events),
        "events": events,
    }


def _segment_label(bucket: str, events: list[dict[str, Any]]) -> str:
    if bucket == "conversation":
        actors = Counter(str(event.get("actor") or "unknown") for event in events)
        actors_label = ", ".join(sorted(actors.keys()))
        return f"Conversation block ({actors_label})"
    if bucket == "terminal":
        return "Terminal block"
    if bucket == "file_edit":
        return "File edit block"
    if bucket == "browser":
        return "Browser block"
    if bucket == "mcp":
        return "MCP block"
    if bucket == "tooling":
        return "Tool block"
    return "System block"


def _render_event_line(event: dict[str, Any]) -> str:
    timestamp = str(event.get("timestamp") or "")
    short_time = timestamp[11:19] if len(timestamp) >= 19 else timestamp
    actor = str(event.get("actor") or "system")
    kind = str(event.get("kind") or "event")
    text = str(event.get("text") or "").strip()
    tool_name = str(event.get("tool_name") or "")

    if kind == "tool_call" and tool_name:
        return f"- {short_time} `{tool_name}` call: {text}"
    if kind == "tool_output":
        return f"- {short_time} tool output: {text}"
    if kind == "reasoning":
        return f"- {short_time} reasoning: {text}"
    return f"- {short_time} {actor}/{kind}: {text}"
