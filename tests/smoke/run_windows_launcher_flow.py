from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from run_cli_ps1_download import (
    CLI_TIMEOUT_SECONDS,
    FIXTURE_ARCHIVED_THREAD_ID,
    FIXTURE_THREAD_ID,
    REPO_ROOT,
    _assert_download_archive,
    _assert_fixture_download_payload,
    _assert_fixture_refresh_payload,
    _assert_master_output,
    _build_smoke_mount_env,
    _cleanup_smoke_compose_project,
    _json_from_stdout,
    _latest_zip,
    _timeline_data_root,
    _to_windows_path,
    _write_settings,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Windows launcher operational flow through start.bat, "
            "cli.bat, and stop.bat with fixture-only sources."
        ),
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

    if not shutil.which("cmd.exe"):
        raise RuntimeError("This smoke test requires cmd.exe because it verifies .bat launchers.")

    timestamp = int(time.time())
    timeline_data = _timeline_data_root()
    smoke_root = timeline_data / f"tfwc-launcher-smoke-{timestamp}"
    master_root = smoke_root / "master"
    download_root = smoke_root / "downloads"
    settings_root = smoke_root / "settings"
    appdata_root = smoke_root / "app-data"
    shared_downloads_root = smoke_root / "shared-downloads"
    settings_path = settings_root / "settings.json"
    for directory in (master_root, download_root, settings_root, appdata_root, shared_downloads_root):
        directory.mkdir(parents=True, exist_ok=True)

    mount_env = _build_smoke_mount_env(
        timeline_data=timeline_data,
        settings_path=settings_path,
        appdata_root=appdata_root,
        shared_downloads_root=shared_downloads_root,
        compose_project_name=f"tfwc-launcher-smoke-{timestamp}",
    )

    stop_exercised = False
    try:
        _write_settings(settings_path, master_root)
        start_result = _run_batch("start.bat", [], mount_env)
        if "TimelineForWindowsCodex worker-1 was started." not in start_result.stdout:
            raise AssertionError(f"start.bat did not report successful startup: {start_result.stdout!r}")

        status = _json_from_stdout(_run_batch("cli.bat", ["settings", "status", "--json"], mount_env).stdout)
        _assert_settings_status(status, master_root)

        refresh = _json_from_stdout(_run_batch("cli.bat", ["items", "refresh", "--json"], mount_env).stdout)
        _assert_fixture_refresh_payload(refresh)

        download = _json_from_stdout(
            _run_batch(
                "cli.bat",
                ["items", "download", "--to", _to_windows_path(download_root), "--json"],
                mount_env,
            ).stdout
        )
        archive_path = _latest_zip(download_root)
        _assert_fixture_download_payload(download, archive_path)
        _assert_master_output(master_root)
        _assert_download_archive(archive_path)

        _run_batch("stop.bat", [], mount_env)
        stop_exercised = True

        print(
            json.dumps(
                {
                    "state": "ok",
                    "entrypoint": "start.bat / cli.bat / stop.bat",
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
        if not stop_exercised:
            _run_batch_ignore_failure("stop.bat", [], mount_env)
        if not args.keep_compose_project:
            _cleanup_smoke_compose_project(mount_env)
        if not args.preserve_output:
            shutil.rmtree(smoke_root, ignore_errors=True)


def _run_batch(
    script_name: str,
    args: list[str],
    mount_env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    command_text = _build_batch_command(script_name, args, mount_env)
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", command_text],
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
                ]
            )
        )
    return completed


def _run_batch_ignore_failure(
    script_name: str,
    args: list[str],
    mount_env: dict[str, str],
) -> None:
    command_text = _build_batch_command(script_name, args, mount_env)
    subprocess.run(
        ["cmd.exe", "/d", "/c", command_text],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=CLI_TIMEOUT_SECONDS,
    )


def _build_batch_command(script_name: str, args: list[str], mount_env: dict[str, str]) -> str:
    env_script = "&&".join(f"set {name}={value}" for name, value in mount_env.items())
    batch_path = _to_windows_path(REPO_ROOT / script_name)
    batch_args = " ".join(_cmd_quote(arg) for arg in args)
    if batch_args:
        return f"{env_script}&&call {batch_path} {batch_args}"
    return f"{env_script}&&call {batch_path}"


def _cmd_quote(value: str) -> str:
    text = str(value)
    if not text:
        return '""'
    if any(character.isspace() or character in '&()[]{}^=;!\'"+,`~|<>' for character in text):
        return '"' + text.replace('"', '""') + '"'
    return text


def _assert_settings_status(payload: dict[str, Any], master_root: Path) -> None:
    output_root = str(payload.get("outputRoot") or "")
    if "tfwc-launcher-smoke-" not in output_root:
        raise AssertionError(f"settings status did not use the temporary outputRoot: {payload!r}")
    expected_suffix = str(master_root).replace("\\", "/").split("/TimelineData/", 1)[-1]
    if expected_suffix.replace("\\", "/") not in output_root.replace("\\", "/"):
        raise AssertionError(f"settings status outputRoot does not match the smoke master: {payload!r}")
    source_roots = payload.get("sourceRoots")
    if source_roots != ["/input/codex-home", "/input/codex-backup"]:
        raise AssertionError(f"settings status should report fixed fixture source mounts: {payload!r}")


if __name__ == "__main__":
    raise SystemExit(main())
