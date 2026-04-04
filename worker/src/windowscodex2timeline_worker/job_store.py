from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .contracts import JobRequest, JobResult, JobStatus, ManifestThreadItem
from .fs_utils import now_iso, read_json, write_json_atomic


def request_path(job_dir: Path) -> Path:
    return job_dir / "request.json"


def status_path(job_dir: Path) -> Path:
    return job_dir / "status.json"


def result_path(job_dir: Path) -> Path:
    return job_dir / "result.json"


def manifest_path(job_dir: Path) -> Path:
    return job_dir / "manifest.json"


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
