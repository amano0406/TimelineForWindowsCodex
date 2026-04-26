from __future__ import annotations

import hashlib
import json
import shutil
import traceback
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .contracts import JobRequest, JobResult, JobStatus, ManifestThreadItem, ThreadSelection
from .fs_utils import append_jsonl, append_log, ensure_dir, now_iso, read_json, write_json_atomic, write_jsonl, write_text
from .job_store import (
    load_request,
    load_status,
    write_manifest,
    write_result,
    write_status,
)
from .parse_sessions import (
    parse_thread_environment_observations,
    parse_thread_events,
    parse_thread_transcript_entries,
    resolve_thread_session_path,
)
from .timeline import (
    build_segments,
    build_environment_ledger,
    export_thread_markdown_name,
    render_environment_ledger_md,
    render_export_readme_html,
    render_fidelity_report_md,
    RUN_INCLUDED_ITEMS,
    RUN_LIMITATION_ITEMS,
    render_thread_timeline,
    render_timeline_index,
)

PARSER_VERSION = 1
RENDER_CONTRACT_VERSION = 1
THREAD_CACHE_SCHEMA_VERSION = 1

THREAD_CACHE_FILES = {
    "timeline": "timeline.md",
    "events": "events.json",
    "transcript_entries": "transcript_entries.json",
    "environment_observations": "environment_observations.json",
    "segments": "segments.json",
    "cache": "cache.json",
}


def process_job(job_dir: Path) -> None:
    request = load_request(job_dir)
    status = load_status(job_dir)
    log_path = job_dir / "logs" / "worker.log"

    status.job_id = request.job_id
    status.state = "running"
    status.current_stage = "parsing"
    status.message = "Worker picked up the run."
    status.started_at = status.started_at or now_iso()
    status.threads_total = len(request.selected_threads)
    write_status(job_dir, status)
    append_log(log_path, f"Starting {request.job_id}")

    try:
        thread_rows: list[dict[str, object]] = []
        thread_catalog_rows: list[dict[str, object]] = []
        source_catalog_by_path: dict[str, dict[str, object]] = {}
        manifest_items: list[ManifestThreadItem] = []
        environment_observations: list[dict[str, object]] = []
        total_event_count = 0
        total_segment_count = 0
        reused_thread_count = 0
        rendered_thread_count = 0
        previous_catalog = load_previous_catalog(job_dir)
        previous_threads = _catalog_threads_by_id(previous_catalog)

        environment_root = ensure_dir(job_dir / "environment")
        threads_root = ensure_dir(job_dir / "threads")
        total_threads = max(1, len(request.selected_threads))
        for index, thread in enumerate(request.selected_threads, start=1):
            resolved_session_path = resolve_thread_session_path(thread)
            if resolved_session_path is not None:
                thread.session_path = str(resolved_session_path)
            source_fingerprint = _file_fingerprint(resolved_session_path)
            thread_cache_key = build_thread_cache_key(request, thread, source_fingerprint)

            status.current_thread_id = thread.thread_id
            status.current_thread_title = thread.preferred_title
            thread_dir = ensure_dir(threads_root / thread.thread_id)
            timeline_path = thread_dir / "timeline.md"
            previous_thread = previous_threads.get(thread.thread_id)
            reused = try_reuse_thread_cache(previous_thread, thread_cache_key, thread_dir)
            if reused:
                status.current_stage = "reusing"
                status.message = f"Reusing {thread.preferred_title or thread.thread_id}"
                write_status(job_dir, status)
                events = _read_json_list(thread_dir / THREAD_CACHE_FILES["events"])
                transcript_entries = _read_json_list(thread_dir / THREAD_CACHE_FILES["transcript_entries"])
                thread_environment_observations = _read_json_list(
                    thread_dir / THREAD_CACHE_FILES["environment_observations"]
                )
                segments = _read_json_list(thread_dir / THREAD_CACHE_FILES["segments"])
                reused_thread_count += 1
                append_log(log_path, f"Reused {thread.thread_id} events={len(events)}")
            else:
                status.current_stage = "parsing"
                status.message = f"Parsing {thread.preferred_title or thread.thread_id}"
                write_status(job_dir, status)

                events = parse_thread_events(
                    thread,
                    include_tool_outputs=request.include_tool_outputs,
                    redaction_profile=request.redaction_profile,
                    date_from=request.date_from,
                    date_to=request.date_to,
                )
                transcript_entries = parse_thread_transcript_entries(
                    thread,
                    redaction_profile=request.redaction_profile,
                    date_from=request.date_from,
                    date_to=request.date_to,
                )
                thread_environment_observations = parse_thread_environment_observations(
                    thread,
                    date_from=request.date_from,
                    date_to=request.date_to,
                )
                if not thread.cwd:
                    thread.cwd = next(
                        (
                            str(event.get("cwd") or "")
                            for event in events
                            if event.get("kind") == "session_meta" and event.get("cwd")
                        ),
                        thread.cwd,
                    )
                segments = build_segments(events)

                status.current_stage = "rendering"
                status.message = f"Rendering {thread.preferred_title or thread.thread_id}"
                write_status(job_dir, status)

                timeline_markdown = render_thread_timeline(thread, transcript_entries)
                write_text(timeline_path, timeline_markdown)
                write_thread_cache_artifacts(
                    thread_dir=thread_dir,
                    cache_key=thread_cache_key,
                    source_fingerprint=source_fingerprint,
                    events=events,
                    transcript_entries=transcript_entries,
                    environment_observations=thread_environment_observations,
                    segments=segments,
                )
                rendered_thread_count += 1
                append_log(log_path, f"Processed {thread.thread_id} events={len(events)}")

            timeline_fingerprint = _file_fingerprint(timeline_path)
            if source_fingerprint is not None:
                source_catalog_by_path[str(source_fingerprint["path"])] = source_fingerprint

            manifest_items.append(
                ManifestThreadItem(
                    thread_id=thread.thread_id,
                    preferred_title=thread.preferred_title,
                    session_path=thread.session_path,
                    source_root_path=thread.source_root_path,
                    status="completed",
                    event_count=len(events),
                    timeline_path=str(timeline_path),
                )
            )

            thread_row = {
                "thread_id": thread.thread_id,
                "preferred_title": thread.preferred_title,
                "timeline_path": str(timeline_path),
                "event_count": len(events),
                "message_count": len(transcript_entries),
                "segment_count": len(segments),
                "source_root_kind": thread.source_root_kind,
                "resolved_session_path": str(resolved_session_path) if resolved_session_path is not None else "",
                "source_type": _source_type_from_path(resolved_session_path),
                "cwd": thread.cwd,
                "updated_at": thread.updated_at,
                "observed_thread_name_count": len(thread.observed_thread_names),
                "has_mode": any(str(entry.get("mode") or "").strip() for entry in transcript_entries),
                "attachment_count": sum(
                    len(entry.get("attachments") or [])
                    for entry in transcript_entries
                    if isinstance(entry.get("attachments"), list)
                ),
                "limitations": _build_thread_limitations(
                    resolved_session_path=resolved_session_path,
                    transcript_entries=transcript_entries,
                ),
            }
            thread_rows.append(thread_row)
            thread_catalog_rows.append(
                {
                    "thread_id": thread.thread_id,
                    "preferred_title": thread.preferred_title,
                    "source_refs": [str(resolved_session_path)] if resolved_session_path is not None else [],
                    "source_type": thread_row["source_type"],
                    "source_root_kind": thread.source_root_kind,
                    "message_count": len(transcript_entries),
                    "event_count": len(events),
                    "timeline_path": str(timeline_path),
                    "timeline_sha256": timeline_fingerprint["sha256"] if timeline_fingerprint is not None else "",
                    "parser_version": PARSER_VERSION,
                    "render_contract_version": RENDER_CONTRACT_VERSION,
                    "cache_key": thread_cache_key,
                    "cache_status": "reused" if reused else "rendered",
                    "cache_artifacts": _thread_cache_artifact_paths(thread_dir),
                }
            )

            for observation in thread_environment_observations:
                environment_observations.append(observation)
            total_event_count += len(events)
            total_segment_count += len(segments)

            status.threads_done = index
            status.events_done = total_event_count
            status.events_total = total_event_count
            status.progress_percent = round((index / total_threads) * 92.0, 1)
            write_status(job_dir, status)
            write_manifest(job_dir, request.job_id, manifest_items)

        environment_observations = sorted(
            environment_observations,
            key=lambda item: (
                str(item.get("timestamp") or ""),
                str(item.get("thread_id") or ""),
                str(item.get("kind") or ""),
                str(item.get("fingerprint") or ""),
            ),
        )
        environment_ledger = build_environment_ledger(environment_observations)
        write_jsonl(environment_root / "observations.jsonl", environment_observations)
        write_json_atomic(environment_root / "ledger.json", environment_ledger)
        write_text(
            environment_root / "ledger.md",
            render_environment_ledger_md(request.job_id, environment_ledger),
        )

        fidelity_report = build_fidelity_report(request.job_id, thread_rows)
        write_json_atomic(job_dir / "fidelity_report.json", fidelity_report)
        write_text(
            job_dir / "fidelity_report.md",
            render_fidelity_report_md(request.job_id, fidelity_report),
        )
        run_catalog = build_run_catalog(
            request.job_id,
            list(source_catalog_by_path.values()),
            thread_catalog_rows,
        )
        update_manifest = build_update_manifest(
            request.job_id,
            run_catalog,
            previous_catalog,
        )
        write_json_atomic(job_dir / "catalog.json", run_catalog)
        write_json_atomic(job_dir / "update_manifest.json", update_manifest)

        _assign_export_names(thread_rows)

        timeline_index_path = threads_root / "index.md"
        export_readme_path = job_dir / "readme.html"

        timeline_index_text = render_timeline_index(request.job_id, thread_rows)
        export_readme_html = render_export_readme_html(request.job_id, thread_rows)

        write_text(timeline_index_path, timeline_index_text)
        write_text(export_readme_path, export_readme_html)

        status.current_stage = "archiving"
        status.message = "Building ZIP archive."
        status.progress_percent = 96.0
        write_status(job_dir, status)

        archive_path = build_run_archive(job_dir, thread_rows)

        result = JobResult(
            job_id=request.job_id,
            state="completed",
            thread_count=len(thread_rows),
            event_count=total_event_count,
            segment_count=total_segment_count,
            timeline_index_path=str(timeline_index_path),
            archive_path=str(archive_path),
            warnings=status.warnings,
        )
        write_result(job_dir, result)

        status.state = "completed"
        status.current_stage = "completed"
        status.message = "Run completed."
        status.progress_percent = 100.0
        status.completed_at = now_iso()
        write_status(job_dir, status)
        write_manifest(job_dir, request.job_id, manifest_items)
        write_current_artifact_pointer(
            job_dir=job_dir,
            job_id=request.job_id,
            archive_path=archive_path,
            thread_count=len(thread_rows),
            event_count=total_event_count,
            reused_thread_count=reused_thread_count,
            rendered_thread_count=rendered_thread_count,
            completed_at=status.completed_at,
        )
        append_refresh_history(
            job_dir=job_dir,
            row={
                "schema_version": 1,
                "refresh_id": request.job_id,
                "job_id": request.job_id,
                "state": "completed",
                "processing_mode": processing_mode_for_run(reused_thread_count),
                "thread_count": len(thread_rows),
                "event_count": total_event_count,
                "reused_thread_count": reused_thread_count,
                "rendered_thread_count": rendered_thread_count,
                "archive_path": str(archive_path),
                "completed_at": status.completed_at,
            },
        )
        append_log(log_path, f"Completed {request.job_id}")
    except Exception as exc:  # pragma: no cover - exercised by manual runs first
        append_log(log_path, f"Failed {request.job_id}: {exc}")
        append_log(log_path, traceback.format_exc())
        status.state = "failed"
        status.current_stage = "failed"
        status.message = str(exc)
        status.completed_at = now_iso()
        write_status(job_dir, status)
        write_result(
            job_dir,
            JobResult(
                job_id=request.job_id,
                state="failed",
                warnings=[str(exc)],
            ),
        )
        append_refresh_history(
            job_dir=job_dir,
            row={
                "schema_version": 1,
                "refresh_id": request.job_id,
                "job_id": request.job_id,
                "state": "failed",
                "processing_mode": "failed_refresh",
                "error": str(exc),
                "completed_at": status.completed_at,
            },
        )
        raise


def build_run_archive(job_dir: Path, thread_rows: list[dict[str, object]]) -> Path:
    export_root = ensure_dir(job_dir / "export")
    archive_path = export_root / "TimelineForWindowsCodex-export.zip"

    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        _write_if_exists(archive, job_dir / "readme.html", "readme.html")
        _write_if_exists(archive, job_dir / "README.md", "README.md")
        _write_if_exists(archive, job_dir / "NOTICE.md", "NOTICE.md")
        _write_if_exists(archive, job_dir / "fidelity_report.md", "fidelity_report.md")
        _write_if_exists(archive, job_dir / "fidelity_report.json", "fidelity_report.json")
        _write_if_exists(archive, job_dir / "catalog.json", "catalog.json")
        _write_if_exists(archive, job_dir / "update_manifest.json", "update_manifest.json")
        _write_if_exists(archive, job_dir / "manifest.json", "manifest.json")
        _write_if_exists(archive, job_dir / "status.json", "status.json")
        _write_if_exists(archive, job_dir / "result.json", "result.json")
        _write_if_exists(archive, job_dir / "threads" / "index.md", "threads/index.md")
        _write_if_exists(archive, job_dir / "environment" / "observations.jsonl", "environment/observations.jsonl")
        _write_if_exists(archive, job_dir / "environment" / "ledger.json", "environment/ledger.json")
        _write_if_exists(archive, job_dir / "environment" / "ledger.md", "environment/ledger.md")

        for row in thread_rows:
            timeline_path = Path(str(row["timeline_path"]))
            archive_name = str(row["export_markdown_name"])
            _write_if_exists(archive, timeline_path, f"threads/{archive_name}")

    return archive_path


def write_current_artifact_pointer(
    *,
    job_dir: Path,
    job_id: str,
    archive_path: Path,
    thread_count: int,
    event_count: int,
    reused_thread_count: int,
    rendered_thread_count: int,
    completed_at: str | None,
) -> None:
    outputs_root = job_dir.parent
    write_json_atomic(
        outputs_root / "current.json",
        {
            "schema_version": 1,
            "job_id": job_id,
            "state": "completed",
            "processing_mode": processing_mode_for_run(reused_thread_count),
            "updated_at": completed_at or now_iso(),
            "run_directory": str(job_dir),
            "archive_path": str(archive_path),
            "readme_path": str(job_dir / "readme.html"),
            "catalog_path": str(job_dir / "catalog.json"),
            "update_manifest_path": str(job_dir / "update_manifest.json"),
            "fidelity_report_path": str(job_dir / "fidelity_report.json"),
            "thread_count": thread_count,
            "event_count": event_count,
            "reused_thread_count": reused_thread_count,
            "rendered_thread_count": rendered_thread_count,
        },
    )


def append_refresh_history(*, job_dir: Path, row: dict[str, object]) -> None:
    append_jsonl(job_dir.parent / "refresh-history.jsonl", row)


def processing_mode_for_run(reused_thread_count: int) -> str:
    return "incremental_reuse" if reused_thread_count > 0 else "full_rebuild"


def build_thread_cache_key(
    request: JobRequest,
    thread: ThreadSelection,
    source_fingerprint: dict[str, object] | None,
) -> str:
    payload = {
        "schema_version": THREAD_CACHE_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "render_contract_version": RENDER_CONTRACT_VERSION,
        "request": {
            "include_tool_outputs": request.include_tool_outputs,
            "redaction_profile": request.redaction_profile,
            "date_from": request.date_from,
            "date_to": request.date_to,
        },
        "thread": {
            "thread_id": thread.thread_id,
            "preferred_title": thread.preferred_title,
            "observed_thread_names": [
                item.to_dict()
                for item in thread.observed_thread_names
            ],
            "source_root_kind": thread.source_root_kind,
            "session_path": thread.session_path,
            "updated_at": thread.updated_at,
            "cwd": thread.cwd,
            "first_user_message_excerpt": thread.first_user_message_excerpt,
        },
        "source": _source_fingerprint_for_cache(source_fingerprint),
    }
    return _stable_payload_sha256(payload)


def try_reuse_thread_cache(
    previous_thread: dict[str, object] | None,
    cache_key: str,
    thread_dir: Path,
) -> bool:
    if previous_thread is None or str(previous_thread.get("cache_key") or "") != cache_key:
        return False

    artifacts = previous_thread.get("cache_artifacts")
    if not isinstance(artifacts, dict):
        return False

    source_paths: dict[str, Path] = {}
    for key in THREAD_CACHE_FILES:
        source_path = Path(str(artifacts.get(key) or ""))
        if not source_path.exists() or not source_path.is_file():
            return False
        source_paths[key] = source_path

    ensure_dir(thread_dir)
    for key, filename in THREAD_CACHE_FILES.items():
        shutil.copy2(source_paths[key], thread_dir / filename)

    return True


def write_thread_cache_artifacts(
    *,
    thread_dir: Path,
    cache_key: str,
    source_fingerprint: dict[str, object] | None,
    events: list[dict[str, object]],
    transcript_entries: list[dict[str, object]],
    environment_observations: list[dict[str, object]],
    segments: list[dict[str, object]],
) -> None:
    write_json_atomic(thread_dir / THREAD_CACHE_FILES["events"], events)
    write_json_atomic(thread_dir / THREAD_CACHE_FILES["transcript_entries"], transcript_entries)
    write_json_atomic(thread_dir / THREAD_CACHE_FILES["environment_observations"], environment_observations)
    write_json_atomic(thread_dir / THREAD_CACHE_FILES["segments"], segments)
    write_json_atomic(
        thread_dir / THREAD_CACHE_FILES["cache"],
        {
            "schema_version": THREAD_CACHE_SCHEMA_VERSION,
            "cache_key": cache_key,
            "parser_version": PARSER_VERSION,
            "render_contract_version": RENDER_CONTRACT_VERSION,
            "source_fingerprint": source_fingerprint,
        },
    )


def _thread_cache_artifact_paths(thread_dir: Path) -> dict[str, str]:
    return {
        key: str(thread_dir / filename)
        for key, filename in THREAD_CACHE_FILES.items()
    }


def _read_json_list(path: Path) -> list[dict[str, object]]:
    payload = read_json(path)
    if not isinstance(payload, list):
        return []
    return [
        item
        for item in payload
        if isinstance(item, dict)
    ]


def _write_if_exists(archive: ZipFile, path: Path, archive_name: str) -> None:
    if path.exists():
        archive.write(path, archive_name)


def _assign_export_names(thread_rows: list[dict[str, object]]) -> None:
    for row in thread_rows:
        preferred_title = str(row.get("preferred_title") or "")
        thread_id = str(row.get("thread_id") or "")
        row["export_markdown_name"] = export_thread_markdown_name(preferred_title, thread_id)


def build_fidelity_report(job_id: str, thread_rows: list[dict[str, object]]) -> dict[str, object]:
    source_types = sorted(
        {
            str(row.get("source_type") or "").strip()
            for row in thread_rows
            if str(row.get("source_type") or "").strip()
        }
    )
    warnings = sorted(
        {
            limitation
            for row in thread_rows
            for limitation in (row.get("limitations") or [])
            if isinstance(limitation, str) and limitation.startswith("Source file could not")
        }
    )
    return {
        "schema_version": 1,
        "job_id": job_id,
        "thread_count": len(thread_rows),
        "source_types": source_types,
        "included": list(RUN_INCLUDED_ITEMS),
        "limitations": list(RUN_LIMITATION_ITEMS),
        "warnings": warnings,
        "threads": [
            {
                "thread_id": str(row.get("thread_id") or ""),
                "preferred_title": str(row.get("preferred_title") or ""),
                "source_root_kind": str(row.get("source_root_kind") or ""),
                "source_type": str(row.get("source_type") or ""),
                "resolved_session_path": str(row.get("resolved_session_path") or ""),
                "message_count": int(row.get("message_count") or 0),
                "event_count": int(row.get("event_count") or 0),
                "segment_count": int(row.get("segment_count") or 0),
                "observed_thread_name_count": int(row.get("observed_thread_name_count") or 0),
                "has_mode": bool(row.get("has_mode")),
                "attachment_count": int(row.get("attachment_count") or 0),
                "limitations": list(row.get("limitations") or []),
            }
            for row in thread_rows
        ],
    }


def build_run_catalog(
    job_id: str,
    source_files: list[dict[str, object]],
    thread_rows: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "job_id": job_id,
        "generated_at": now_iso(),
        "source_files": sorted(source_files, key=lambda item: str(item.get("path") or "")),
        "threads": sorted(thread_rows, key=lambda item: str(item.get("thread_id") or "")),
    }


def load_previous_catalog(job_dir: Path) -> dict[str, object] | None:
    current_pointer_path = job_dir.parent / "current.json"
    if not current_pointer_path.exists():
        return None

    try:
        current_pointer = read_json(current_pointer_path)
    except Exception:
        return None

    previous_job_id = str(current_pointer.get("job_id") or "")
    if previous_job_id == job_dir.name:
        return None

    catalog_path_text = str(current_pointer.get("catalog_path") or "")
    if not catalog_path_text:
        return None

    catalog_path = Path(catalog_path_text)
    if not catalog_path.exists():
        return None

    try:
        return read_json(catalog_path)
    except Exception:
        return None


def build_update_manifest(
    job_id: str,
    current_catalog: dict[str, object],
    previous_catalog: dict[str, object] | None,
) -> dict[str, object]:
    previous_threads = _catalog_threads_by_id(previous_catalog)
    current_threads = _catalog_threads_by_id(current_catalog)
    previous_job_id = str(previous_catalog.get("job_id") or "") if previous_catalog is not None else ""
    reused_thread_count = sum(
        1
        for row in current_threads.values()
        if str(row.get("cache_status") or "") == "reused"
    )

    rows: list[dict[str, object]] = []
    counts = {
        "new": 0,
        "changed": 0,
        "unchanged": 0,
        "missing": 0,
        "degraded": 0,
    }

    for thread_id in sorted(current_threads):
        current = current_threads[thread_id]
        previous = previous_threads.get(thread_id)
        status = _classify_thread_update(current, previous)
        counts[status] += 1
        rows.append(
            {
                "thread_id": thread_id,
                "preferred_title": str(current.get("preferred_title") or ""),
                "status": status,
                "source_type": str(current.get("source_type") or ""),
                "cache_status": str(current.get("cache_status") or ""),
                "message_count": int(current.get("message_count") or 0),
                "event_count": int(current.get("event_count") or 0),
                "previous_message_count": int(previous.get("message_count") or 0) if previous is not None else 0,
                "previous_event_count": int(previous.get("event_count") or 0) if previous is not None else 0,
            }
        )

    for thread_id in sorted(set(previous_threads) - set(current_threads)):
        previous = previous_threads[thread_id]
        counts["missing"] += 1
        rows.append(
            {
                "thread_id": thread_id,
                "preferred_title": str(previous.get("preferred_title") or ""),
                "status": "missing",
                "source_type": str(previous.get("source_type") or ""),
                "message_count": 0,
                "event_count": 0,
                "previous_message_count": int(previous.get("message_count") or 0),
                "previous_event_count": int(previous.get("event_count") or 0),
            }
        )

    return {
        "schema_version": 1,
        "job_id": job_id,
        "previous_job_id": previous_job_id,
        "generated_at": now_iso(),
        "processing_mode": processing_mode_for_run(reused_thread_count),
        "counts": counts,
        "threads": rows,
    }


def _catalog_threads_by_id(catalog: dict[str, object] | None) -> dict[str, dict[str, object]]:
    if catalog is None:
        return {}

    rows: dict[str, dict[str, object]] = {}
    for item in catalog.get("threads") or []:
        if not isinstance(item, dict):
            continue
        thread_id = str(item.get("thread_id") or "")
        if thread_id:
            rows[thread_id] = item
    return rows


def _classify_thread_update(
    current: dict[str, object],
    previous: dict[str, object] | None,
) -> str:
    if previous is None:
        return "new"

    current_message_count = int(current.get("message_count") or 0)
    previous_message_count = int(previous.get("message_count") or 0)
    current_source_type = str(current.get("source_type") or "")
    previous_source_type = str(previous.get("source_type") or "")
    if (
        current_source_type == "missing" and previous_source_type != "missing"
    ) or current_message_count < previous_message_count:
        return "degraded"

    comparable_keys = (
        "source_refs",
        "source_type",
        "cache_key",
        "timeline_sha256",
        "parser_version",
        "render_contract_version",
        "message_count",
        "event_count",
    )
    if all(current.get(key) == previous.get(key) for key in comparable_keys):
        return "unchanged"

    return "changed"


def _source_type_from_path(path: Path | None) -> str:
    if path is None:
        return "missing"
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return "session_jsonl"
    if suffix == ".json":
        return "thread_read_json"
    return "unknown"


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
