from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_SRC = REPO_ROOT / "worker" / "src"
DEFAULT_SOURCE_ROOTS = [
    Path("/mnt/c/Users/amano/.codex"),
    Path("/mnt/c/Codex/archive/migration-backup-2026-03-27/codex-home"),
]
REQUIRED_ZIP_ENTRIES = {
    "README.md",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a production-like refresh smoke test against real Codex history sources.",
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
    temp_root = Path(tempfile.mkdtemp(prefix="tfwc-production-like-"))
    appdata_root = temp_root / "appdata"
    settings_path = temp_root / "settings.json"
    outputs_root = temp_root / "outputs"

    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(WORKER_SRC)
        env["TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN"] = "1"
        env["TIMELINE_FOR_WINDOWS_CODEX_APPDATA_ROOT"] = str(appdata_root)
        env["TIMELINE_FOR_WINDOWS_CODEX_SETTINGS_PATH"] = str(settings_path)
        env["TIMELINE_FOR_WINDOWS_CODEX_OUTPUTS_ROOT"] = str(temp_root / "ignored")

        settings_payloads = []
        for source_root in source_roots:
            settings_payloads.append(
                _run_json(
                    [
                        sys.executable,
                        "-m",
                        "timeline_for_windows_codex_worker",
                        "settings",
                        "inputs",
                        "add",
                        str(source_root),
                        "--format",
                        "json",
                    ],
                    env,
                )
            )
        settings_payloads.append(
            _run_json(
                [
                    sys.executable,
                    "-m",
                    "timeline_for_windows_codex_worker",
                    "settings",
                    "master",
                    "set",
                    str(outputs_root),
                    "--format",
                    "json",
                ],
                env,
            )
        )

        refresh_payloads: list[dict[str, Any]] = []
        inspections: list[dict[str, Any]] = []
        for index in range(runs):
            refresh_payload = _run_json(
                [
                    sys.executable,
                    "-m",
                    "timeline_for_windows_codex_worker",
                    "items",
                    "refresh",
                    "--download-to",
                    str(temp_root / f"download-{index + 1}"),
                    "--json",
                ],
                env,
            )
            refresh_payloads.append(refresh_payload)
            inspections.append(_inspect_refresh(refresh_payload))
        _assert_valid(refresh_payloads, inspections)

        summary = {
            "state": "ok",
            "production_like": True,
            "source_roots": [str(path) for path in source_roots],
            "runs": refresh_payloads,
            "inspections": inspections,
            "output_root": str(outputs_root),
            "output_preserved": args.preserve_output,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        if not args.preserve_output:
            shutil.rmtree(temp_root, ignore_errors=True)


def _resolve_source_roots(values: list[str]) -> list[Path]:
    candidates = [Path(value).expanduser().resolve() for value in values]
    if not candidates:
        candidates = [path for path in DEFAULT_SOURCE_ROOTS if path.exists()]
    return [path for path in candidates if path.exists() and path.is_dir()]


def _run_json(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
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
    return json.loads(completed.stdout)


def _inspect_refresh(payload: dict[str, Any]) -> dict[str, Any]:
    master_root = Path(str(payload.get("master_root") or ""))
    download = payload.get("download") if isinstance(payload.get("download"), dict) else {}
    archive_path = Path(str(download.get("destination_path") or ""))
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
