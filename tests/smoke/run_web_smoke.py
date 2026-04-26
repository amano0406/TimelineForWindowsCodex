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
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_DOTNET = Path("/mnt/c/Program Files/dotnet/dotnet.exe")
WINDOWS_CMD = Path("/mnt/c/Windows/System32/cmd.exe")
WINDOWS_TASKKILL = Path("/mnt/c/Windows/System32/taskkill.exe")
WINDOWS_CURL = Path("/mnt/c/Windows/System32/curl.exe")
WINDOWS_DOTNET_CMD = r"C:\Progra~1\dotnet\dotnet.exe"
WEB_PROJECT = REPO_ROOT / "web" / "TimelineForWindowsCodex.Web.csproj"
WEB_ROOT = REPO_ROOT / "web"
WORKER_SRC = REPO_ROOT / "worker" / "src"
FIXTURE_CODEX_HOME = REPO_ROOT / "tests" / "fixtures" / "codex-home-min"
THREAD_TITLE = "Codex timeline sample thread"
ARCHIVED_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "archived-root-min"
ARCHIVED_THREAD_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ARCHIVED_THREAD_TITLE = "Archived timeline source"

TOKEN_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', re.IGNORECASE)
THREAD_RE = re.compile(r'name="SelectedThreadIds"[^>]*value="([^"]+)"', re.IGNORECASE)
JOB_ID_RE = re.compile(r"/(?:exports|jobs)/([^/?]+)")


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
        build_output_root = temp_root_path / "web-build"
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

        web_dll = build_web_app(build_output_root)

        process = start_web_server(
            base_url=base_url,
            runtime_defaults_path=runtime_defaults_path,
            app_data_root=app_data_root,
            outputs_root=outputs_root,
            web_dll_path=web_dll,
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


def build_web_app(output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(WINDOWS_DOTNET),
            "build",
            to_windows_path(WEB_PROJECT),
            "-o",
            to_windows_path(output_root),
        ],
        check=True,
    )
    return output_root / "TimelineForWindowsCodex.Web.dll"


def start_web_server(
    *,
    base_url: str,
    runtime_defaults_path: Path,
    app_data_root: Path,
    outputs_root: Path,
    web_dll_path: Path,
    log_path: Path,
) -> subprocess.Popen[str]:
    log_handle = log_path.open("w", encoding="utf-8")
    command = " && ".join(
        [
            f"cd /d {to_windows_path(WEB_ROOT)}",
            "set ASPNETCORE_ENVIRONMENT=Development",
            f"set ASPNETCORE_URLS={base_url}",
            f"set TIMELINE_FOR_WINDOWS_CODEX_RUNTIME_DEFAULTS={to_windows_path(runtime_defaults_path)}",
            f"set TIMELINE_FOR_WINDOWS_CODEX_APPDATA_ROOT={to_windows_path(app_data_root)}",
            f"set TIMELINE_FOR_WINDOWS_CODEX_OUTPUTS_ROOT={to_windows_path(outputs_root)}",
            f"{WINDOWS_DOTNET_CMD} {to_windows_path(web_dll_path)}",
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
    active_current_job_id: str | None = None
    new_html, new_url = fetch_text(
        url=f"{base_url}/threads?lang=en",
        cookie_jar=cookie_jar,
        response_body_path=temp_root / f"{artifact_prefix}-threads.html",
    )

    if expected_title not in new_html or to_windows_path(primary_root) != to_windows_path(FIXTURE_CODEX_HOME):
        refresh_url = post_form(
            url=f"{base_url}/threads?handler=Refresh&lang=en",
            cookie_jar=cookie_jar,
            response_body_path=temp_root / f"{artifact_prefix}-threads-refresh.html",
            fields=refresh_fields(
                token=first_match(TOKEN_RE, new_html, "__RequestVerificationToken"),
                primary_root=primary_root,
            ),
        )
        new_html = (temp_root / f"{artifact_prefix}-threads-refresh.html").read_text(encoding="utf-8", errors="replace")
        new_url = refresh_url

    if expected_title not in new_html:
        raise AssertionError(f"Thread discovery did not render {expected_title}.")
    if "Filter by thread name, ID, or working folder" not in new_html:
        raise AssertionError("Thread selection filter was not rendered.")
    if "Select visible" not in new_html:
        raise AssertionError("Thread selection helper buttons were not rendered.")

    token = first_match(TOKEN_RE, new_html, "__RequestVerificationToken")
    thread_id = first_match(THREAD_RE, new_html, "SelectedThreadIds")
    if thread_id != expected_thread_id:
        raise AssertionError(f"Unexpected thread id {thread_id} for {artifact_prefix}.")

    final_url = post_form(
        url=f"{base_url}/threads?handler=Execute&lang=en",
        cookie_jar=cookie_jar,
        response_body_path=temp_root / f"{artifact_prefix}-threads-execute.html",
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

    active_jobs_html, _ = fetch_text(
        url=f"{base_url}/exports?lang=en",
        cookie_jar=cookie_jar,
        response_body_path=temp_root / f"{artifact_prefix}-exports-active.html",
    )
    if "Running or pending" not in active_jobs_html or "Current thread" not in active_jobs_html or "ETA" not in active_jobs_html:
        raise AssertionError("Exports page did not render active-run inspection details.")

    process_job(job_dir)
    current_path = outputs_root / "current.json"
    refresh_history_path = outputs_root / "refresh-history.jsonl"
    if job_id not in current_path.read_text(encoding="utf-8") or "full_rebuild" not in refresh_history_path.read_text(encoding="utf-8"):
        raise AssertionError("Worker did not update the current artifact pointer and refresh history.")
    active_current_job_id = read_json_file(current_path)["job_id"]
    update_manifest_text = (job_dir / "update_manifest.json").read_text(encoding="utf-8")
    if '"processing_mode": "full_rebuild"' not in update_manifest_text:
        raise AssertionError("Worker did not write the update manifest.")

    overview_html, _ = fetch_text(
        url=f"{base_url}/?lang=en",
        cookie_jar=cookie_jar,
        response_body_path=temp_root / f"{artifact_prefix}-overview.html",
    )
    if "Overview" not in overview_html or "Current artifact" not in overview_html or "Inspect threads" not in overview_html:
        raise AssertionError("Overview page did not render the public inspection dashboard.")

    environment_html, _ = fetch_text(
        url=f"{base_url}/environment?lang=en",
        cookie_jar=cookie_jar,
        response_body_path=temp_root / f"{artifact_prefix}-environment.html",
    )
    if "Environment" not in environment_html or "Input scope" not in environment_html:
        raise AssertionError("Environment page did not render the input scope dashboard.")

    details_html, _ = fetch_text(
        url=f"{base_url}/exports/{job_id}?lang=en",
        cookie_jar=cookie_jar,
        response_body_path=temp_root / f"{artifact_prefix}-exports-details.html",
    )
    if expected_title not in details_html:
        raise AssertionError("Export details did not render the thread timeline preview.")
    if "Completed" not in details_html:
        raise AssertionError("Export details did not render the completed state.")
    if "Current thread" not in details_html or "ETA" not in details_html:
        raise AssertionError("Export details did not render current processing inspection.")
    if "Fidelity summary" not in details_html or "Attachment labels" not in details_html:
        raise AssertionError("Export details did not render the fidelity summary.")
    if "Refresh summary" not in details_html or "Update status" not in details_html or "Full rebuild" not in details_html:
        raise AssertionError("Export details did not render refresh summary inspection.")
    if "Worker log" not in details_html or f"Processed {expected_thread_id}" not in details_html:
        raise AssertionError("Export details did not render the worker log tail.")
    if "Thread coverage" not in details_html or "Source type" not in details_html:
        raise AssertionError("Export details did not render thread coverage.")
    if "Export preview" not in details_html or "fidelity_report.md" not in details_html or "update_manifest.json" not in details_html:
        raise AssertionError("Export details did not render export previews.")

    jobs_html, _ = fetch_text(
        url=f"{base_url}/exports?lang=en",
        cookie_jar=cookie_jar,
        response_body_path=temp_root / f"{artifact_prefix}-exports-index.html",
    )
    if job_id not in jobs_html:
        raise AssertionError("Exports page did not render the completed export.")
    if "Current artifact" not in jobs_html or "Refresh history" not in jobs_html:
        raise AssertionError("Exports page did not render the current artifact dashboard.")
    if "Reused" not in jobs_html or "Rendered" not in jobs_html:
        raise AssertionError("Exports page did not render cache reuse counters.")
    if "Refresh latest" not in jobs_html:
        raise AssertionError("Exports page did not render the latest refresh button.")

    if artifact_prefix == "session":
        refresh_url = post_form(
            url=f"{base_url}/exports?handler=RefreshCurrent&lang=en",
            cookie_jar=cookie_jar,
            response_body_path=temp_root / "refresh-current-post.html",
            fields={"__RequestVerificationToken": first_match(TOKEN_RE, jobs_html, "__RequestVerificationToken")},
        )
        refresh_match = JOB_ID_RE.search(refresh_url)
        if not refresh_match:
            raise AssertionError(f"Could not determine refresh job id from redirect: {refresh_url}")
        refresh_job_id = refresh_match.group(1)
        process_job(outputs_root / refresh_job_id)
        refresh_manifest_text = (outputs_root / refresh_job_id / "update_manifest.json").read_text(encoding="utf-8")
        refresh_log_text = (outputs_root / refresh_job_id / "logs" / "worker.log").read_text(encoding="utf-8")
        if '"processing_mode": "incremental_reuse"' not in refresh_manifest_text or f"Reused {expected_thread_id}" not in refresh_log_text:
            raise AssertionError("Refresh latest did not reuse the unchanged thread cache.")
        refresh_details_html, _ = fetch_text(
            url=f"{base_url}/exports/{refresh_job_id}?lang=en",
            cookie_jar=cookie_jar,
            response_body_path=temp_root / "refresh-current-details.html",
        )
        if "Refresh summary" not in refresh_details_html or "Incremental reuse" not in refresh_details_html or "unchanged" not in refresh_details_html:
            raise AssertionError("Refresh export details did not render update manifest summary.")
        active_current_job_id = read_json_file(current_path)["job_id"]

        failed_refresh_url = post_form(
            url=f"{base_url}/exports?handler=RefreshCurrent&lang=en",
            cookie_jar=cookie_jar,
            response_body_path=temp_root / "refresh-current-failed-post.html",
            fields={"__RequestVerificationToken": first_match(TOKEN_RE, jobs_html, "__RequestVerificationToken")},
        )
        failed_refresh_match = JOB_ID_RE.search(failed_refresh_url)
        if not failed_refresh_match:
            raise AssertionError(f"Could not determine failed refresh job id from redirect: {failed_refresh_url}")
        failed_refresh_job_id = failed_refresh_match.group(1)
        failed_job_dir = outputs_root / failed_refresh_job_id
        rewrite_request_with_broken_thread_source(
            job_dir=failed_job_dir,
            broken_source_path=temp_root / "broken-thread-read.json",
        )
        process_job_expect_failure(failed_job_dir)

        current_after_failure = read_json_file(current_path)
        refresh_history_text = refresh_history_path.read_text(encoding="utf-8")
        if current_after_failure["job_id"] != active_current_job_id:
            raise AssertionError("Failed refresh replaced the previous current artifact.")
        if failed_refresh_job_id in json.dumps(current_after_failure, ensure_ascii=False):
            raise AssertionError("Failed refresh leaked into current artifact metadata.")
        if f'"job_id": "{failed_refresh_job_id}"' not in refresh_history_text or '"state": "failed"' not in refresh_history_text:
            raise AssertionError("Failed refresh was not recorded in refresh history.")

        failed_details_html, _ = fetch_text(
            url=f"{base_url}/exports/{failed_refresh_job_id}?lang=en",
            cookie_jar=cookie_jar,
            response_body_path=temp_root / "refresh-current-failed-details.html",
        )
        if "Failed" not in failed_details_html:
            raise AssertionError("Failed refresh details did not render the failed state.")

        exports_after_failure_html, _ = fetch_text(
            url=f"{base_url}/exports?lang=en",
            cookie_jar=cookie_jar,
            response_body_path=temp_root / "refresh-current-failed-exports.html",
        )
        if active_current_job_id not in exports_after_failure_html or failed_refresh_job_id not in exports_after_failure_html:
            raise AssertionError("Exports page did not preserve the previous current artifact alongside the failed refresh.")
        if "failed_refresh" not in exports_after_failure_html:
            raise AssertionError("Exports page did not render the failed refresh history entry.")

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
            f"{base_url}/exports/{job_id}/download?lang=en",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = download_path.read_bytes()[:4]
    if download_response.stdout.strip() != "200" or payload != b"PK\x03\x04":
        raise AssertionError("ZIP download did not return a valid archive.")
    with ZipFile(download_path) as archive:
        names = set(archive.namelist())
        if "readme.html" not in names or "threads/index.md" not in names:
            raise AssertionError("ZIP download did not contain the expected entry files.")
        if "catalog.json" not in names:
            raise AssertionError("ZIP download did not contain catalog.json.")
        if "update_manifest.json" not in names:
            raise AssertionError("ZIP download did not contain update_manifest.json.")

    timeline_path = job_dir / "threads" / expected_thread_id / "timeline.md"
    if not timeline_path.exists():
        raise AssertionError("Worker did not create the thread timeline.")
    timeline_text = timeline_path.read_text(encoding="utf-8")
    if artifact_prefix == "session":
        if "Attachments / 添付ファイル" not in timeline_text or "000.txt" not in timeline_text:
            raise AssertionError("Thread timeline did not preserve the attachment label.")
    timeline_index_path = job_dir / "threads" / "index.md"
    if not timeline_index_path.exists():
        raise AssertionError("Worker did not create the bundle index.")
    timeline_index_text = timeline_index_path.read_text(encoding="utf-8")
    if str(timeline_path) in timeline_index_text:
        raise AssertionError("Bundle index leaked an internal absolute path.")

    if new_url == final_url:
        raise AssertionError("Execute flow did not redirect to an export details page.")


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
                "c:\\apps\\TimelineForWindowsCodex",
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
        [sys.executable, "-m", "timeline_for_windows_codex_worker", "process-job", str(job_dir)],
        check=True,
        env=env,
    )


def process_job_expect_failure(job_dir: Path) -> None:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(WORKER_SRC) if not existing_pythonpath else f"{WORKER_SRC}:{existing_pythonpath}"
    result = subprocess.run(
        [sys.executable, "-m", "timeline_for_windows_codex_worker", "process-job", str(job_dir)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode == 0:
        raise AssertionError("Expected refresh processing to fail, but it completed successfully.")


def rewrite_request_with_broken_thread_source(*, job_dir: Path, broken_source_path: Path) -> None:
    broken_source_path.write_text("{broken json\n", encoding="utf-8")
    request_path = job_dir / "request.json"
    payload = read_json_file(request_path)
    selected_threads = payload.get("selected_threads")
    if not isinstance(selected_threads, list) or not selected_threads:
        raise AssertionError("Refresh request did not contain any selected threads.")

    first_thread = selected_threads[0]
    if not isinstance(first_thread, dict):
        raise AssertionError("Refresh request selected thread payload was malformed.")

    first_thread["session_path"] = to_windows_path(broken_source_path)
    first_thread["source_root_path"] = to_windows_path(broken_source_path.parent)
    request_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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


def read_json_file(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


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
