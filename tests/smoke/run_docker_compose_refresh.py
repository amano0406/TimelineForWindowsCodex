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
CONTAINER_CONFIG_DIR = PurePosixPath("/smoke/config")
CONTAINER_APPDATA_DIR = PurePosixPath("/smoke/appdata")
CONTAINER_OUTPUT_DIR = PurePosixPath("/smoke/output")
CONTAINER_IGNORED_OUTPUTS_DIR = PurePosixPath("/smoke/ignored")
CONTAINER_DOWNLOAD_DIR = PurePosixPath("/smoke/downloads")
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
    parser.add_argument(
        "--include-full-payload",
        action="store_true",
        help="Print full refresh payloads including item details. Default output is compact.",
    )
    args = parser.parse_args(argv)

    source_roots = _resolve_source_roots(args.source_root)
    if not source_roots:
        print("No source roots exist. Pass --source-root explicitly.", file=sys.stderr)
        return 1

    runs = max(1, args.runs)
    temp_root = Path(tempfile.mkdtemp(prefix="tfwc-docker-smoke-"))
    settings_dir = temp_root / "settings"
    config_dir = temp_root / "config"
    appdata_dir = temp_root / "appdata"
    output_dir = temp_root / "output"
    ignored_outputs_dir = temp_root / "ignored"
    download_dir = temp_root / "downloads"
    for directory in (settings_dir, config_dir, appdata_dir, output_dir, ignored_outputs_dir, download_dir):
        directory.mkdir(parents=True, exist_ok=True)
    compose_file = temp_root / "docker-compose.smoke.yml"
    project_name = f"tfwc-smoke-{temp_root.name.lower()}"

    try:
        source_mounts = _build_source_mounts(source_roots)
        _write_smoke_settings(settings_dir)
        _write_smoke_runtime_defaults(config_dir, source_mounts)
        _write_smoke_compose_file(
            compose_file=compose_file,
            settings_dir=settings_dir,
            config_dir=config_dir,
            appdata_dir=appdata_dir,
            output_dir=output_dir,
            ignored_outputs_dir=ignored_outputs_dir,
            download_dir=download_dir,
            source_mounts=source_mounts,
        )
        _run_compose_process(
            [*_compose_base_command(compose_file, project_name), "up", "-d", "--build", "worker"],
            capture_json=False,
        )

        refresh_payloads: list[dict[str, Any]] = []
        inspections: list[dict[str, Any]] = []
        for index in range(runs):
            refresh_payload = _run_compose_json(
                [
                    "items",
                    "refresh",
                    "--download-to",
                    str(CONTAINER_DOWNLOAD_DIR / f"download-{index + 1}"),
                    "--json",
                ],
                settings_dir=settings_dir,
                appdata_dir=appdata_dir,
                output_dir=output_dir,
                ignored_outputs_dir=ignored_outputs_dir,
                download_dir=download_dir,
                source_mounts=source_mounts,
                compose_file=compose_file,
                project_name=project_name,
            )
            refresh_payloads.append(refresh_payload)
            inspections.append(_inspect_refresh(refresh_payload, output_dir, download_dir))
        _assert_valid(refresh_payloads, inspections)

        summary: dict[str, Any] = {
            "state": "ok",
            "production_like": True,
            "runtime": "docker_compose",
            "source_roots": [str(path) for path in source_roots],
            "runs": [
                _summarize_refresh_payload(payload, inspection)
                for payload, inspection in zip(refresh_payloads, inspections, strict=True)
            ],
            "inspections": inspections,
            "host_output_root": str(output_dir),
            "output_preserved": args.preserve_output,
        }
        if args.include_full_payload:
            summary["full_payloads"] = refresh_payloads
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        if compose_file.exists():
            _run_compose_process(
                [*_compose_base_command(compose_file, project_name), "down", "--remove-orphans", "-v", "--rmi", "local"],
                capture_json=False,
                check=False,
            )
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
    download_dir: Path,
    source_mounts: list[SourceMount],
    compose_file: Path,
    project_name: str,
) -> dict[str, Any]:
    compose_command = [
        *_compose_base_command(compose_file, project_name),
        "exec",
        "-T",
        "worker",
        "python",
        "-m",
        "timeline_for_windows_codex_worker",
        *command,
    ]
    completed = _run_compose_process(compose_command, capture_json=True)
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


def _write_smoke_settings(settings_dir: Path) -> None:
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "outputRoot": str(CONTAINER_OUTPUT_DIR),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_smoke_runtime_defaults(config_dir: Path, source_mounts: list[SourceMount]) -> None:
    (config_dir / "runtime.defaults.json").write_text(
        json.dumps(
            {
                "sourceRoots": [str(source_mount.container_path) for source_mount in source_mounts],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_smoke_compose_file(
    *,
    compose_file: Path,
    settings_dir: Path,
    config_dir: Path,
    appdata_dir: Path,
    output_dir: Path,
    ignored_outputs_dir: Path,
    download_dir: Path,
    source_mounts: list[SourceMount],
) -> None:
    volume_lines = [
        f"      - {_quoted_volume(settings_dir, CONTAINER_SETTINGS_DIR)}",
        f"      - {_quoted_volume(config_dir, CONTAINER_CONFIG_DIR, read_only=True)}",
        f"      - {_quoted_volume(appdata_dir, CONTAINER_APPDATA_DIR)}",
        f"      - {_quoted_volume(output_dir, CONTAINER_OUTPUT_DIR)}",
        f"      - {_quoted_volume(ignored_outputs_dir, CONTAINER_IGNORED_OUTPUTS_DIR)}",
        f"      - {_quoted_volume(download_dir, CONTAINER_DOWNLOAD_DIR)}",
    ]
    for source_mount in source_mounts:
        volume_lines.append(f"      - {_quoted_volume(source_mount.host_path, source_mount.container_path, read_only=True)}")

    compose_file.write_text(
        "\n".join(
            [
                "services:",
                "  worker:",
                "    build:",
                f"      context: {_yaml_string(REPO_ROOT)}",
                f"      dockerfile: {_yaml_string('docker/worker.Dockerfile')}",
                "    entrypoint: [\"sleep\", \"infinity\"]",
                "    environment:",
                "      TIMELINE_FOR_WINDOWS_CODEX_RUNTIME: docker",
                f"      TIMELINE_FOR_WINDOWS_CODEX_RUNTIME_DEFAULTS: {_yaml_string(CONTAINER_CONFIG_DIR / 'runtime.defaults.json')}",
                f"      TIMELINE_FOR_WINDOWS_CODEX_SETTINGS_PATH: {_yaml_string(CONTAINER_SETTINGS_DIR / 'settings.json')}",
                f"      TIMELINE_FOR_WINDOWS_CODEX_APPDATA_ROOT: {_yaml_string(CONTAINER_APPDATA_DIR)}",
                f"      TIMELINE_FOR_WINDOWS_CODEX_OUTPUTS_ROOT: {_yaml_string(CONTAINER_IGNORED_OUTPUTS_DIR)}",
                "    volumes:",
                *volume_lines,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _compose_base_command(compose_file: Path, project_name: str) -> list[str]:
    return ["docker", "compose", "-p", project_name, "-f", str(compose_file)]


def _run_compose_process(
    command: list[str],
    *,
    capture_json: bool,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            "\n".join(
                [
                    f"Command failed: {' '.join(command)}",
                    f"exit_code: {completed.returncode}",
                    f"stdout: {completed.stdout}",
                    f"stderr: {completed.stderr}",
                ]
            )
        )
    if capture_json:
        return completed
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed


def _quoted_volume(host_path: Path, container_path: PurePosixPath, *, read_only: bool = False) -> str:
    suffix = ":ro" if read_only else ""
    return _yaml_string(f"{host_path}:{container_path}{suffix}")


def _yaml_string(value: object) -> str:
    return json.dumps(str(value))


def _inspect_refresh(payload: dict[str, Any], output_dir: Path, download_dir: Path) -> dict[str, Any]:
    master_root = _container_output_path_to_host(str(payload.get("master_root") or ""), output_dir)
    download = payload.get("download") if isinstance(payload.get("download"), dict) else {}
    archive_path = _container_download_path_to_host(str(download.get("destination_path") or ""), download_dir)
    master_timeline_json_count = len(list(master_root.glob("*/timeline.json")))
    master_convert_info_count = len(list(master_root.glob("*/convert_info.json")))

    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        timeline_json_count = len(
            [
                name
                for name in names
                if name.endswith("/timeline.json")
            ]
        )
        convert_json_count = len([name for name in names if name.endswith("/convert_info.json")])
        missing_zip_entries = sorted(REQUIRED_ZIP_ENTRIES - names)

    return {
        "refresh_id": payload.get("refresh_id"),
        "master_root_exists": master_root.exists(),
        "archive_exists": archive_path.exists(),
        "archive_name": archive_path.name,
        "thread_count": payload.get("thread_count"),
        "message_count": payload.get("message_count"),
        "update_counts": payload.get("update_counts"),
        "processing_mode": payload.get("processing_mode"),
        "reused_thread_count": payload.get("reused_thread_count"),
        "rendered_thread_count": payload.get("rendered_thread_count"),
        "master_timeline_json_count": master_timeline_json_count,
        "master_convert_info_count": master_convert_info_count,
        "missing_zip_entries": missing_zip_entries,
        "zip_timeline_json_count": timeline_json_count,
        "zip_convert_json_count": convert_json_count,
    }


def _summarize_refresh_payload(payload: dict[str, Any], inspection: dict[str, Any]) -> dict[str, Any]:
    return {
        "refresh_id": payload.get("refresh_id"),
        "state": payload.get("state"),
        "master_root": payload.get("master_root"),
        "completed_at": payload.get("completed_at"),
        "thread_count": payload.get("thread_count"),
        "message_count": payload.get("message_count"),
        "attachment_count": payload.get("attachment_count"),
        "update_counts": payload.get("update_counts"),
        "processing_mode": payload.get("processing_mode"),
        "reused_thread_count": payload.get("reused_thread_count"),
        "rendered_thread_count": payload.get("rendered_thread_count"),
        "processing_duration_ms": payload.get("processing_duration_ms"),
        "download": {
            "state": _download_payload(payload).get("state"),
            "destination_path": _download_payload(payload).get("destination_path"),
            "thread_count": _download_payload(payload).get("thread_count"),
            "message_count": _download_payload(payload).get("message_count"),
            "attachment_count": _download_payload(payload).get("attachment_count"),
        },
        "inspection": inspection,
    }


def _download_payload(payload: dict[str, Any]) -> dict[str, Any]:
    download = payload.get("download")
    return download if isinstance(download, dict) else {}


def _container_output_path_to_host(container_path: str, output_dir: Path) -> Path:
    if not container_path.startswith(str(CONTAINER_OUTPUT_DIR)):
        raise ValueError(f"Unexpected container output path: {container_path}")
    relative_path = PurePosixPath(container_path).relative_to(CONTAINER_OUTPUT_DIR)
    return output_dir.joinpath(*relative_path.parts)


def _container_download_path_to_host(container_path: str, download_dir: Path) -> Path:
    if not container_path.startswith(str(CONTAINER_DOWNLOAD_DIR)):
        raise ValueError(f"Unexpected container download path: {container_path}")
    relative_path = PurePosixPath(container_path).relative_to(CONTAINER_DOWNLOAD_DIR)
    return download_dir.joinpath(*relative_path.parts)


def _assert_valid(
    refresh_payloads: list[dict[str, Any]],
    inspections: list[dict[str, Any]],
) -> None:
    for payload, inspection in zip(refresh_payloads, inspections, strict=True):
        if payload.get("state") != "completed":
            raise AssertionError(f"Refresh did not complete: {payload}")
        if inspection.get("missing_zip_entries"):
            raise AssertionError(f"ZIP is missing required files: {inspection}")
        if int(inspection.get("thread_count") or 0) <= 0:
            raise AssertionError(f"No threads were exported: {inspection}")
        if inspection.get("master_timeline_json_count") != inspection.get("thread_count"):
            raise AssertionError(f"Master timeline JSON count mismatch: {inspection}")
        if inspection.get("master_convert_info_count") != inspection.get("thread_count"):
            raise AssertionError(f"Master convert_info JSON count mismatch: {inspection}")
        if inspection.get("zip_timeline_json_count") != inspection.get("thread_count"):
            raise AssertionError(f"Timeline JSON count mismatch: {inspection}")
        if inspection.get("zip_convert_json_count") != inspection.get("thread_count"):
            raise AssertionError(f"Convert JSON count mismatch: {inspection}")

    if len(inspections) >= 2:
        second_counts = inspections[1].get("update_counts") or {}
        unchanged = int(second_counts.get("unchanged") or 0)
        if unchanged <= 0:
            raise AssertionError(f"Second refresh did not reuse unchanged threads: {inspections[1]}")


if __name__ == "__main__":
    raise SystemExit(main())
