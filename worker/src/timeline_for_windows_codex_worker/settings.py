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
    source_roots: list[str] | None = None

    def __post_init__(self) -> None:
        if self.source_roots is None:
            self.source_roots = ["/input/codex-home", "/input/codex-backup"]

    @property
    def primary_source_root(self) -> str:
        return (self.source_roots or ["/input/codex-home"])[0]

    @property
    def backup_source_roots(self) -> list[str]:
        return list((self.source_roots or [])[1:])


@dataclass
class UserSettings:
    schema_version: int = 1
    output_root: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "UserSettings":
        return cls(
            schema_version=int(payload.get("schemaVersion") or 1),
            output_root=str(payload.get("outputRoot") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "outputRoot": self.output_root,
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
        "/mnt/c/TimelineData/windows-codex",
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

        return RuntimeDefaults(
            source_roots=_parse_path_list(payload.get("sourceRoots")),
        )

    return RuntimeDefaults()


def _candidate_runtime_defaults_paths(configured_path: Path) -> list[Path]:
    candidates: list[Path] = [configured_path]
    repo_default = _repo_root() / "configs" / "runtime.defaults.json"
    if repo_default not in candidates:
        candidates.append(repo_default)
    return candidates


def _parse_path_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    paths: list[str] = []
    for item in value:
        path = str(item or "").strip()
        if path:
            paths.append(path)
    return paths
