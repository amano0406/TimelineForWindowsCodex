from __future__ import annotations

from collections import Counter
from datetime import datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from .contracts import ThreadSelection

RUN_INCLUDED_ITEMS = [
    "Per-thread raw user/assistant message chain",
    "Observed thread names from supported sources",
    "Cross-thread environment ledger",
    "ZIP bundle with readme, index, threads, and environment artifacts",
]

RUN_LIMITATION_ITEMS = [
    "Confirmed thread rename events are not reconstructed; thread names are observation points.",
    "Exact custom-instruction save timestamps are not reconstructed; only observation times are recorded.",
    "Fine-grained file edit diffs are not exported.",
    "Binary attachment contents are not exported; only attachment labels or file names are preserved when visible.",
    "Archived thread_reads coverage is limited to currently supported item types.",
]


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
    transcript_rows: list[dict[str, Any]],
) -> str:
    observed_thread_names = _dedupe_thread_name_observations(thread.observed_thread_names)
    display_name = str(thread.preferred_title or "").strip()
    lines = [
        f"# {thread.thread_id}",
        "",
        f"- Thread ID / スレッドID: `{thread.thread_id}`",
        f"- Source / ソース: `{thread.source_root_kind}`",
        f"- Session / セッション: `{thread.session_path}`",
        f"- Updated At / 更新時刻: `{thread.updated_at or ''}`",
        f"- CWD: `{thread.cwd or ''}`",
        f"- Messages / 発話数: `{len(transcript_rows)}`",
        "- Environment ledger / 環境台帳: `../environment/ledger.md`",
        "",
    ]

    if display_name and display_name != thread.thread_id:
        lines.extend(
            [
                f"- Current observed thread name / 現在の観測スレッド名: `{display_name}`",
                "",
            ]
        )

    if thread.first_user_message_excerpt:
        lines.extend(["## First prompt / 最初のプロンプト", "", thread.first_user_message_excerpt, ""])

    if observed_thread_names:
        lines.extend(
            [
                "## Thread-local system notes / スレッド内システムメモ",
                "",
                "Observed thread names from the selected sources / 選択したソースで観測したスレッド名:",
                "",
            ]
        )
        for observation in observed_thread_names:
            name = str(observation.get("name") or "")
            observed_at = _format_display_timestamp(observation.get("observed_at"))
            source = str(observation.get("source") or "").strip() or "unknown"
            suffix = " (current)" if name == display_name else ""
            lines.append(f"- `{observed_at}` | `{source}` | {name}{suffix}")
        lines.append("")
        if len(observed_thread_names) > 1:
            lines.extend(
                [
                    "These are observation points, not confirmed rename events. "
                    "これらは観測時点であり、確定した名称変更イベントではありません。",
                    "",
                ]
            )

    if not transcript_rows:
        lines.extend(
            [
                "## Transcript / 会話",
                "",
                "No transcript messages were available for the selected filters. "
                "選択した条件では会話が見つかりませんでした。",
                "",
            ]
        )
        return "\n".join(lines).strip() + "\n"

    lines.extend(["## Transcript / 会話", ""])
    for event in transcript_rows:
        lines.append(f"### {_format_display_timestamp(event.get('timestamp'))} | {_display_actor(event.get('actor'))}")
        lines.append("")
        if str(event.get("actor") or "") == "user":
            mode = str(event.get("mode") or "").strip()
            if mode:
                lines.append(f"- Mode / モード: `{mode}`")

        attachments = event.get("attachments") or []
        if isinstance(attachments, list) and attachments:
            lines.append("- Attachments / 添付ファイル:")
            for attachment in attachments:
                lines.append(f"  - {attachment}")
            lines.append("")

        text = str(event.get("raw_text") or event.get("text") or "")
        if text.strip():
            lines.append(text.rstrip())
        else:
            lines.append("_(no text)_")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_timeline_index(job_id: str, thread_rows: list[dict[str, Any]]) -> str:
    thread_count = len(thread_rows)
    message_total = sum(int(row.get("message_count") or 0) for row in thread_rows)
    lines = [
        f"# {job_id}",
        "",
        "Timeline bundle index. Start with `../readme.html` if you want the simplest entry point.",
        "このファイルはスレッド一覧です。最初は `../readme.html` を開くと分かりやすいです。",
        "",
        f"- Threads / スレッド数: `{thread_count}`",
        f"- Messages / 発話数: `{message_total}`",
        "",
        "## Bundle files / 同梱ファイル",
        "",
        "- `threads/index.md`",
        "- `readme.html`",
        "- `fidelity_report.md`",
        "- `fidelity_report.json`",
        "- `environment/ledger.md`",
        "- `environment/ledger.json`",
        "- `environment/observations.jsonl`",
        "",
        "## Thread transcripts / スレッド本文",
        "",
    ]
    for row in thread_rows:
        export_path = f"threads/{row['export_markdown_name']}"
        observed_name = str(row.get("preferred_title") or "").strip()
        observed_suffix = f" | observed name: {observed_name}" if observed_name and observed_name != row["thread_id"] else ""
        lines.append(
            f"- `{row['thread_id']}` -> `{export_path}`{observed_suffix} "
            f"({row['message_count']} messages / 発話)"
        )
    lines.append("")
    return "\n".join(lines)


def export_timeline_name(preferred_title: str, thread_id: str) -> str:
    return f"{_safe_thread_id_filename(thread_id)}.md"


def export_thread_markdown_name(preferred_title: str, thread_id: str) -> str:
    return f"{_safe_thread_id_filename(thread_id)}.md"


def render_export_readme_html(job_id: str, thread_rows: list[dict[str, Any]]) -> str:
    thread_count = len(thread_rows)
    message_total = sum(int(row.get("message_count") or 0) for row in thread_rows)
    overview_items = [
        "\n".join(
            [
                "<li>",
                '  <a href="threads/index.md">threads/index.md</a>',
                "  <div class=\"meta\">Bundle index for the exported thread histories. "
                "スレッド一覧と対応ファイルを確認できます。</div>",
                "</li>",
            ]
        ),
        "\n".join(
            [
                "<li>",
                '  <a href="environment/ledger.md">environment/ledger.md</a>',
                "  <div class=\"meta\">Cross-thread environment ledger derived from selected sessions. "
                "スレッド横断の環境変更台帳です。</div>",
                "</li>",
            ]
        ),
        "\n".join(
            [
                "<li>",
                '  <a href="fidelity_report.md">fidelity_report.md</a>',
                "  <div class=\"meta\">Run-level source coverage and known fidelity gaps. "
                "どの source を採用し、何が未収録かを確認できます。</div>",
                "</li>",
            ]
        ),
    ]

    items = []
    for row in thread_rows:
        href = f"threads/{escape(str(row['export_markdown_name']))}"
        observed_name = escape(str(row.get("preferred_title") or ""))
        updated_at = escape(str(row.get("updated_at") or ""))
        message_count = escape(str(row.get("message_count") or 0))
        thread_id = escape(str(row["thread_id"]))
        observed_name_meta = (
            f"  <div class=\"meta\">Observed thread name: {observed_name}</div>"
            if observed_name and observed_name != thread_id
            else ""
        )
        items.append(
            "\n".join(
                [
                    "<li>",
                    f'  <a href="{href}">{thread_id}</a>',
                    f"  <div class=\"meta\">File: {escape(str(row['export_markdown_name']))}</div>",
                    f"  <div class=\"meta\">Thread ID: {thread_id}</div>",
                    observed_name_meta,
                    f"  <div class=\"meta\">Messages: {message_count}</div>",
                    f"  <div class=\"meta\">Updated At: {updated_at}</div>",
                    "</li>",
                ]
            )
        )

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="ja">',
            "<head>",
            '  <meta charset="utf-8">',
            f"  <title>{escape(job_id)} - TimelineForWindowsCodex export</title>",
            "  <style>",
            "    body { font-family: 'Segoe UI', sans-serif; margin: 2rem auto; max-width: 960px; line-height: 1.6; color: #0f172a; }",
            "    h1 { margin-bottom: 0.25rem; }",
            "    p { color: #475569; }",
            "    .summary { display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin: 1.25rem 0 2rem; }",
            "    .summary-card { border: 1px solid #cbd5e1; border-radius: 16px; padding: 1rem 1.25rem; background: #f8fafc; }",
            "    .summary-label { color: #475569; font-size: 0.9rem; }",
            "    .summary-value { font-size: 1.35rem; font-weight: 700; margin-top: 0.2rem; }",
            "    ul { list-style: none; padding: 0; display: grid; gap: 1rem; }",
            "    li { border: 1px solid #cbd5e1; border-radius: 16px; padding: 1rem 1.25rem; background: #fff; }",
            "    a { font-weight: 700; color: #0f172a; text-decoration: none; }",
            "    a:hover { text-decoration: underline; }",
            "    .meta { color: #475569; font-size: 0.95rem; }",
            "  </style>",
            "</head>",
            "<body>",
            f"  <h1>{escape(job_id)}</h1>",
            "  <p>Thread transcript archive. Open a thread below to read the raw user and assistant message chain.</p>",
            "  <p>Codex の raw な会話連鎖を thread ごとに保存したアーカイブです。"
            "スレッド内の細かなファイル編集履歴は含めず、見えた会話本文を優先しています。</p>",
            "  <section class=\"summary\">",
            "    <div class=\"summary-card\"><div class=\"summary-label\">Threads / スレッド数</div>"
            f"<div class=\"summary-value\">{thread_count}</div></div>",
            "    <div class=\"summary-card\"><div class=\"summary-label\">Messages / 発話数</div>"
            f"<div class=\"summary-value\">{message_total}</div></div>",
            "    <div class=\"summary-card\"><div class=\"summary-label\">Recommended order / 開く順番</div>"
            "<div class=\"summary-value\">readme → index → thread</div></div>",
            "  </section>",
            "  <h2>Bundle files / 同梱ファイル</h2>",
            "  <ul>",
            *overview_items,
            "  </ul>",
            "  <h2>Included / 含まれるもの</h2>",
            "  <ul>",
            *[
                f"    <li><div>{escape(item)}</div></li>"
                for item in RUN_INCLUDED_ITEMS
            ],
            "  </ul>",
            "  <h2>Known gaps / 既知の欠損・未収録</h2>",
            "  <ul>",
            *[
                f"    <li><div>{escape(item)}</div></li>"
                for item in RUN_LIMITATION_ITEMS
            ],
            "  </ul>",
            "  <h2>Threads / スレッド本文</h2>",
            "  <ul>",
            *items,
            "  </ul>",
            "</body>",
            "</html>",
            "",
        ]
    )


def build_environment_ledger(observations: list[dict[str, Any]]) -> dict[str, Any]:
    grouped_rows = {
        "custom_instruction": [],
        "model_profile": [],
        "client_runtime": [],
    }
    grouped_lookup: dict[str, dict[str, dict[str, Any]]] = {
        key: {} for key in grouped_rows
    }
    prefixes = {
        "custom_instruction": "CI",
        "model_profile": "MP",
        "client_runtime": "CR",
    }

    ordered = sorted(
        observations,
        key=lambda item: (
            str(item.get("timestamp") or ""),
            str(item.get("thread_id") or ""),
            str(item.get("kind") or ""),
            str(item.get("fingerprint") or ""),
        ),
    )

    for observation in ordered:
        kind = str(observation.get("kind") or "")
        fingerprint = str(observation.get("fingerprint") or "")
        if kind not in grouped_lookup or not fingerprint:
            continue

        current = grouped_lookup[kind].get(fingerprint)
        if current is None:
            current = {
                "id": f"{prefixes[kind]}-{len(grouped_rows[kind]) + 1:03d}",
                "kind": kind,
                "fingerprint": fingerprint,
                "first_observed_at": observation.get("timestamp"),
                "last_observed_at": observation.get("timestamp"),
                "first_thread_id": observation.get("thread_id"),
                "first_thread_name": observation.get("thread_name"),
                "first_turn_id": observation.get("turn_id"),
                "observed_count": 0,
                "_thread_ids": set(),
                "_session_paths": set(),
            }

            if kind == "custom_instruction":
                current["text"] = observation.get("text") or ""
            elif kind == "model_profile":
                current.update(
                    {
                        "model": observation.get("model") or "",
                        "reasoning_effort": observation.get("reasoning_effort") or "",
                        "personality": observation.get("personality") or "",
                        "collaboration_mode": observation.get("collaboration_mode") or "",
                    }
                )
            elif kind == "client_runtime":
                current.update(
                    {
                        "cli_version": observation.get("cli_version") or "",
                        "originator": observation.get("originator") or "",
                        "source": observation.get("source") or "",
                        "model_provider": observation.get("model_provider") or "",
                    }
                )

            grouped_lookup[kind][fingerprint] = current
            grouped_rows[kind].append(current)

        current["observed_count"] = int(current["observed_count"]) + 1
        current["last_observed_at"] = observation.get("timestamp") or current["last_observed_at"]
        current["_thread_ids"].add(str(observation.get("thread_id") or ""))
        current["_session_paths"].add(str(observation.get("session_path") or ""))

    return {
        "schema_version": 1,
        "observation_count": len(ordered),
        "custom_instructions": _finalize_environment_rows(grouped_rows["custom_instruction"]),
        "model_profiles": _finalize_environment_rows(grouped_rows["model_profile"]),
        "client_runtimes": _finalize_environment_rows(grouped_rows["client_runtime"]),
    }


def render_environment_ledger_md(job_id: str, ledger: dict[str, Any]) -> str:
    lines = [
        f"# Environment ledger {job_id}",
        "",
        "This file stores cross-thread environment observations deduplicated across the selected threads.",
        "このファイルは、選択したスレッド群から重複除去した環境観測をまとめた台帳です。",
        "`first_observed_at` is the earliest time this run observed the value. "
        "It may be later than the actual save time.",
        "`first_observed_at` は今回の run が最初に観測した時刻です。実際の保存時刻より後になる場合があります。",
        "",
    ]

    _append_custom_instruction_section(lines, ledger.get("custom_instructions") or [])
    _append_model_profile_section(lines, ledger.get("model_profiles") or [])
    _append_client_runtime_section(lines, ledger.get("client_runtimes") or [])
    return "\n".join(lines).strip() + "\n"


def render_fidelity_report_md(job_id: str, report: dict[str, Any]) -> str:
    lines = [
        f"# Fidelity report {job_id}",
        "",
        "This file records the source coverage used for this run and the known fidelity gaps.",
        "このファイルは、この run で採用した source と、既知の情報欠損・未収録範囲をまとめたレポートです。",
        "",
        f"- Threads / スレッド数: `{report.get('thread_count', 0)}`",
        f"- Included source types / 採用 source 種別: `{', '.join(report.get('source_types', [])) or '-'}`",
        "",
        "## Included in this run / 今回の run に含めたもの",
        "",
    ]

    for item in report.get("included", []):
        lines.append(f"- {item}")

    lines.extend(["", "## Known gaps / 既知の欠損・未収録", ""])
    for item in report.get("limitations", []):
        lines.append(f"- {item}")

    warnings = report.get("warnings") or []
    if warnings:
        lines.extend(["", "## Run warnings / run ごとの注意", ""])
        for item in warnings:
            lines.append(f"- {item}")

    lines.extend(["", "## Per-thread source summary / スレッドごとの source 概要", ""])

    for thread in report.get("threads", []):
        lines.extend(
            [
                f"### {thread.get('thread_id', '')}",
                "",
                f"- Preferred name / 表示名: `{thread.get('preferred_title', '')}`",
                f"- Source kind / source 区分: `{thread.get('source_root_kind', '')}`",
                f"- Source type / source 種別: `{thread.get('source_type', '')}`",
                f"- Resolved path / 解決した path: `{thread.get('resolved_session_path', '')}`",
                f"- Messages / 発話数: `{thread.get('message_count', 0)}`",
                f"- Events / イベント数: `{thread.get('event_count', 0)}`",
                f"- Segments / セグメント数: `{thread.get('segment_count', 0)}`",
                f"- Observed thread names / 観測スレッド名数: `{thread.get('observed_thread_name_count', 0)}`",
                f"- Mode observed / mode 観測: `{thread.get('has_mode', False)}`",
                f"- Attachment labels / 添付ラベル数: `{thread.get('attachment_count', 0)}`",
            ]
        )
        limitations = thread.get("limitations") or []
        if limitations:
            lines.append("- Thread-specific limitations / スレッド固有の注意:")
            for item in limitations:
                lines.append(f"  - {item}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


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


def _display_actor(value: Any) -> str:
    actor = str(value or "").strip().lower()
    if actor == "user":
        return "User"
    if actor == "assistant":
        return "Assistant"
    return actor.title() or "System"


def _format_display_timestamp(value: Any) -> str:
    timestamp = str(value or "").strip()
    if not timestamp:
        return "-"
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S JST")
    except (ValueError, TypeError):
        return timestamp


def _safe_thread_id_filename(thread_id: str) -> str:
    text = str(thread_id or "").strip()
    return text.replace("/", "_").replace("\\", "_") or "thread"


def _dedupe_thread_name_observations(values: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for value in values:
        name = str(getattr(value, "name", "") or "").strip()
        observed_at = str(getattr(value, "observed_at", "") or "").strip()
        source = str(getattr(value, "source", "") or "").strip()
        if not name:
            continue
        key = (name, observed_at, source)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "name": name,
                "observed_at": observed_at,
                "source": source,
            }
        )
    rows.sort(
        key=lambda item: (
            str(item.get("observed_at") or ""),
            str(item.get("source") or ""),
            str(item.get("name") or ""),
        )
    )
    return rows


def _finalize_environment_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    finalized: list[dict[str, Any]] = []
    for row in rows:
        thread_ids = sorted(item for item in row["_thread_ids"] if item)
        session_paths = sorted(item for item in row["_session_paths"] if item)
        finalized.append(
            {
                key: value
                for key, value in row.items()
                if not key.startswith("_")
            }
            | {
                "thread_ids": thread_ids,
                "thread_count": len(thread_ids),
                "session_paths": session_paths,
                "session_count": len(session_paths),
            }
        )
    return finalized


def _append_custom_instruction_section(lines: list[str], rows: list[dict[str, Any]]) -> None:
    lines.extend(["## Custom instruction versions / カスタム指示の版", ""])
    if not rows:
        lines.extend(["No custom instruction observations were captured. 観測されたカスタム指示はありません。", ""])
        return

    for row in rows:
        lines.extend(
            [
                f"### {row['id']}",
                "",
                f"- First observed at / 最初の観測時刻: `{row.get('first_observed_at') or ''}`",
                f"- First thread ID / 最初のスレッドID: `{row.get('first_thread_id') or ''}`",
                f"- First turn ID / 最初のターンID: `{row.get('first_turn_id') or ''}`",
                f"- Observed count / 観測回数: `{row.get('observed_count') or 0}`",
                f"- Thread count / 対象スレッド数: `{row.get('thread_count') or 0}`",
                "",
                "```text",
                str(row.get("text") or ""),
                "```",
                "",
            ]
        )


def _append_model_profile_section(lines: list[str], rows: list[dict[str, Any]]) -> None:
    lines.extend(["## Model profiles / モデル設定", ""])
    if not rows:
        lines.extend(["No model profile observations were captured. 観測されたモデル設定はありません。", ""])
        return

    for row in rows:
        lines.extend(
            [
                f"### {row['id']}",
                "",
                f"- First observed at / 最初の観測時刻: `{row.get('first_observed_at') or ''}`",
                f"- Model / モデル: `{row.get('model') or ''}`",
                f"- Reasoning effort / 推論強度: `{row.get('reasoning_effort') or ''}`",
                f"- Personality / 性格: `{row.get('personality') or ''}`",
                f"- Collaboration mode / 協調モード: `{row.get('collaboration_mode') or ''}`",
                f"- Observed count / 観測回数: `{row.get('observed_count') or 0}`",
                "",
            ]
        )


def _append_client_runtime_section(lines: list[str], rows: list[dict[str, Any]]) -> None:
    lines.extend(["## Client runtimes / クライアント実行環境", ""])
    if not rows:
        lines.extend(["No client runtime observations were captured. 観測されたクライアント実行環境はありません。", ""])
        return

    for row in rows:
        lines.extend(
            [
                f"### {row['id']}",
                "",
                f"- First observed at / 最初の観測時刻: `{row.get('first_observed_at') or ''}`",
                f"- CLI version / CLI バージョン: `{row.get('cli_version') or ''}`",
                f"- Originator / 起点: `{row.get('originator') or ''}`",
                f"- Source / ソース: `{row.get('source') or ''}`",
                f"- Model provider / モデル提供元: `{row.get('model_provider') or ''}`",
                f"- Observed count / 観測回数: `{row.get('observed_count') or 0}`",
                "",
            ]
        )
