from __future__ import annotations

from pathlib import Path
from typing import Iterable
from uuid import uuid4

from .contracts import JobRequest, JobResult, JobStatus, ManifestThreadItem
from .fs_utils import ensure_dir, now_iso, read_json, write_json_atomic, write_text


def request_path(job_dir: Path) -> Path:
    return job_dir / "request.json"


def status_path(job_dir: Path) -> Path:
    return job_dir / "status.json"


def result_path(job_dir: Path) -> Path:
    return job_dir / "result.json"


def manifest_path(job_dir: Path) -> Path:
    return job_dir / "manifest.json"


def create_job_id(outputs_root: Path) -> str:
    ensure_dir(outputs_root)
    while True:
        candidate = f"run-{now_iso().replace(':', '').replace('-', '')[:15]}-{uuid4().hex}"[:32]
        if not (outputs_root / candidate).exists():
            return candidate


def create_job(job_dir: Path, request: JobRequest) -> None:
    ensure_dir(job_dir)
    ensure_dir(job_dir / "environment")
    ensure_dir(job_dir / "export")
    ensure_dir(job_dir / "logs")

    write_json_atomic(request_path(job_dir), request.to_dict())
    write_status(
        job_dir,
        JobStatus(
            job_id=request.job_id,
            state="pending",
            current_stage="queued",
            message="Waiting for worker pickup.",
            threads_total=len(request.selected_threads),
            threads_done=0,
            events_total=0,
            events_done=0,
            progress_percent=0.0,
        ),
    )
    write_result(job_dir, JobResult(job_id=request.job_id, state="pending"))
    write_manifest(
        job_dir,
        request.job_id,
        [
            ManifestThreadItem(
                thread_id=thread.thread_id,
                preferred_title=thread.preferred_title,
                session_path=thread.session_path,
                source_root_path=thread.source_root_path,
                status="pending",
                event_count=0,
            )
            for thread in request.selected_threads
        ],
    )
    write_text(
        job_dir / "README.md",
        "# TimelineForWindowsCodex run\n\nThis directory is the source of truth for one timeline run.\n",
    )
    write_text(
        job_dir / "NOTICE.md",
        "Sensitive data may exist in raw source material. Exported outputs should use redacted views.\n",
    )


def load_request(job_dir: Path) -> JobRequest:
    return JobRequest.from_dict(read_json(request_path(job_dir)))


def load_status(job_dir: Path) -> JobStatus:
    path = status_path(job_dir)
    if not path.exists():
        return JobStatus(job_id=job_dir.name, updated_at=now_iso())
    return JobStatus(**read_json(path))


def write_status(job_dir: Path, status: JobStatus) -> None:
    status.updated_at = now_iso()
    write_json_atomic(status_path(job_dir), status.to_dict())


def write_result(job_dir: Path, result: JobResult) -> None:
    write_json_atomic(result_path(job_dir), result.to_dict())


def write_manifest(job_dir: Path, job_id: str, items: Iterable[ManifestThreadItem]) -> None:
    payload = {
        "schema_version": 1,
        "job_id": job_id,
        "generated_at": now_iso(),
        "items": [item.to_dict() for item in items],
    }
    write_json_atomic(manifest_path(job_dir), payload)


def iter_run_dirs(outputs_root: Path) -> list[Path]:
    if not outputs_root.exists():
        return []
    return sorted(
        [
            path
            for path in outputs_root.iterdir()
            if path.is_dir() and request_path(path).exists()
        ],
        key=lambda item: item.name,
    )


def collect_jobs_by_state(outputs_root: Path, *states: str) -> list[Path]:
    wanted = {state.lower() for state in states}
    rows: list[Path] = []
    for job_dir in iter_run_dirs(outputs_root):
        status = load_status(job_dir)
        if status.state.lower() in wanted:
            rows.append(job_dir)
    return rows
