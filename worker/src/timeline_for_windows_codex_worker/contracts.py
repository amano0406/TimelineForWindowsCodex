from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ObservedThreadName:
    name: str
    observed_at: str | None = None
    source: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ObservedThreadName":
        return cls(
            name=str(payload.get("name") or ""),
            observed_at=payload.get("observed_at"),
            source=str(payload.get("source") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ThreadSelection:
    thread_id: str
    preferred_title: str
    observed_thread_names: list[ObservedThreadName] = field(default_factory=list)
    source_root_path: str = ""
    source_root_kind: str = ""
    session_path: str = ""
    updated_at: str | None = None
    cwd: str | None = None
    first_user_message_excerpt: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ThreadSelection":
        observations_payload = payload.get("observed_thread_names") or []
        title_history = payload.get("title_history") or []
        return cls(
            thread_id=str(payload.get("thread_id") or ""),
            preferred_title=str(payload.get("preferred_title") or ""),
            observed_thread_names=[
                ObservedThreadName.from_dict(item)
                for item in observations_payload
                if isinstance(item, dict)
            ] or [
                ObservedThreadName(name=str(item or ""))
                for item in title_history
                if str(item or "").strip()
            ],
            source_root_path=str(payload.get("source_root_path") or ""),
            source_root_kind=str(payload.get("source_root_kind") or ""),
            session_path=str(payload.get("session_path") or ""),
            updated_at=payload.get("updated_at"),
            cwd=payload.get("cwd"),
            first_user_message_excerpt=payload.get("first_user_message_excerpt"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observed_thread_names"] = [item.to_dict() for item in self.observed_thread_names]
        return payload


@dataclass
class JobRequest:
    schema_version: int = 1
    job_id: str = ""
    created_at: str = ""
    primary_codex_home_path: str = ""
    backup_codex_home_paths: list[str] = field(default_factory=list)
    include_archived_sources: bool = True
    include_tool_outputs: bool = True
    redaction_profile: str = "strict"
    date_from: str | None = None
    date_to: str | None = None
    selected_threads: list[ThreadSelection] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "JobRequest":
        return cls(
            schema_version=int(payload.get("schema_version") or 1),
            job_id=str(payload.get("job_id") or ""),
            created_at=str(payload.get("created_at") or ""),
            primary_codex_home_path=str(payload.get("primary_codex_home_path") or ""),
            backup_codex_home_paths=list(payload.get("backup_codex_home_paths") or []),
            include_archived_sources=bool(payload.get("include_archived_sources", True)),
            include_tool_outputs=bool(payload.get("include_tool_outputs", True)),
            redaction_profile=str(payload.get("redaction_profile") or "strict"),
            date_from=payload.get("date_from"),
            date_to=payload.get("date_to"),
            selected_threads=[
                ThreadSelection.from_dict(item)
                for item in payload.get("selected_threads", [])
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "created_at": self.created_at,
            "primary_codex_home_path": self.primary_codex_home_path,
            "backup_codex_home_paths": self.backup_codex_home_paths,
            "include_archived_sources": self.include_archived_sources,
            "include_tool_outputs": self.include_tool_outputs,
            "redaction_profile": self.redaction_profile,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "selected_threads": [item.to_dict() for item in self.selected_threads],
        }


@dataclass
class JobStatus:
    schema_version: int = 1
    job_id: str = ""
    state: str = "pending"
    current_stage: str = "queued"
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    threads_total: int = 0
    threads_done: int = 0
    events_total: int = 0
    events_done: int = 0
    progress_percent: float = 0.0
    estimated_remaining_sec: float | None = None
    current_thread_id: str | None = None
    current_thread_title: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JobResult:
    schema_version: int = 1
    job_id: str = ""
    state: str = "pending"
    thread_count: int = 0
    event_count: int = 0
    segment_count: int = 0
    timeline_index_path: str | None = None
    handoff_path: str | None = None
    archive_path: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ManifestThreadItem:
    thread_id: str
    preferred_title: str
    session_path: str
    source_root_path: str
    status: str = "pending"
    event_count: int = 0
    timeline_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
