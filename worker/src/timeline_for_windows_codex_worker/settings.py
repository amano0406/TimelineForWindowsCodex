from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .fs_utils import ensure_dir, read_json, write_json_atomic


@dataclass(frozen=True)
class RuntimePaths:
    outputs_root: Path
    appdata_root: Path
    runtime_defaults_path: Path
    settings_path: Path


@dataclass
class RuntimeDefaults:
    default_primary_codex_home_path: str = "/input/codex-home"
    default_backup_codex_home_paths: list[str] | None = None
    default_redaction_profile: str = "strict"
    default_include_archived_sources: bool = True
    default_include_tool_outputs: bool = True

    def __post_init__(self) -> None:
        if self.default_backup_codex_home_paths is None:
            self.default_backup_codex_home_paths = []


@dataclass
class UserSettings:
    schema_version: int = 1
    source_roots: list[str] | None = None
    outputs_root: str = ""
    redaction_profile: str = ""
    include_archived_sources: bool | None = None
    include_tool_outputs: bool | None = None

    def __post_init__(self) -> None:
        if self.source_roots is None:
            self.source_roots = []

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "UserSettings":
        return cls(
            schema_version=int(payload.get("schema_version") or 1),
            source_roots=[
                str(item).strip()
                for item in (payload.get("source_roots") or [])
                if str(item).strip()
            ],
            outputs_root=str(payload.get("outputs_root") or "").strip(),
            redaction_profile=str(payload.get("redaction_profile") or "").strip().lower(),
            include_archived_sources=_optional_bool(payload.get("include_archived_sources")),
            include_tool_outputs=_optional_bool(payload.get("include_tool_outputs")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_roots": list(self.source_roots or []),
            "outputs_root": self.outputs_root,
            "redaction_profile": self.redaction_profile,
            "include_archived_sources": self.include_archived_sources,
            "include_tool_outputs": self.include_tool_outputs,
        }


def _normalize_path(value: str | None, fallback: str) -> Path:
    raw = (value or fallback).strip()
    return Path(raw or fallback).expanduser().resolve()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_runtime_paths() -> RuntimePaths:
    repo_root = _repo_root()
    appdata_root = _normalize_path(
        os.environ.get("TIMELINE_FOR_WINDOWS_CODEX_APPDATA_ROOT"),
        "/shared/app-data",
    )
    outputs_root = _normalize_path(
        os.environ.get("TIMELINE_FOR_WINDOWS_CODEX_OUTPUTS_ROOT"),
        str(appdata_root / "outputs"),
    )
    runtime_defaults_path = _normalize_path(
        os.environ.get("TIMELINE_FOR_WINDOWS_CODEX_RUNTIME_DEFAULTS"),
        "/app/config/runtime.defaults.json",
    )
    settings_path = _normalize_path(
        os.environ.get("TIMELINE_FOR_WINDOWS_CODEX_SETTINGS_PATH"),
        str(repo_root / "settings.json"),
    )
    return RuntimePaths(
        outputs_root=outputs_root,
        appdata_root=appdata_root,
        runtime_defaults_path=runtime_defaults_path,
        settings_path=settings_path,
    )


def user_settings_path(runtime_paths: RuntimePaths | None = None) -> Path:
    runtime = runtime_paths or load_runtime_paths()
    return runtime.settings_path


def load_user_settings(runtime_paths: RuntimePaths | None = None) -> UserSettings:
    path = user_settings_path(runtime_paths)
    if not path.exists():
        return UserSettings()
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError):
        return UserSettings()
    if not isinstance(payload, dict):
        return UserSettings()
    return UserSettings.from_dict(payload)


def save_user_settings(
    settings: UserSettings,
    runtime_paths: RuntimePaths | None = None,
) -> Path:
    path = user_settings_path(runtime_paths)
    ensure_dir(path.parent)
    write_json_atomic(path, settings.to_dict())
    return path


def load_runtime_defaults(runtime_paths: RuntimePaths | None = None) -> RuntimeDefaults:
    runtime = runtime_paths or load_runtime_paths()
    for path in _candidate_runtime_defaults_paths(runtime.runtime_defaults_path):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue

        backup_paths = [
            str(item).strip()
            for item in (payload.get("default_backup_codex_home_paths") or [])
            if str(item).strip()
        ]
        redaction_profile = str(payload.get("default_redaction_profile") or "strict").strip().lower()
        if redaction_profile not in {"strict", "loose"}:
            redaction_profile = "strict"

        return RuntimeDefaults(
            default_primary_codex_home_path=str(
                payload.get("default_primary_codex_home_path") or "/input/codex-home"
            ).strip()
            or "/input/codex-home",
            default_backup_codex_home_paths=backup_paths,
            default_redaction_profile=redaction_profile,
            default_include_archived_sources=bool(
                payload.get("default_include_archived_sources", True)
            ),
            default_include_tool_outputs=bool(payload.get("default_include_tool_outputs", True)),
        )

    return RuntimeDefaults()


def _candidate_runtime_defaults_paths(configured_path: Path) -> list[Path]:
    candidates: list[Path] = [configured_path]
    repo_default = _repo_root() / "configs" / "runtime.defaults.json"
    if repo_default not in candidates:
        candidates.append(repo_default)
    return candidates


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)
