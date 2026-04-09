from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    outputs_root: Path
    appdata_root: Path
    runtime_defaults_path: Path


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
