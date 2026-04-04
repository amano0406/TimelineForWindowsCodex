from __future__ import annotations

import traceback
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .contracts import JobResult, JobStatus, ManifestThreadItem
from .fs_utils import append_log, ensure_dir, now_iso, write_json_atomic, write_jsonl, write_text
from .job_store import (
    load_request,
    load_status,
    write_manifest,
    write_result,
    write_status,
)
from .parse_sessions import parse_thread_events, resolve_thread_session_path
from .timeline import (
    build_segments,
    export_timeline_name,
    render_handoff_md,
    render_thread_timeline,
    render_timeline_index,
)


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
        manifest_items: list[ManifestThreadItem] = []
        combined_events: list[dict[str, object]] = []
        combined_segments: list[dict[str, object]] = []

        normalized_root = ensure_dir(job_dir / "normalized")
        derived_root = ensure_dir(job_dir / "derived")
        threads_root = ensure_dir(job_dir / "threads")
        llm_root = ensure_dir(job_dir / "llm")

        total_threads = max(1, len(request.selected_threads))
        for index, thread in enumerate(request.selected_threads, start=1):
            resolved_session_path = resolve_thread_session_path(thread)
            if resolved_session_path is not None:
                thread.session_path = str(resolved_session_path)

            status.current_thread_id = thread.thread_id
            status.current_thread_title = thread.preferred_title
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

            thread_dir = ensure_dir(threads_root / thread.thread_id)
            timeline_path = thread_dir / "timeline.md"
            normalized_path = normalized_root / f"{thread.thread_id}.events.jsonl"
            segments_path = derived_root / f"{thread.thread_id}.segments.json"

            write_jsonl(normalized_path, events)
            write_json_atomic(segments_path, segments)

            status.current_stage = "rendering"
            status.message = f"Rendering {thread.preferred_title or thread.thread_id}"
            write_status(job_dir, status)

            timeline_markdown = render_thread_timeline(thread, events, segments)
            write_text(timeline_path, timeline_markdown)

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
                "segment_count": len(segments),
                "source_root_kind": thread.source_root_kind,
                "cwd": thread.cwd,
            }
            thread_rows.append(thread_row)

            for event in events:
                combined_events.append(event)
            combined_segments.append(
                {
                    "thread_id": thread.thread_id,
                    "preferred_title": thread.preferred_title,
                    "segments": segments,
                }
            )

            status.threads_done = index
            status.events_done = len(combined_events)
            status.events_total = len(combined_events)
            status.progress_percent = round((index / total_threads) * 92.0, 1)
            write_status(job_dir, status)
            write_manifest(job_dir, request.job_id, manifest_items)
            append_log(log_path, f"Processed {thread.thread_id} events={len(events)}")

        write_jsonl(normalized_root / "events.jsonl", combined_events)
        write_json_atomic(derived_root / "segments.json", combined_segments)

        timeline_index_path = threads_root / "index.md"
        handoff_md_path = llm_root / "handoff.md"
        handoff_json_path = llm_root / "handoff.json"

        timeline_index_text = render_timeline_index(request.job_id, thread_rows)
        handoff_md_text = render_handoff_md(
            request.job_id,
            thread_rows,
            total_events=len(combined_events),
            total_segments=sum(int(row["segment_count"]) for row in thread_rows),
        )

        write_text(timeline_index_path, timeline_index_text)
        write_text(handoff_md_path, handoff_md_text)
        write_json_atomic(
            handoff_json_path,
            {
                "schema_version": 1,
                "job_id": request.job_id,
                "generated_at": now_iso(),
                "thread_count": len(thread_rows),
                "event_count": len(combined_events),
                "segment_count": sum(int(row["segment_count"]) for row in thread_rows),
                "threads": thread_rows,
            },
        )

        status.current_stage = "archiving"
        status.message = "Building ZIP archive."
        status.progress_percent = 96.0
        write_status(job_dir, status)

        archive_path = build_run_archive(job_dir, thread_rows)

        result = JobResult(
            job_id=request.job_id,
            state="completed",
            thread_count=len(thread_rows),
            event_count=len(combined_events),
            segment_count=sum(int(row["segment_count"]) for row in thread_rows),
            timeline_index_path=str(timeline_index_path),
            handoff_path=str(handoff_md_path),
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
        raise


def build_run_archive(job_dir: Path, thread_rows: list[dict[str, object]]) -> Path:
    export_root = ensure_dir(job_dir / "export")
    archive_path = export_root / "windowscodex2timeline-export.zip"

    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        _write_if_exists(archive, job_dir / "README.md", "README.md")
        _write_if_exists(archive, job_dir / "NOTICE.md", "NOTICE.md")
        _write_if_exists(archive, job_dir / "manifest.json", "manifest.json")
        _write_if_exists(archive, job_dir / "status.json", "status.json")
        _write_if_exists(archive, job_dir / "result.json", "result.json")
        _write_if_exists(archive, job_dir / "llm" / "handoff.md", "llm/handoff.md")
        _write_if_exists(archive, job_dir / "llm" / "handoff.json", "llm/handoff.json")
        _write_if_exists(archive, job_dir / "threads" / "index.md", "threads/index.md")
        _write_if_exists(archive, job_dir / "normalized" / "events.jsonl", "normalized/events.jsonl")
        _write_if_exists(archive, job_dir / "derived" / "segments.json", "derived/segments.json")

        for row in thread_rows:
            thread_id = str(row["thread_id"])
            preferred_title = str(row["preferred_title"])
            timeline_path = Path(str(row["timeline_path"]))
            archive_name = export_timeline_name(preferred_title, thread_id)
            _write_if_exists(archive, timeline_path, f"timelines/{archive_name}")

    return archive_path


def _write_if_exists(archive: ZipFile, path: Path, archive_name: str) -> None:
    if path.exists():
        archive.write(path, archive_name)
