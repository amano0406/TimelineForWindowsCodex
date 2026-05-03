from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from zipfile import ZipFile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CODEX_HOME = REPO_ROOT / "tests" / "fixtures" / "codex-home-min"
FIXTURE_ARCHIVE_HOME = REPO_ROOT / "tests" / "fixtures" / "archived-root-min"
FIXTURE_THREAD_ID = "11111111-2222-3333-4444-555555555555"
FIXTURE_ARCHIVED_THREAD_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CLI_TIMEOUT_SECONDS = 180


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a local Windows cli.ps1 download smoke test through Docker Compose.",
    )
    parser.add_argument(
        "--preserve-output",
        action="store_true",
        help="Keep the temporary C:\\TimelineData smoke output for manual inspection.",
    )
    parser.add_argument(
        "--keep-compose-project",
        action="store_true",
        help="Do not remove the temporary Docker Compose project after the smoke test.",
    )
    args = parser.parse_args(argv)

    powershell = _resolve_powershell()
    timeline_data = _timeline_data_root()
    smoke_root = timeline_data / f"tfwc-cli-ps1-smoke-{int(time.time())}"
    master_root = smoke_root / "master"
    download_root = smoke_root / "downloads"
    settings_root = smoke_root / "settings"
    appdata_root = smoke_root / "app-data"
    shared_downloads_root = smoke_root / "shared-downloads"
    settings_path = settings_root / "settings.json"
    for directory in (master_root, download_root, settings_root, appdata_root, shared_downloads_root):
        directory.mkdir(parents=True, exist_ok=True)

    compose_project_name = f"tfwc-cli-ps1-smoke-{int(time.time())}"
    mount_env = _build_smoke_mount_env(
        timeline_data=timeline_data,
        settings_path=settings_path,
        appdata_root=appdata_root,
        shared_downloads_root=shared_downloads_root,
        compose_project_name=compose_project_name,
    )

    try:
        _write_settings(settings_path, master_root)
        _force_recreate_worker_service(mount_env)
        refresh = _json_from_stdout(
            _run_cli(powershell, ["items", "refresh", "--json"], mount_env).stdout
        )
        _assert_fixture_refresh_payload(refresh)
        download = _json_from_stdout(
            _run_cli(
                powershell,
                ["items", "download", "--to", _to_windows_path(download_root), "--json"],
                mount_env,
            ).stdout
        )
        archive_path = _latest_zip(download_root)
        _assert_fixture_download_payload(download, archive_path)
        _assert_master_output(master_root)
        _assert_download_archive(archive_path)
        print(
            json.dumps(
                {
                    "state": "ok",
                    "entrypoint": "cli.ps1",
                    "master_root": str(master_root),
                    "download_archive": str(archive_path),
                    "fixture_threads": [FIXTURE_THREAD_ID, FIXTURE_ARCHIVED_THREAD_ID],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        if not args.keep_compose_project:
            _cleanup_smoke_compose_project(mount_env)
        if not args.preserve_output:
            shutil.rmtree(smoke_root, ignore_errors=True)


def _resolve_powershell() -> str:
    if shutil.which("cmd.exe") and shutil.which("powershell.exe"):
        return "powershell.exe"

    candidates = ["powershell.exe", "powershell"]
    for candidate in candidates:
        if shutil.which(candidate):
            return candidate
    raise RuntimeError("PowerShell was not found. Run this smoke test on Windows or WSL with powershell.exe available.")


def _timeline_data_root() -> Path:
    if os.name == "nt":
        return Path("C:/TimelineData")
    if Path("/mnt/c").exists():
        return Path("/mnt/c/TimelineData")
    raise RuntimeError("This smoke test requires Windows C: drive access.")


def _build_smoke_mount_env(
    *,
    timeline_data: Path,
    settings_path: Path,
    appdata_root: Path,
    shared_downloads_root: Path,
    compose_project_name: str,
) -> dict[str, str]:
    return {
        "COMPOSE_PROJECT_NAME": compose_project_name,
        "HOST_TFWC_APP_DATA": _to_windows_path(appdata_root),
        "HOST_TFWC_SETTINGS_FILE": _to_windows_path(settings_path),
        "HOST_TFWC_DOWNLOADS": _to_windows_path(shared_downloads_root),
        "HOST_TIMELINE_DATA": _to_windows_path(timeline_data),
        "HOST_CODEX_HOME": _to_windows_path(FIXTURE_CODEX_HOME),
        "HOST_CODEX_BACKUP_HOME": _to_windows_path(FIXTURE_ARCHIVE_HOME),
        "HOST_CODEX_ROOT": _to_windows_path(REPO_ROOT / "tests" / "fixtures"),
    }


def _write_settings(settings_path: Path, master_root: Path) -> None:
    settings_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "outputRoot": _to_windows_path(master_root),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _run_cli(
    powershell: str,
    args: list[str],
    mount_env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    if shutil.which("cmd.exe"):
        return _run_cli_through_cmd(powershell, args, mount_env)

    env_script = " ".join(
        f"$env:{name}={_ps_quote(value)};"
        for name, value in mount_env.items()
    )
    args_script = " ".join(_ps_quote(arg) for arg in args)
    script = (
        f"{env_script} "
        f"& {_ps_quote(_to_windows_path(REPO_ROOT / 'cli.ps1'))} {args_script}; "
        "exit $LASTEXITCODE"
    )
    command = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=CLI_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "\n".join(
                [
                    f"Command failed: {' '.join(command)}",
                    f"exit_code: {completed.returncode}",
                    f"stdout: {completed.stdout}",
                    f"stderr: {completed.stderr}",
                    "Run .\\start.bat once if the worker image has not been built.",
                ]
            )
        )
    return completed


def _run_cli_through_cmd(
    powershell: str,
    args: list[str],
    mount_env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    env_script = "&&".join(
        f"set {name}={value}"
        for name, value in mount_env.items()
    )
    powershell_command = " ".join(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            _to_windows_path(REPO_ROOT / "cli.ps1"),
            *args,
        ]
    )
    command_text = f"{env_script}&&{powershell_command}"
    completed = subprocess.run(
        ["cmd.exe", "/c", command_text],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=CLI_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "\n".join(
                [
                    f"Command failed: {command_text}",
                    f"exit_code: {completed.returncode}",
                    f"stdout: {completed.stdout}",
                    f"stderr: {completed.stderr}",
                    "Run .\\start.bat once if the worker image has not been built.",
                ]
            )
        )
    return completed


def _force_recreate_worker_service(mount_env: dict[str, str]) -> None:
    if not shutil.which("cmd.exe"):
        return

    env_script = "&&".join(
        f"set {name}={value}"
        for name, value in mount_env.items()
    )
    project_name = mount_env.get("COMPOSE_PROJECT_NAME") or "tfwc-cli-ps1-smoke"
    command_text = (
        f"{env_script}&&docker compose -p {project_name} "
        "up -d --no-build --force-recreate --remove-orphans worker"
    )
    completed = subprocess.run(
        ["cmd.exe", "/c", command_text],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=CLI_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "\n".join(
                [
                    f"Command failed: {command_text}",
                    f"exit_code: {completed.returncode}",
                    f"stdout: {completed.stdout}",
                    f"stderr: {completed.stderr}",
                    "Run .\\start.bat once if the worker image has not been built.",
                ]
            )
        )


def _cleanup_smoke_compose_project(mount_env: dict[str, str]) -> None:
    if shutil.which("cmd.exe"):
        env_script = "&&".join(
            f"set {name}={value}"
            for name, value in mount_env.items()
        )
        project_name = mount_env.get("COMPOSE_PROJECT_NAME") or "tfwc-cli-ps1-smoke"
        command_text = f"{env_script}&&docker compose -p {project_name} down --remove-orphans -v"
        subprocess.run(
            ["cmd.exe", "/c", command_text],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLI_TIMEOUT_SECONDS,
        )
        return

    env = os.environ.copy()
    env.update(mount_env)
    command = [
        "docker",
        "compose",
        "-p",
        mount_env.get("COMPOSE_PROJECT_NAME") or "tfwc-cli-ps1-smoke",
        "down",
        "--remove-orphans",
        "-v",
    ]
    subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=CLI_TIMEOUT_SECONDS,
    )


def _assert_master_output(master_root: Path) -> None:
    deadline = time.time() + 10
    while True:
        missing: list[Path] = []
        for thread_id in (FIXTURE_THREAD_ID, FIXTURE_ARCHIVED_THREAD_ID):
            timeline_path = master_root / thread_id / "timeline.json"
            convert_info_path = master_root / thread_id / "convert_info.json"
            if not timeline_path.exists():
                missing.append(timeline_path)
            if not convert_info_path.exists():
                missing.append(convert_info_path)
        if not missing:
            return
        if time.time() >= deadline:
            raise AssertionError(f"Missing master output files: {missing}")
        time.sleep(0.25)


def _assert_download_archive(archive_path: Path) -> None:
    if not archive_path.exists():
        raise AssertionError(f"Download ZIP was not created: {archive_path}")
    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        required = {
            "README.md",
            f"items/{FIXTURE_THREAD_ID}/timeline.json",
            f"items/{FIXTURE_THREAD_ID}/convert_info.json",
            f"items/{FIXTURE_ARCHIVED_THREAD_ID}/timeline.json",
            f"items/{FIXTURE_ARCHIVED_THREAD_ID}/convert_info.json",
        }
        missing = sorted(required - names)
        if missing:
            raise AssertionError(f"Download ZIP is missing required entries: {missing}")
        if any(name.endswith("/thread.json") for name in names):
            raise AssertionError("Download ZIP must not contain legacy thread.json entries.")


def _assert_fixture_refresh_payload(payload: dict[str, Any]) -> None:
    expected_ids = {FIXTURE_THREAD_ID, FIXTURE_ARCHIVED_THREAD_ID}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    actual_ids = {str(item.get("thread_id") or "") for item in items if isinstance(item, dict)}
    if int(payload.get("thread_count") or 0) != 2 or actual_ids != expected_ids:
        raise AssertionError(
            "cli.ps1 smoke test must use fixture sources only. "
            f"thread_count={payload.get('thread_count')!r}, actual_ids={sorted(actual_ids)!r}"
        )


def _assert_fixture_download_payload(payload: dict[str, Any], archive_path: Path) -> None:
    if payload.get("state") != "completed":
        raise AssertionError(f"Download did not complete: {payload!r}")
    if int(payload.get("thread_count") or 0) != 2:
        raise AssertionError(f"Download should contain exactly 2 fixture threads: {payload!r}")
    if Path(str(payload.get("destination_path") or "")) != archive_path:
        raise AssertionError(
            f"Download payload destination does not match ZIP path: {payload.get('destination_path')} != {archive_path}"
        )


def _latest_zip(download_root: Path) -> Path:
    deadline = time.time() + 10
    while True:
        archives = sorted(download_root.glob("TimelineForWindowsCodex-export-*.zip"))
        if archives:
            return archives[-1]
        if time.time() >= deadline:
            raise AssertionError(f"No download ZIP was created in {download_root}")
        time.sleep(0.25)


def _json_from_stdout(stdout: str) -> dict[str, Any]:
    stripped = stdout.strip()
    start = stripped.find("{")
    if start < 0:
        raise AssertionError(f"Command stdout did not contain a JSON object: {stdout!r}")
    try:
        payload = json.loads(stripped[start:])
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Command stdout did not contain valid JSON: {stdout!r}") from exc
    if not isinstance(payload, dict):
        raise AssertionError(f"Command stdout JSON was not an object: {stdout!r}")
    return payload


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _to_windows_path(path: Path) -> str:
    text = str(path)
    if len(text) >= 3 and text[1] == ":":
        return text.replace("/", "\\")
    if text.startswith("/mnt/") and len(text) >= 7 and text[6] == "/":
        drive = text[5].upper()
        rest = text[7:].replace("/", "\\")
        return f"{drive}:\\{rest}"
    return text


if __name__ == "__main__":
    raise SystemExit(main())
