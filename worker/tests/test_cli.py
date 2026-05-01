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
from timeline_for_windows_codex_worker.settings import load_runtime_paths  # noqa: E402


FIXTURE_CODEX_HOME = REPO_ROOT / "tests" / "fixtures" / "codex-home-min"
FIXTURE_THREAD_ID = "11111111-2222-3333-4444-555555555555"
ARCHIVED_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "archived-root-min"
ARCHIVED_THREAD_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class WorkerCliTests(unittest.TestCase):
    maxDiff = None

    def test_host_direct_execution_is_blocked_without_explicit_test_allow(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch(
            "timeline_for_windows_codex_worker.cli.Path.exists",
            return_value=False,
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(["settings", "status"])

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Host direct execution is disabled", stderr.getvalue())
        self.assertIn("docker compose run --rm worker", stderr.getvalue())

    def test_runtime_paths_default_settings_path_is_repo_root(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            runtime = load_runtime_paths()

        self.assertEqual(runtime.settings_path, (REPO_ROOT / "settings.json").resolve())

    def test_items_list_cli_returns_current_and_archived_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs_root = Path(temp_dir) / "outputs"
            stdout, _stderr, exit_code = self._invoke_cli(
                outputs_root,
                "items", "list",
                "--primary-root",
                str(FIXTURE_CODEX_HOME),
                "--backup-root",
                str(ARCHIVED_FIXTURE_ROOT),
                "--include-archived-sources",
                "--json",
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout)
            thread_ids = {row["item_id"] for row in payload}
            self.assertEqual(thread_ids, {FIXTURE_THREAD_ID, ARCHIVED_THREAD_ID})

    def test_settings_inputs_list_and_remove_accepts_generated_input_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            appdata_root = temp_root / "appdata"

            add_stdout, _stderr, add_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "settings",
                "inputs",
                "add",
                str(FIXTURE_CODEX_HOME),
                "--json",
                appdata_root=appdata_root,
            )
            self.assertEqual(add_exit_code, 0)
            add_payload = json.loads(add_stdout)
            input_id = add_payload["inputs"][0]["input_id"]

            list_stdout, _stderr, list_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "settings",
                "inputs",
                "list",
                "--json",
                appdata_root=appdata_root,
            )
            self.assertEqual(list_exit_code, 0)
            list_payload = json.loads(list_stdout)
            self.assertEqual(list_payload["inputs"][0]["input_id"], input_id)

            remove_stdout, _stderr, remove_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "settings",
                "inputs",
                "remove",
                input_id,
                "--json",
                appdata_root=appdata_root,
            )
            self.assertEqual(remove_exit_code, 0)
            remove_payload = json.loads(remove_stdout)
            self.assertEqual(remove_payload["inputs"], [])

    def test_items_refresh_cli_exports_all_items_when_unfiltered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs_root = Path(temp_dir) / "outputs"
            stdout, _stderr, exit_code = self._invoke_cli(
                outputs_root,
                "items", "refresh",
                "--primary-root",
                str(FIXTURE_CODEX_HOME),
                "--backup-root",
                str(ARCHIVED_FIXTURE_ROOT),
                "--include-archived-sources",
                "--json",
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout)
            archive_path = Path(payload["archive_path"])
            self.assertTrue(archive_path.exists())

            with ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                first_thread = json.loads(archive.read(f"{FIXTURE_THREAD_ID}/thread.json").decode("utf-8"))
                first_convert = json.loads(archive.read(f"{FIXTURE_THREAD_ID}/convert.json").decode("utf-8"))

            self.assertIn("README.md", names)
            self.assertIn(f"{FIXTURE_THREAD_ID}/thread.json", names)
            self.assertIn(f"{FIXTURE_THREAD_ID}/convert.json", names)
            self.assertIn(f"{ARCHIVED_THREAD_ID}/thread.json", names)
            self.assertIn(f"{ARCHIVED_THREAD_ID}/convert.json", names)
            self.assertNotIn("readme.html", names)
            self.assertNotIn("status.json", names)
            self.assertEqual(first_thread["thread"]["thread_id"], FIXTURE_THREAD_ID)
            self.assertEqual(first_convert["thread_id"], FIXTURE_THREAD_ID)
            self.assertIn("TimelineForWindowsCodex-export-run-", archive_path.name)

    def test_items_refresh_uses_configured_sources_and_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            appdata_root = temp_root / "appdata"
            outputs_root = temp_root / "configured-outputs"

            settings_stdout, _stderr, settings_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "settings",
                "inputs", "add",
                str(FIXTURE_CODEX_HOME),
                "--json",
                appdata_root=appdata_root,
            )
            self.assertEqual(settings_exit_code, 0)
            settings_payload = json.loads(settings_stdout)
            self.assertEqual([row["path"] for row in settings_payload["inputs"]], [str(FIXTURE_CODEX_HOME.resolve())])
            self.assertEqual(settings_payload["settings_path"], str((appdata_root / "settings.json").resolve()))
            self.assertTrue((appdata_root / "settings.json").exists())

            output_stdout, _stderr, output_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "settings",
                "master", "set",
                str(outputs_root),
                "--json",
                appdata_root=appdata_root,
            )
            self.assertEqual(output_exit_code, 0)
            output_payload = json.loads(output_stdout)
            self.assertEqual(output_payload["master_root"], str(outputs_root.resolve()))

            first_stdout, _stderr, first_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "items", "refresh",
                "--json",
                appdata_root=appdata_root,
            )
            self.assertEqual(first_exit_code, 0)
            first_payload = json.loads(first_stdout)
            self.assertTrue(Path(first_payload["archive_path"]).exists())
            self.assertTrue(str(first_payload["run_directory"]).startswith(str(outputs_root.resolve())))
            self.assertEqual(first_payload["processing_mode"], "full_rebuild")
            self.assertEqual(first_payload["rendered_thread_count"], 1)
            self.assertEqual(first_payload["update_counts"]["new"], 1)
            self.assertEqual(len(first_payload["slowest_threads"]), 1)

            second_stdout, _stderr, second_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "items", "refresh",
                "--json",
                appdata_root=appdata_root,
            )
            self.assertEqual(second_exit_code, 0)
            second_payload = json.loads(second_stdout)
            self.assertTrue(Path(second_payload["archive_path"]).exists())
            self.assertEqual(second_payload["processing_mode"], "incremental_reuse")
            self.assertEqual(second_payload["reused_thread_count"], 1)
            self.assertEqual(second_payload["update_counts"]["unchanged"], 1)

    def test_settings_init_items_refresh_and_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            appdata_root = temp_root / "appdata"
            outputs_root = temp_root / "configured-outputs"
            export_root = temp_root / "exported"

            init_stdout, _stderr, init_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "settings",
                "init",
                "--source-root",
                str(FIXTURE_CODEX_HOME),
                "--output-root",
                str(outputs_root),
                "--json",
                appdata_root=appdata_root,
            )
            self.assertEqual(init_exit_code, 0)
            init_payload = json.loads(init_stdout)
            self.assertEqual(init_payload["source_roots"], [str(FIXTURE_CODEX_HOME.resolve())])
            self.assertEqual(init_payload["outputs_root"], str(outputs_root.resolve()))

            refresh_stdout, _stderr, refresh_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "items", "refresh",
                "--json",
                appdata_root=appdata_root,
            )
            self.assertEqual(refresh_exit_code, 0)
            refresh_payload = json.loads(refresh_stdout)

            export_stdout, _stderr, export_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "items", "download",
                "--to",
                str(export_root),
                "--json",
                appdata_root=appdata_root,
            )
            self.assertEqual(export_exit_code, 0)
            export_payload = json.loads(export_stdout)
            destination_path = Path(export_payload["destination_path"])
            self.assertTrue(destination_path.exists())
            self.assertEqual(destination_path.name, Path(refresh_payload["archive_path"]).name)

            _stdout, overwrite_stderr, overwrite_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "items", "download",
                "--to",
                str(export_root),
                "--json",
                appdata_root=appdata_root,
            )
            self.assertEqual(overwrite_exit_code, 1)
            self.assertIn("--overwrite", overwrite_stderr)

            overwrite_stdout, _stderr, final_export_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "items", "download",
                "--to",
                str(export_root),
                "--overwrite",
                "--json",
                appdata_root=appdata_root,
            )
            self.assertEqual(final_export_exit_code, 0)
            overwrite_payload = json.loads(overwrite_stdout)
            self.assertEqual(overwrite_payload["destination_path"], str(destination_path))

            handoff_root = temp_root / "handoff"
            handoff_stdout, _stderr, handoff_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "items",
                "refresh",
                "--download-to",
                str(handoff_root),
                "--json",
                appdata_root=appdata_root,
            )
            self.assertEqual(handoff_exit_code, 0)
            handoff_payload = json.loads(handoff_stdout)
            self.assertEqual(handoff_payload["state"], "completed")
            self.assertEqual(handoff_payload["download"]["state"], "completed")
            self.assertTrue(Path(handoff_payload["download"]["destination_path"]).exists())

    def test_runs_list_and_show_cli_support_single_and_multiple_item_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs_root = Path(temp_dir) / "outputs"

            single_stdout, _stderr, single_exit_code = self._invoke_cli(
                outputs_root,
                "items", "refresh",
                "--primary-root",
                str(FIXTURE_CODEX_HOME),
                "--backup-root",
                str(ARCHIVED_FIXTURE_ROOT),
                "--include-archived-sources",
                "--item-id",
                FIXTURE_THREAD_ID,
                "--json",
            )
            self.assertEqual(single_exit_code, 0)
            single_payload = json.loads(single_stdout)
            with ZipFile(single_payload["archive_path"]) as archive:
                names = set(archive.namelist())
            self.assertIn("README.md", names)
            self.assertIn(f"{FIXTURE_THREAD_ID}/thread.json", names)
            self.assertIn(f"{FIXTURE_THREAD_ID}/convert.json", names)
            self.assertNotIn(f"{ARCHIVED_THREAD_ID}/thread.json", names)
            self.assertNotIn(f"{ARCHIVED_THREAD_ID}/convert.json", names)
            self.assertNotIn("status.json", names)

            multi_stdout, _stderr, multi_exit_code = self._invoke_cli(
                outputs_root,
                "items", "refresh",
                "--primary-root",
                str(FIXTURE_CODEX_HOME),
                "--backup-root",
                str(ARCHIVED_FIXTURE_ROOT),
                "--include-archived-sources",
                "--item-id",
                FIXTURE_THREAD_ID,
                "--item-id",
                ARCHIVED_THREAD_ID,
                "--json",
            )
            self.assertEqual(multi_exit_code, 0)
            multi_payload = json.loads(multi_stdout)
            with ZipFile(multi_payload["archive_path"]) as archive:
                names = set(archive.namelist())
            self.assertIn("README.md", names)
            self.assertIn(f"{FIXTURE_THREAD_ID}/thread.json", names)
            self.assertIn(f"{FIXTURE_THREAD_ID}/convert.json", names)
            self.assertIn(f"{ARCHIVED_THREAD_ID}/thread.json", names)
            self.assertIn(f"{ARCHIVED_THREAD_ID}/convert.json", names)
            self.assertNotIn("status.json", names)

            list_stdout, _stderr, list_exit_code = self._invoke_cli(
                outputs_root,
                "runs", "list",
                "--json",
            )
            self.assertEqual(list_exit_code, 0)
            listed_jobs = json.loads(list_stdout)
            self.assertEqual(len(listed_jobs), 2)

            show_stdout, _stderr, show_exit_code = self._invoke_cli(
                outputs_root,
                "runs", "show",
                "--run-id",
                multi_payload["run_id"],
                "--json",
            )
            self.assertEqual(show_exit_code, 0)
            show_payload = json.loads(show_stdout)
            show_ids = {row["thread_id"] for row in show_payload["selected_threads"]}
            self.assertEqual(show_ids, {FIXTURE_THREAD_ID, ARCHIVED_THREAD_ID})

    def _invoke_cli(
        self,
        outputs_root: Path,
        *argv: str,
        appdata_root: Path | None = None,
        settings_path: Path | None = None,
    ) -> tuple[str, str, int]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        env = {
            "TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN": "1",
            "TIMELINE_FOR_WINDOWS_CODEX_OUTPUTS_ROOT": str(outputs_root),
        }
        if appdata_root is not None:
            env["TIMELINE_FOR_WINDOWS_CODEX_APPDATA_ROOT"] = str(appdata_root)
            if settings_path is None:
                settings_path = appdata_root / "settings.json"
        if settings_path is not None:
            env["TIMELINE_FOR_WINDOWS_CODEX_SETTINGS_PATH"] = str(settings_path)
        with patch.dict(os.environ, env, clear=False):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(list(argv))
        return stdout.getvalue(), stderr.getvalue(), exit_code


if __name__ == "__main__":
    unittest.main()
