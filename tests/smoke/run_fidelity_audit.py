from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_SRC = REPO_ROOT / "worker" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from timeline_for_windows_codex_worker.contracts import RefreshRequest, ThreadSelection  # noqa: E402
from timeline_for_windows_codex_worker.discovery import discover_threads  # noqa: E402
from timeline_for_windows_codex_worker.fs_utils import now_iso, read_json  # noqa: E402
from timeline_for_windows_codex_worker.parse_sessions import parse_thread_transcript_entries  # noqa: E402
from timeline_for_windows_codex_worker.processor import process_refresh  # noqa: E402
from timeline_for_windows_codex_worker.timeline import (  # noqa: E402
    THREAD_CONVERT_FILE_NAME,
    THREAD_FINAL_FILE_NAME,
    export_thread_dir_name,
)


DEFAULT_SOURCE_ROOTS = [
    REPO_ROOT / "tests" / "fixtures" / "codex-home-min",
    REPO_ROOT / "tests" / "fixtures" / "archived-root-min",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare representative raw Codex source transcripts with generated "
            "timeline.json files."
        ),
    )
    parser.add_argument(
        "--source-root",
        action="append",
        default=[],
        help="Codex source root. Defaults to the repository fixtures.",
    )
    parser.add_argument(
        "--master-root",
        help="Existing master output root to audit. If omitted, a temporary fixture master is generated first.",
    )
    parser.add_argument(
        "--item-id",
        action="append",
        default=[],
        help="Thread/item id to audit. Can be repeated or comma-separated.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of discovered items to audit. 0 means all selected/discovered items.",
    )
    parser.add_argument(
        "--preserve-output",
        action="store_true",
        help="Keep the temporary generated master output for manual inspection.",
    )
    args = parser.parse_args(argv)

    source_roots = _resolve_source_roots(args.source_root)
    if not source_roots:
        raise RuntimeError("No source roots were found for fidelity audit.")

    primary_root = source_roots[0]
    backup_roots = source_roots[1:]
    discovered = discover_threads(str(primary_root), [str(path) for path in backup_roots], True)
    selected_threads = _select_threads(discovered, _selected_item_ids(args.item_id))
    if args.limit and args.limit > 0:
        selected_threads = selected_threads[: args.limit]
    if not selected_threads:
        raise RuntimeError("No threads matched the fidelity audit selection.")

    owns_master_root = False
    if args.master_root:
        master_root = Path(args.master_root).expanduser().resolve()
    else:
        master_root = Path(tempfile.mkdtemp(prefix=f"tfwc-fidelity-audit-{int(time.time())}-"))
        owns_master_root = True
        request = RefreshRequest(
            refresh_id=f"fidelity-audit-{int(time.time())}",
            created_at=now_iso(),
            primary_codex_home_path=str(primary_root),
            backup_codex_home_paths=[str(path) for path in backup_roots],
            include_archived_sources=True,
            include_tool_outputs=False,
            include_compaction_recovery=False,
            redaction_profile="none",
            selected_threads=selected_threads,
        )
        process_refresh(request, master_root)

    try:
        results = [_audit_thread(master_root, thread) for thread in selected_threads]
        failed = [item for item in results if item["state"] != "ok"]
        payload = {
            "state": "failed" if failed else "ok",
            "audited_item_count": len(results),
            "failed_item_count": len(failed),
            "master_root": str(master_root),
            "source_roots": [str(path) for path in source_roots],
            "items": results,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1 if failed else 0
    finally:
        if owns_master_root and not args.preserve_output:
            shutil.rmtree(master_root, ignore_errors=True)


def _resolve_source_roots(values: list[str]) -> list[Path]:
    candidates = [Path(value).expanduser().resolve() for value in values] if values else DEFAULT_SOURCE_ROOTS
    return [path for path in candidates if path.exists() and path.is_dir()]


def _selected_item_ids(values: list[str]) -> list[str]:
    return [
        item.strip()
        for value in values
        for item in str(value).split(",")
        if item.strip()
    ]


def _select_threads(threads: list[ThreadSelection], selected_ids: list[str]) -> list[ThreadSelection]:
    if not selected_ids:
        return threads
    selected = {item.casefold() for item in selected_ids}
    return [thread for thread in threads if thread.thread_id.casefold() in selected]


def _audit_thread(master_root: Path, thread: ThreadSelection) -> dict[str, Any]:
    item_dir = master_root / export_thread_dir_name(thread.thread_id)
    timeline_path = item_dir / THREAD_FINAL_FILE_NAME
    convert_path = item_dir / THREAD_CONVERT_FILE_NAME
    failures: list[str] = []

    expected_rows = parse_thread_transcript_entries(
        thread,
        redaction_profile="none",
        include_compaction_recovery=False,
    )
    timeline_payload = _read_json_or_failure(timeline_path, failures)
    convert_payload = _read_json_or_failure(convert_path, failures)

    messages = timeline_payload.get("messages") if isinstance(timeline_payload, dict) else None
    if not isinstance(messages, list):
        messages = []
        failures.append("timeline.json messages is not a list")

    if (item_dir / "thread.json").exists():
        failures.append("legacy thread.json exists")
    if (item_dir / "convert.json").exists():
        failures.append("legacy convert.json exists")

    if timeline_payload.get("application") != "TimelineForWindowsCodex":
        failures.append("timeline.json application mismatch")
    if convert_payload.get("application") != "TimelineForWindowsCodex":
        failures.append("convert_info.json application mismatch")
    if timeline_payload.get("thread_id") != thread.thread_id:
        failures.append("timeline.json thread_id mismatch")
    if convert_payload.get("thread_id") != thread.thread_id:
        failures.append("convert_info.json thread_id mismatch")
    if int(convert_payload.get("message_count") or -1) != len(messages):
        failures.append("convert_info.json message_count does not match timeline.json messages")
    if len(messages) != len(expected_rows):
        failures.append(
            f"message count mismatch: raw={len(expected_rows)} timeline={len(messages)}"
        )

    for index, (expected, actual) in enumerate(zip(expected_rows, messages), start=1):
        _audit_message_pair(index, expected, actual, failures)

    return {
        "state": "failed" if failures else "ok",
        "thread_id": thread.thread_id,
        "title": timeline_payload.get("title") or thread.preferred_title,
        "source_session_path": thread.session_path,
        "message_count": len(messages),
        "raw_message_count": len(expected_rows),
        "failures": failures,
    }


def _read_json_or_failure(path: Path, failures: list[str]) -> dict[str, Any]:
    if not path.exists():
        failures.append(f"missing file: {path.name}")
        return {}
    try:
        payload = read_json(path)
    except Exception as exc:  # noqa: BLE001 - audit reports malformed artifacts as data.
        failures.append(f"failed to read {path.name}: {exc}")
        return {}
    return payload if isinstance(payload, dict) else {}


def _audit_message_pair(
    index: int,
    expected: dict[str, Any],
    actual: dict[str, Any],
    failures: list[str],
) -> None:
    expected_role = str(expected.get("actor") or "")
    actual_role = str(actual.get("role") or "")
    if actual_role != expected_role:
        failures.append(f"message {index}: role mismatch raw={expected_role!r} timeline={actual_role!r}")

    expected_at = expected.get("timestamp")
    actual_at = actual.get("created_at")
    if actual_at != expected_at:
        failures.append(f"message {index}: timestamp mismatch raw={expected_at!r} timeline={actual_at!r}")

    expected_text = str(expected.get("text") or "")
    actual_text = str(actual.get("text") or "")
    if actual_text != expected_text:
        failures.append(f"message {index}: text mismatch")

    expected_attachments = _normalize_list(expected.get("attachments"))
    actual_attachments = _normalize_list(actual.get("attachments"))
    if actual_attachments != expected_attachments:
        failures.append(
            f"message {index}: attachments mismatch raw={expected_attachments!r} timeline={actual_attachments!r}"
        )

    expected_mode = expected.get("mode")
    actual_mode = actual.get("mode")
    if expected_mode and actual_mode != expected_mode:
        failures.append(f"message {index}: mode mismatch raw={expected_mode!r} timeline={actual_mode!r}")


def _normalize_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


if __name__ == "__main__":
    raise SystemExit(main())
