from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_ROOTS = [
    Path("/mnt/c/Users/amano/.codex"),
    Path("/mnt/c/Codex/archive/migration-backup-2026-03-27/codex-home"),
]
CONTAINER_SETTINGS_DIR = PurePosixPath("/smoke/settings")
CONTAINER_APPDATA_DIR = PurePosixPath("/smoke/appdata")
CONTAINER_OUTPUT_DIR = PurePosixPath("/smoke/output")
CONTAINER_IGNORED_OUTPUTS_DIR = PurePosixPath("/smoke/ignored")
REQUIRED_ZIP_ENTRIES = {
    "README.md",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a Docker Compose production-like refresh smoke test against real Codex history sources.",
    )
    parser.add_argument(
        "--source-root",
        action="append",
        default=[],
        help="Real Codex history source root. Can be passed multiple times.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=2,
        help="Number of refresh runs. Use 2 to verify incremental reuse.",
    )
    parser.add_argument(
        "--preserve-output",
        action="store_true",
        help="Keep the temporary output directory for manual inspection.",
    )
    args = parser.parse_args(argv)

    source_roots = _resolve_source_roots(args.source_root)
    if not source_roots:
        print("No source roots exist. Pass --source-root explicitly.", file=sys.stderr)
        return 1

    runs = max(1, args.runs)
    temp_root = Path(tempfile.mkdtemp(prefix="tfwc-docker-smoke-"))
    settings_dir = temp_root / "settings"
    appdata_dir = temp_root / "appdata"
    output_dir = temp_root / "output"
    ignored_outputs_dir = temp_root / "ignored"
    for directory in (settings_dir, appdata_dir, output_dir, ignored_outputs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    try:
        source_mounts = _build_source_mounts(source_roots)
        for source_mount in source_mounts:
            _run_compose_json(
                [
                    "settings",
                    "inputs",
                    "add",
                    str(source_mount.container_path),
                    "--format",
                    "json",
                ],
                settings_dir=settings_dir,
                appdata_dir=appdata_dir,
                output_dir=output_dir,
                ignored_outputs_dir=ignored_outputs_dir,
                source_mounts=source_mounts,
            )

        _run_compose_json(
            [
                "settings",
                "master",
                "set",
                str(CONTAINER_OUTPUT_DIR),
                "--format",
                "json",
            ],
            settings_dir=settings_dir,
            appdata_dir=appdata_dir,
            output_dir=output_dir,
            ignored_outputs_dir=ignored_outputs_dir,
            source_mounts=source_mounts,
        )

        refresh_payloads: list[dict[str, Any]] = []
        inspections: list[dict[str, Any]] = []
        for _ in range(runs):
            refresh_payload = _run_compose_json(
                ["items", "refresh", "--json"],
                settings_dir=settings_dir,
                appdata_dir=appdata_dir,
                output_dir=output_dir,
                ignored_outputs_dir=ignored_outputs_dir,
                source_mounts=source_mounts,
            )
            refresh_payloads.append(refresh_payload)
            inspections.append(_inspect_refresh(refresh_payload, output_dir))
        _assert_valid(refresh_payloads, inspections)

        summary = {
            "state": "ok",
            "production_like": True,
            "runtime": "docker_compose",
            "source_roots": [str(path) for path in source_roots],
            "runs": refresh_payloads,
            "inspections": inspections,
            "host_output_root": str(output_dir),
            "output_preserved": args.preserve_output,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        if not args.preserve_output:
            shutil.rmtree(temp_root, ignore_errors=True)


class SourceMount:
    def __init__(self, host_path: Path, container_path: PurePosixPath) -> None:
        self.host_path = host_path
        self.container_path = container_path


def _resolve_source_roots(values: list[str]) -> list[Path]:
    candidates = [Path(value).expanduser().resolve() for value in values]
    if not candidates:
        candidates = [path for path in DEFAULT_SOURCE_ROOTS if path.exists()]
    return [path for path in candidates if path.exists() and path.is_dir()]


def _build_source_mounts(source_roots: list[Path]) -> list[SourceMount]:
    return [
        SourceMount(host_path=source_root, container_path=PurePosixPath(f"/smoke/source-{index}"))
        for index, source_root in enumerate(source_roots)
    ]


def _run_compose_json(
    command: list[str],
    *,
    settings_dir: Path,
    appdata_dir: Path,
    output_dir: Path,
    ignored_outputs_dir: Path,
    source_mounts: list[SourceMount],
) -> dict[str, Any]:
    compose_command = [
        "docker",
        "compose",
        "run",
        "--rm",
        "--no-deps",
        "-e",
        f"TIMELINE_FOR_WINDOWS_CODEX_SETTINGS_PATH={CONTAINER_SETTINGS_DIR / 'settings.json'}",
        "-e",
        f"TIMELINE_FOR_WINDOWS_CODEX_APPDATA_ROOT={CONTAINER_APPDATA_DIR}",
        "-e",
        f"TIMELINE_FOR_WINDOWS_CODEX_OUTPUTS_ROOT={CONTAINER_IGNORED_OUTPUTS_DIR}",
        "-v",
        f"{settings_dir}:{CONTAINER_SETTINGS_DIR}",
        "-v",
        f"{appdata_dir}:{CONTAINER_APPDATA_DIR}",
        "-v",
        f"{output_dir}:{CONTAINER_OUTPUT_DIR}",
        "-v",
        f"{ignored_outputs_dir}:{CONTAINER_IGNORED_OUTPUTS_DIR}",
    ]
    for source_mount in source_mounts:
        compose_command.extend(["-v", f"{source_mount.host_path}:{source_mount.container_path}:ro"])
    compose_command.extend(["worker", *command])

    completed = subprocess.run(
        compose_command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "\n".join(
                [
                    f"Command failed: {' '.join(compose_command)}",
                    f"exit_code: {completed.returncode}",
                    f"stdout: {completed.stdout}",
                    f"stderr: {completed.stderr}",
                ]
            )
        )
    return json.loads(completed.stdout)


def _inspect_refresh(payload: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    run_dir = _container_output_path_to_host(str(payload.get("run_directory") or ""), output_dir)
    archive_path = _container_output_path_to_host(str(payload.get("archive_path") or ""), output_dir)
    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    update_manifest = json.loads((run_dir / "update_manifest.json").read_text(encoding="utf-8"))
    current = json.loads((run_dir.parent / "current.json").read_text(encoding="utf-8"))
    fidelity = json.loads((run_dir / "fidelity_report.json").read_text(encoding="utf-8"))
    processing_profile = json.loads((run_dir / "processing_profile.json").read_text(encoding="utf-8"))

    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        thread_json_count = len(
            [
                name
                for name in names
                if name.endswith("/thread.json")
            ]
        )
        convert_json_count = len([name for name in names if name.endswith("/convert.json")])
        missing_zip_entries = sorted(REQUIRED_ZIP_ENTRIES - names)

    return {
        "refresh_id": payload.get("refresh_id"),
        "run_directory_exists": run_dir.exists(),
        "archive_exists": archive_path.exists(),
        "archive_name": archive_path.name,
        "status_state": status.get("state"),
        "result_state": result.get("state"),
        "thread_count": payload.get("thread_count"),
        "event_count": payload.get("event_count"),
        "update_counts": update_manifest.get("counts"),
        "current_processing_mode": current.get("processing_mode"),
        "current_run_id": current.get("job_id"),
        "current_reused_thread_count": current.get("reused_thread_count"),
        "current_rendered_thread_count": current.get("rendered_thread_count"),
        "fidelity_thread_count": fidelity.get("thread_count"),
        "fidelity_source_types": fidelity.get("source_types"),
        "processing_profile_thread_count": processing_profile.get("thread_count"),
        "slowest_thread_count": len(processing_profile.get("slowest_threads") or []),
        "missing_zip_entries": missing_zip_entries,
        "zip_thread_json_count": thread_json_count,
        "zip_convert_json_count": convert_json_count,
    }


def _container_output_path_to_host(container_path: str, output_dir: Path) -> Path:
    if not container_path.startswith(str(CONTAINER_OUTPUT_DIR)):
        raise ValueError(f"Unexpected container output path: {container_path}")
    relative_path = PurePosixPath(container_path).relative_to(CONTAINER_OUTPUT_DIR)
    return output_dir.joinpath(*relative_path.parts)


def _assert_valid(
    refresh_payloads: list[dict[str, Any]],
    inspections: list[dict[str, Any]],
) -> None:
    for payload, inspection in zip(refresh_payloads, inspections, strict=True):
        if payload.get("state") != "completed":
            raise AssertionError(f"Refresh did not complete: {payload}")
        for key in ("status_state", "result_state"):
            if inspection.get(key) != "completed":
                raise AssertionError(f"{key} was not completed: {inspection}")
        if inspection.get("missing_zip_entries"):
            raise AssertionError(f"ZIP is missing required files: {inspection}")
        if int(inspection.get("thread_count") or 0) <= 0:
            raise AssertionError(f"No threads were exported: {inspection}")
        if inspection.get("zip_thread_json_count") != inspection.get("thread_count"):
            raise AssertionError(f"Thread JSON count mismatch: {inspection}")
        if inspection.get("zip_convert_json_count") != inspection.get("thread_count"):
            raise AssertionError(f"Convert JSON count mismatch: {inspection}")
        if inspection.get("processing_profile_thread_count") != inspection.get("thread_count"):
            raise AssertionError(f"Processing profile thread count mismatch: {inspection}")
        if inspection.get("current_run_id") != payload.get("run_id"):
            raise AssertionError(f"Current pointer does not match refresh: {inspection}")

    if len(inspections) >= 2:
        second_counts = inspections[1].get("update_counts") or {}
        unchanged = int(second_counts.get("unchanged") or 0)
        if unchanged <= 0:
            raise AssertionError(f"Second refresh did not reuse unchanged threads: {inspections[1]}")


if __name__ == "__main__":
    raise SystemExit(main())
