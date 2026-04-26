from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    outputs_root: Path
    appdata_root: Path
    runtime_defaults_path: Path


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


def _normalize_path(value: str | None, fallback: str) -> Path:
    raw = (value or fallback).strip()
    return Path(raw or fallback).resolve()


def load_runtime_paths() -> RuntimePaths:
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
    return RuntimePaths(
        outputs_root=outputs_root,
        appdata_root=appdata_root,
        runtime_defaults_path=runtime_defaults_path,
    )


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
    repo_default = Path(__file__).resolve().parents[3] / "configs" / "runtime.defaults.json"
    if repo_default not in candidates:
        candidates.append(repo_default)
    return candidates
