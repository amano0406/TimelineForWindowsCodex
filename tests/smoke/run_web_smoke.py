from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_DOTNET = Path("/mnt/c/Program Files/dotnet/dotnet.exe")
WINDOWS_CMD = Path("/mnt/c/Windows/System32/cmd.exe")
WINDOWS_TASKKILL = Path("/mnt/c/Windows/System32/taskkill.exe")
WINDOWS_CURL = Path("/mnt/c/Windows/System32/curl.exe")
WINDOWS_DOTNET_CMD = r"C:\Progra~1\dotnet\dotnet.exe"
WEB_PROJECT = REPO_ROOT / "web" / "WindowsCodex2Timeline.Web.csproj"
WEB_ROOT = REPO_ROOT / "web"
WEB_DLL = REPO_ROOT / "web" / "bin" / "Debug" / "net10.0" / "WindowsCodex2Timeline.Web.dll"
WORKER_SRC = REPO_ROOT / "worker" / "src"
FIXTURE_CODEX_HOME = REPO_ROOT / "tests" / "fixtures" / "codex-home-min"
THREAD_TITLE = "Codex timeline sample thread"
ARCHIVED_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "archived-root-min"
ARCHIVED_THREAD_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ARCHIVED_THREAD_TITLE = "Archived timeline source"

TOKEN_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', re.IGNORECASE)
THREAD_RE = re.compile(r'name="SelectedThreadIds"[^>]*value="([^"]+)"', re.IGNORECASE)
JOB_ID_RE = re.compile(r"/jobs/([^/?]+)")


def main() -> int:
    if not WINDOWS_DOTNET.exists():
        raise SystemExit(f"Windows dotnet was not found: {WINDOWS_DOTNET}")

    ensure_tmp_root()

    with tempfile.TemporaryDirectory(
        dir=str(REPO_ROOT / ".tmp"),
        prefix="web-smoke-",
        ignore_cleanup_errors=True,
    ) as temp_root:
        temp_root_path = Path(temp_root)
        runtime_defaults_path = temp_root_path / "runtime.defaults.json"
        app_data_root = temp_root_path / "app-data"
        outputs_root = temp_root_path / "outputs"
        web_log_path = temp_root_path / "web.log"
        port = allocate_port()
        base_url = f"http://127.0.0.1:{port}"

        runtime_defaults_path.write_text(
            json.dumps(
                {
                    "default_primary_codex_home_path": to_windows_path(FIXTURE_CODEX_HOME),
                    "default_backup_codex_home_paths": [],
                    "default_enrichment_root_paths": [],
                    "default_redaction_profile": "strict",
                    "default_include_archived_sources": True,
                    "default_include_tool_outputs": True,
                    "ui_language": "en",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        build_web_app()

        process = start_web_server(
            base_url=base_url,
            runtime_defaults_path=runtime_defaults_path,
            app_data_root=app_data_root,
            outputs_root=outputs_root,
            log_path=web_log_path,
        )
        try:
            wait_for_server(base_url, process, web_log_path)
            run_smoke_flow(
                base_url=base_url,
                temp_root=temp_root_path,
                outputs_root=outputs_root,
            )
        finally:
            stop_process(process)

    print("Web smoke passed.")
    return 0


def build_web_app() -> None:
    subprocess.run(
        [str(WINDOWS_DOTNET), "build", to_windows_path(WEB_PROJECT)],
        check=True,
    )


def start_web_server(
    *,
    base_url: str,
    runtime_defaults_path: Path,
    app_data_root: Path,
    outputs_root: Path,
    log_path: Path,
) -> subprocess.Popen[str]:
    log_handle = log_path.open("w", encoding="utf-8")
    command = " && ".join(
        [
            f"cd /d {to_windows_path(WEB_ROOT)}",
            "set ASPNETCORE_ENVIRONMENT=Development",
            f"set ASPNETCORE_URLS={base_url}",
            f"set WINDOWSCODEX2TIMELINE_RUNTIME_DEFAULTS={to_windows_path(runtime_defaults_path)}",
            f"set WINDOWSCODEX2TIMELINE_APPDATA_ROOT={to_windows_path(app_data_root)}",
            f"set WINDOWSCODEX2TIMELINE_OUTPUTS_ROOT={to_windows_path(outputs_root)}",
            f"{WINDOWS_DOTNET_CMD} {to_windows_path(WEB_DLL)}",
        ]
    )
    process = subprocess.Popen(
        [str(WINDOWS_CMD), "/C", command],
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process


def wait_for_server(base_url: str, process: subprocess.Popen[str], log_path: Path) -> None:
    deadline = time.time() + 45
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "Web server exited early.\n\n"
                + log_path.read_text(encoding="utf-8", errors="replace")
            )
        try:
            response = subprocess.run(
                [
                    str(WINDOWS_CURL),
                    "-sS",
                    "--max-time",
                    "2",
                    "-o",
                    "NUL",
                    "-w",
                    "%{http_code}",
                    f"{base_url}/api/app/version",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            if response.stdout.strip() == "200":
                return
        except subprocess.CalledProcessError:
            time.sleep(0.5)
    raise TimeoutError(
        "Timed out waiting for the web server.\n\n"
        + log_path.read_text(encoding="utf-8", errors="replace")
    )


def run_smoke_flow(*, base_url: str, temp_root: Path, outputs_root: Path) -> None:
    cookie_jar = temp_root / "cookies.txt"
    state_catalog_root = create_state_catalog_root(temp_root)

    run_execute_flow(
        base_url=base_url,
        temp_root=temp_root,
        outputs_root=outputs_root,
        cookie_jar=cookie_jar,
        primary_root=FIXTURE_CODEX_HOME,
        expected_title=THREAD_TITLE,
        expected_thread_id="11111111-2222-3333-4444-555555555555",
        artifact_prefix="session",
    )
    run_execute_flow(
        base_url=base_url,
        temp_root=temp_root,
        outputs_root=outputs_root,
        cookie_jar=cookie_jar,
        primary_root=state_catalog_root,
        expected_title=ARCHIVED_THREAD_TITLE,
        expected_thread_id=ARCHIVED_THREAD_ID,
        artifact_prefix="state-catalog",
    )


def run_execute_flow(
    *,
    base_url: str,
    temp_root: Path,
    outputs_root: Path,
    cookie_jar: Path,
    primary_root: Path,
    expected_title: str,
    expected_thread_id: str,
    artifact_prefix: str,
) -> None:
    new_html, new_url = fetch_text(
        url=f"{base_url}/jobs/new?lang=en",
        cookie_jar=cookie_jar,
        response_body_path=temp_root / f"{artifact_prefix}-jobs-new.html",
    )

    if expected_title not in new_html or to_windows_path(primary_root) != to_windows_path(FIXTURE_CODEX_HOME):
        refresh_url = post_form(
            url=f"{base_url}/jobs/new?handler=Refresh&lang=en",
            cookie_jar=cookie_jar,
            response_body_path=temp_root / f"{artifact_prefix}-jobs-refresh.html",
            fields=refresh_fields(
                token=first_match(TOKEN_RE, new_html, "__RequestVerificationToken"),
                primary_root=primary_root,
            ),
        )
        new_html = (temp_root / f"{artifact_prefix}-jobs-refresh.html").read_text(encoding="utf-8", errors="replace")
        new_url = refresh_url

    if expected_title not in new_html:
        raise AssertionError(f"Thread discovery did not render {expected_title}.")

    token = first_match(TOKEN_RE, new_html, "__RequestVerificationToken")
    thread_id = first_match(THREAD_RE, new_html, "SelectedThreadIds")
    if thread_id != expected_thread_id:
        raise AssertionError(f"Unexpected thread id {thread_id} for {artifact_prefix}.")

    final_url = post_form(
        url=f"{base_url}/jobs/new?handler=Execute&lang=en",
        cookie_jar=cookie_jar,
        response_body_path=temp_root / f"{artifact_prefix}-jobs-execute.html",
        fields=execute_fields(
            token=token,
            primary_root=primary_root,
            thread_id=thread_id,
        ),
    )
    match = JOB_ID_RE.search(final_url)
    if not match:
        raise AssertionError(f"Could not determine job id from redirect: {final_url}")

    job_id = match.group(1)
    job_dir = outputs_root / job_id
    process_job(job_dir)

    details_html, _ = fetch_text(
        url=f"{base_url}/jobs/{job_id}?lang=en",
        cookie_jar=cookie_jar,
        response_body_path=temp_root / f"{artifact_prefix}-jobs-details.html",
    )
    if expected_title not in details_html:
        raise AssertionError("Job details did not render the thread timeline preview.")
    if "Completed" not in details_html:
        raise AssertionError("Job details did not render the completed state.")

    jobs_html, _ = fetch_text(
        url=f"{base_url}/jobs?lang=en",
        cookie_jar=cookie_jar,
        response_body_path=temp_root / f"{artifact_prefix}-jobs-index.html",
    )
    if job_id not in jobs_html:
        raise AssertionError("Jobs list did not render the completed run.")

    download_path = temp_root / f"{artifact_prefix}-download.zip"
    download_response = subprocess.run(
        [
            str(WINDOWS_CURL),
            "-sS",
            "-L",
            "--max-time",
            "10",
            "-c",
            to_windows_path(cookie_jar),
            "-b",
            to_windows_path(cookie_jar),
            "-o",
            to_windows_path(download_path),
            "-w",
            "%{http_code}",
            f"{base_url}/jobs/{job_id}/download?lang=en",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = download_path.read_bytes()[:4]
    if download_response.stdout.strip() != "200" or payload != b"PK\x03\x04":
        raise AssertionError("ZIP download did not return a valid archive.")

    timeline_path = job_dir / "threads" / expected_thread_id / "timeline.md"
    if not timeline_path.exists():
        raise AssertionError("Worker did not create the thread timeline.")

    if new_url == final_url:
        raise AssertionError("Execute flow did not redirect to a job details page.")


def refresh_fields(*, token: str, primary_root: Path) -> dict[str, str]:
    return {
        "__RequestVerificationToken": token,
        "PrimaryCodexHomePath": to_windows_path(primary_root),
        "BackupCodexHomePathsText": "",
        "IncludeArchivedSources": "true",
        "IncludeToolOutputs": "true",
        "RedactionProfile": "strict",
        "DateFrom": "",
        "DateTo": "",
    }


def execute_fields(*, token: str, primary_root: Path, thread_id: str) -> dict[str, str]:
    fields = refresh_fields(token=token, primary_root=primary_root)
    fields["SelectedThreadIds"] = thread_id
    return fields


def create_state_catalog_root(temp_root: Path) -> Path:
    root = temp_root / "state-catalog-root"
    thread_reads_root = root / "_codex_tools" / "thread_reads"
    thread_reads_root.mkdir(parents=True, exist_ok=True)

    source_thread_read = ARCHIVED_FIXTURE_ROOT / "_codex_tools" / "thread_reads" / f"{ARCHIVED_THREAD_ID}.json"
    shutil.copy2(source_thread_read, thread_reads_root / source_thread_read.name)

    db_path = root / "state_5.sqlite"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                first_user_message TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO threads (
                id,
                rollout_path,
                updated_at,
                cwd,
                title,
                first_user_message
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                ARCHIVED_THREAD_ID,
                "C:\\Users\\amano\\.codex\\sessions\\2026\\04\\01\\missing.jsonl",
                1775102460,
                "c:\\apps\\windowscodex2timeline",
                "State catalog request for archived@example.com token=legacy-secret",
                "Summarize archived@example.com follow-up with token=legacy-secret",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    return root


def process_job(job_dir: Path) -> None:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(WORKER_SRC) if not existing_pythonpath else f"{WORKER_SRC}:{existing_pythonpath}"
    subprocess.run(
        [sys.executable, "-m", "windowscodex2timeline_worker", "process-job", str(job_dir)],
        check=True,
        env=env,
    )


def fetch_text(
    *,
    url: str,
    cookie_jar: Path,
    response_body_path: Path,
) -> tuple[str, str]:
    result = subprocess.run(
        [
            str(WINDOWS_CURL),
            "-sS",
            "-L",
            "--max-time",
            "10",
            "-c",
            to_windows_path(cookie_jar),
            "-b",
            to_windows_path(cookie_jar),
            "-o",
            to_windows_path(response_body_path.resolve()),
            "-w",
            "%{url_effective}",
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return response_body_path.read_text(encoding="utf-8", errors="replace"), result.stdout.strip()


def post_form(
    *,
    url: str,
    cookie_jar: Path,
    response_body_path: Path,
    fields: dict[str, str],
) -> str:
    encoded = urllib.parse.urlencode(fields, doseq=True)
    result = subprocess.run(
        [
            str(WINDOWS_CURL),
            "-sS",
            "-L",
            "--max-time",
            "10",
            "-X",
            "POST",
            "-H",
            "Content-Type: application/x-www-form-urlencoded",
            "-c",
            to_windows_path(cookie_jar),
            "-b",
            to_windows_path(cookie_jar),
            "--data-binary",
            encoded,
            "-o",
            to_windows_path(response_body_path.resolve()),
            "-w",
            "%{url_effective}",
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def first_match(pattern: re.Pattern[str], text: str, field_name: str) -> str:
    match = pattern.search(text)
    if match:
        return match.group(1)
    raise AssertionError(f"Could not find {field_name} in HTML.")


def allocate_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def ensure_tmp_root() -> None:
    (REPO_ROOT / ".tmp").mkdir(exist_ok=True)


def to_windows_path(path: Path) -> str:
    text = str(path.resolve())
    if text.startswith("/mnt/") and len(text) > 6:
        drive = text[5]
        remainder = text[7:].replace("/", "\\")
        return f"{drive.upper()}:\\{remainder}"
    return text


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        if process.stdout is not None:
            process.stdout.close()
        return

    subprocess.run(
        [str(WINDOWS_TASKKILL), "/PID", str(process.pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
