from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_SRC = REPO_ROOT / "worker" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from timeline_for_windows_codex_worker.cli import main  # noqa: E402
from timeline_for_windows_codex_worker.fs_utils import read_json  # noqa: E402


FIXTURE_CODEX_HOME = REPO_ROOT / "tests" / "fixtures" / "codex-home-min"
FIXTURE_THREAD_ID = "11111111-2222-3333-4444-555555555555"
ARCHIVED_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "archived-root-min"
ARCHIVED_THREAD_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class WorkerCliTests(unittest.TestCase):
    maxDiff = None

    def test_discover_cli_returns_current_and_archived_threads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs_root = Path(temp_dir) / "outputs"
            stdout, _stderr, exit_code = self._invoke_cli(
                outputs_root,
                "discover",
                "--primary-root",
                str(FIXTURE_CODEX_HOME),
                "--backup-root",
                str(ARCHIVED_FIXTURE_ROOT),
                "--include-archived-sources",
                "--format",
                "json",
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout)
            thread_ids = {row["thread_id"] for row in payload}
            self.assertEqual(thread_ids, {FIXTURE_THREAD_ID, ARCHIVED_THREAD_ID})

    def test_create_job_cli_defaults_to_all_discovered_threads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs_root = Path(temp_dir) / "outputs"
            stdout, _stderr, exit_code = self._invoke_cli(
                outputs_root,
                "create-job",
                "--primary-root",
                str(FIXTURE_CODEX_HOME),
                "--backup-root",
                str(ARCHIVED_FIXTURE_ROOT),
                "--include-archived-sources",
                "--format",
                "json",
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["thread_count"], 2)

            request = read_json(Path(payload["run_directory"]) / "request.json")
            selected_ids = {row["thread_id"] for row in request["selected_threads"]}
            self.assertEqual(selected_ids, {FIXTURE_THREAD_ID, ARCHIVED_THREAD_ID})

    def test_run_cli_exports_all_threads_when_unfiltered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs_root = Path(temp_dir) / "outputs"
            stdout, _stderr, exit_code = self._invoke_cli(
                outputs_root,
                "run",
                "--primary-root",
                str(FIXTURE_CODEX_HOME),
                "--backup-root",
                str(ARCHIVED_FIXTURE_ROOT),
                "--include-archived-sources",
                "--format",
                "json",
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout)
            archive_path = Path(payload["archive_path"])
            self.assertTrue(archive_path.exists())

            with ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                zipped_status = json.loads(archive.read("status.json").decode("utf-8"))
                zipped_result = json.loads(archive.read("result.json").decode("utf-8"))

            self.assertIn(f"threads/{FIXTURE_THREAD_ID}.md", names)
            self.assertIn(f"threads/{ARCHIVED_THREAD_ID}.md", names)
            self.assertIn("environment/ledger.json", names)
            self.assertEqual(zipped_status["state"], "completed")
            self.assertEqual(zipped_result["state"], "completed")

    def test_run_list_and_show_cli_support_single_and_multiple_thread_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs_root = Path(temp_dir) / "outputs"

            single_stdout, _stderr, single_exit_code = self._invoke_cli(
                outputs_root,
                "run",
                "--primary-root",
                str(FIXTURE_CODEX_HOME),
                "--backup-root",
                str(ARCHIVED_FIXTURE_ROOT),
                "--include-archived-sources",
                "--thread-id",
                FIXTURE_THREAD_ID,
                "--format",
                "json",
            )
            self.assertEqual(single_exit_code, 0)
            single_payload = json.loads(single_stdout)
            with ZipFile(single_payload["archive_path"]) as archive:
                names = set(archive.namelist())
                zipped_status = json.loads(archive.read("status.json").decode("utf-8"))
                zipped_result = json.loads(archive.read("result.json").decode("utf-8"))
            self.assertIn(f"threads/{FIXTURE_THREAD_ID}.md", names)
            self.assertNotIn(f"threads/{ARCHIVED_THREAD_ID}.md", names)
            self.assertIn("environment/ledger.json", names)
            self.assertEqual(zipped_status["state"], "completed")
            self.assertEqual(zipped_result["state"], "completed")

            multi_stdout, _stderr, multi_exit_code = self._invoke_cli(
                outputs_root,
                "run",
                "--primary-root",
                str(FIXTURE_CODEX_HOME),
                "--backup-root",
                str(ARCHIVED_FIXTURE_ROOT),
                "--include-archived-sources",
                "--thread-id",
                FIXTURE_THREAD_ID,
                "--thread-id",
                ARCHIVED_THREAD_ID,
                "--format",
                "json",
            )
            self.assertEqual(multi_exit_code, 0)
            multi_payload = json.loads(multi_stdout)
            with ZipFile(multi_payload["archive_path"]) as archive:
                names = set(archive.namelist())
                zipped_status = json.loads(archive.read("status.json").decode("utf-8"))
                zipped_result = json.loads(archive.read("result.json").decode("utf-8"))
            self.assertIn(f"threads/{FIXTURE_THREAD_ID}.md", names)
            self.assertIn(f"threads/{ARCHIVED_THREAD_ID}.md", names)
            self.assertIn("environment/ledger.json", names)
            self.assertEqual(zipped_status["state"], "completed")
            self.assertEqual(zipped_result["state"], "completed")

            list_stdout, _stderr, list_exit_code = self._invoke_cli(
                outputs_root,
                "list-jobs",
                "--format",
                "json",
            )
            self.assertEqual(list_exit_code, 0)
            listed_jobs = json.loads(list_stdout)
            self.assertEqual(len(listed_jobs), 2)

            show_stdout, _stderr, show_exit_code = self._invoke_cli(
                outputs_root,
                "show-job",
                multi_payload["job_id"],
                "--format",
                "json",
            )
            self.assertEqual(show_exit_code, 0)
            show_payload = json.loads(show_stdout)
            show_ids = {row["thread_id"] for row in show_payload["selected_threads"]}
            self.assertEqual(show_ids, {FIXTURE_THREAD_ID, ARCHIVED_THREAD_ID})

    def _invoke_cli(self, outputs_root: Path, *argv: str) -> tuple[str, str, int]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        env = {
            "TIMELINE_FOR_WINDOWS_CODEX_OUTPUTS_ROOT": str(outputs_root),
        }
        with patch.dict(os.environ, env, clear=False):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(list(argv))
        return stdout.getvalue(), stderr.getvalue(), exit_code


if __name__ == "__main__":
    unittest.main()
