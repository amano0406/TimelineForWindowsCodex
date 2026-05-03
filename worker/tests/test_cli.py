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
        self.assertIn(".\\cli.ps1 settings status", stderr.getvalue())

    def test_runtime_paths_default_settings_path_is_repo_root(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            runtime = load_runtime_paths()

        self.assertEqual(runtime.settings_path, (REPO_ROOT / "settings.json").resolve())

    def test_items_list_cli_returns_current_and_archived_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            outputs_root = Path(temp_dir) / "outputs"
            appdata_root = temp_root / "appdata"
            runtime_defaults = self._write_runtime_defaults(temp_root, FIXTURE_CODEX_HOME, ARCHIVED_FIXTURE_ROOT)
            stdout, _stderr, exit_code = self._invoke_cli(
                outputs_root,
                "items", "list",
                "--json",
                appdata_root=appdata_root,
                runtime_defaults_path=runtime_defaults,
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["sort"]["order"], "desc")
            self.assertEqual(payload["sort"]["fields"], ["updated_at", "created_at", "thread_id"])
            self.assertEqual(payload["item_count"], 2)
            self.assertEqual(payload["total_items"], 2)
            self.assertEqual(payload["pagination"]["total_items"], 2)
            self.assertEqual(payload["pagination"]["mode"], "all")
            self.assertEqual(payload["pagination"]["returned_items"], 2)
            self.assertNotIn("cache", payload)
            thread_ids = {row["item_id"] for row in payload["items"]}
            self.assertEqual(thread_ids, {FIXTURE_THREAD_ID, ARCHIVED_THREAD_ID})

    def test_items_list_paginates_latest_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            outputs_root = temp_root / "outputs"
            appdata_root = temp_root / "appdata"
            runtime_defaults = self._write_runtime_defaults(temp_root, FIXTURE_CODEX_HOME, ARCHIVED_FIXTURE_ROOT)

            first_stdout, _stderr, first_exit_code = self._invoke_cli(
                outputs_root,
                "items", "list",
                "--page-size",
                "1",
                "--page",
                "1",
                "--json",
                appdata_root=appdata_root,
                runtime_defaults_path=runtime_defaults,
            )
            self.assertEqual(first_exit_code, 0)
            first_payload = json.loads(first_stdout)
            self.assertEqual(first_payload["pagination"]["mode"], "page")
            self.assertEqual(first_payload["pagination"]["returned_items"], 1)
            self.assertTrue(first_payload["pagination"]["has_next"])
            self.assertEqual(first_payload["items"][0]["thread_id"], FIXTURE_THREAD_ID)

            second_stdout, _stderr, second_exit_code = self._invoke_cli(
                outputs_root,
                "items", "list",
                "--page-size",
                "1",
                "--page",
                "2",
                "--json",
                appdata_root=appdata_root,
                runtime_defaults_path=runtime_defaults,
            )
            self.assertEqual(second_exit_code, 0)
            second_payload = json.loads(second_stdout)
            self.assertEqual(second_payload["items"][0]["thread_id"], ARCHIVED_THREAD_ID)
            self.assertFalse(second_payload["pagination"]["has_next"])

    def test_items_list_all_overrides_page_size(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            runtime_defaults = self._write_runtime_defaults(temp_root, FIXTURE_CODEX_HOME, ARCHIVED_FIXTURE_ROOT)
            stdout, _stderr, exit_code = self._invoke_cli(
                temp_root / "outputs",
                "items", "list",
                "--all",
                "--page-size",
                "1",
                "--json",
                appdata_root=temp_root / "appdata",
                runtime_defaults_path=runtime_defaults,
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["pagination"]["mode"], "all")
            self.assertEqual(payload["pagination"]["returned_items"], 2)
            self.assertEqual(len(payload["items"]), 2)
            self.assertFalse(payload["pagination"]["has_next"])

    def test_settings_status_reports_fixed_runtime_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            appdata_root = temp_root / "appdata"
            runtime_defaults = self._write_runtime_defaults(temp_root, FIXTURE_CODEX_HOME, ARCHIVED_FIXTURE_ROOT)

            stdout, _stderr, exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "settings", "status",
                "--json",
                appdata_root=appdata_root,
                runtime_defaults_path=runtime_defaults,
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout)
            self.assertEqual(
                payload["sourceRoots"],
                [str(FIXTURE_CODEX_HOME), str(ARCHIVED_FIXTURE_ROOT)],
            )

    def test_items_refresh_cli_exports_all_items_when_unfiltered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            outputs_root = Path(temp_dir) / "outputs"
            runtime_defaults = self._write_runtime_defaults(temp_root, FIXTURE_CODEX_HOME, ARCHIVED_FIXTURE_ROOT)
            stdout, _stderr, exit_code = self._invoke_cli(
                outputs_root,
                "items", "refresh",
                "--download-to",
                str(Path(temp_dir) / "download"),
                "--json",
                runtime_defaults_path=runtime_defaults,
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout)
            archive_path = Path(payload["download"]["destination_path"])
            self.assertTrue(archive_path.exists())
            self.assertEqual(payload["master_root"], str(outputs_root.resolve()))
            self.assertTrue((outputs_root / FIXTURE_THREAD_ID / "timeline.json").exists())
            self.assertTrue((outputs_root / FIXTURE_THREAD_ID / "convert_info.json").exists())

            with ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                first_thread = json.loads(archive.read(f"items/{FIXTURE_THREAD_ID}/timeline.json").decode("utf-8"))
                first_convert = json.loads(archive.read(f"items/{FIXTURE_THREAD_ID}/convert_info.json").decode("utf-8"))

            self.assertIn("README.md", names)
            self.assertIn(f"items/{FIXTURE_THREAD_ID}/timeline.json", names)
            self.assertIn(f"items/{FIXTURE_THREAD_ID}/convert_info.json", names)
            self.assertIn(f"items/{ARCHIVED_THREAD_ID}/timeline.json", names)
            self.assertIn(f"items/{ARCHIVED_THREAD_ID}/convert_info.json", names)
            self.assertNotIn("readme.html", names)
            self.assertNotIn("status.json", names)
            self.assertEqual(first_thread["thread_id"], FIXTURE_THREAD_ID)
            self.assertEqual(first_convert["thread_id"], FIXTURE_THREAD_ID)
            self.assertIn("TimelineForWindowsCodex-export-", archive_path.name)

    def test_items_refresh_uses_fixed_sources_and_configured_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            appdata_root = temp_root / "appdata"
            outputs_root = temp_root / "configured-outputs"
            runtime_defaults = self._write_runtime_defaults(temp_root, FIXTURE_CODEX_HOME)

            output_stdout, _stderr, output_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "settings",
                "master", "set",
                str(outputs_root),
                "--json",
                appdata_root=appdata_root,
                runtime_defaults_path=runtime_defaults,
            )
            self.assertEqual(output_exit_code, 0)
            output_payload = json.loads(output_stdout)
            self.assertEqual(output_payload["outputRoot"], str(outputs_root.resolve()))

            first_stdout, _stderr, first_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "items", "refresh",
                "--json",
                appdata_root=appdata_root,
                runtime_defaults_path=runtime_defaults,
            )
            self.assertEqual(first_exit_code, 0)
            first_payload = json.loads(first_stdout)
            self.assertEqual(first_payload["master_root"], str(outputs_root.resolve()))
            self.assertTrue((outputs_root / FIXTURE_THREAD_ID / "timeline.json").exists())
            self.assertTrue((outputs_root / FIXTURE_THREAD_ID / "convert_info.json").exists())
            self.assertEqual(first_payload["processing_mode"], "full_rebuild")
            self.assertEqual(first_payload["rendered_thread_count"], 1)
            self.assertEqual(first_payload["update_counts"]["new"], 1)

            second_stdout, _stderr, second_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "items", "refresh",
                "--json",
                appdata_root=appdata_root,
                runtime_defaults_path=runtime_defaults,
            )
            self.assertEqual(second_exit_code, 0)
            second_payload = json.loads(second_stdout)
            self.assertEqual(second_payload["processing_mode"], "incremental_reuse")
            self.assertEqual(second_payload["reused_thread_count"], 1)
            self.assertEqual(second_payload["update_counts"]["unchanged"], 1)

    def test_settings_init_items_refresh_and_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            appdata_root = temp_root / "appdata"
            outputs_root = temp_root / "configured-outputs"
            export_root = temp_root / "exported"
            runtime_defaults = self._write_runtime_defaults(temp_root, FIXTURE_CODEX_HOME)

            init_stdout, _stderr, init_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "settings",
                "init",
                "--output-root",
                str(outputs_root),
                "--json",
                appdata_root=appdata_root,
                runtime_defaults_path=runtime_defaults,
            )
            self.assertEqual(init_exit_code, 0)
            init_payload = json.loads(init_stdout)
            self.assertEqual(init_payload["sourceRoots"], [str(FIXTURE_CODEX_HOME)])
            self.assertEqual(init_payload["outputRoot"], str(outputs_root.resolve()))

            refresh_stdout, _stderr, refresh_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "items", "refresh",
                "--json",
                appdata_root=appdata_root,
                runtime_defaults_path=runtime_defaults,
            )
            self.assertEqual(refresh_exit_code, 0)
            refresh_payload = json.loads(refresh_stdout)
            self.assertEqual(refresh_payload["master_root"], str(outputs_root.resolve()))

            export_stdout, _stderr, export_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "items", "download",
                "--to",
                str(export_root),
                "--json",
                appdata_root=appdata_root,
                runtime_defaults_path=runtime_defaults,
            )
            self.assertEqual(export_exit_code, 0)
            export_payload = json.loads(export_stdout)
            destination_path = Path(export_payload["destination_path"])
            self.assertTrue(destination_path.exists())
            with ZipFile(destination_path) as archive:
                names = set(archive.namelist())
            self.assertIn(f"items/{FIXTURE_THREAD_ID}/timeline.json", names)
            self.assertIn(f"items/{FIXTURE_THREAD_ID}/convert_info.json", names)

            handoff_root = temp_root / "handoff"
            handoff_stdout, _stderr, handoff_exit_code = self._invoke_cli(
                temp_root / "ignored-outputs",
                "items",
                "refresh",
                "--download-to",
                str(handoff_root),
                "--json",
                appdata_root=appdata_root,
                runtime_defaults_path=runtime_defaults,
            )
            self.assertEqual(handoff_exit_code, 0)
            handoff_payload = json.loads(handoff_stdout)
            self.assertEqual(handoff_payload["state"], "completed")
            self.assertEqual(handoff_payload["download"]["state"], "completed")
            self.assertTrue(Path(handoff_payload["download"]["destination_path"]).exists())

    def test_items_refresh_and_download_support_single_and_multiple_item_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            outputs_root = Path(temp_dir) / "outputs"
            single_download_root = Path(temp_dir) / "single-download"
            runtime_defaults = self._write_runtime_defaults(temp_root, FIXTURE_CODEX_HOME, ARCHIVED_FIXTURE_ROOT)

            single_stdout, _stderr, single_exit_code = self._invoke_cli(
                outputs_root,
                "items", "refresh",
                "--item-id",
                FIXTURE_THREAD_ID,
                "--download-to",
                str(single_download_root),
                "--json",
                runtime_defaults_path=runtime_defaults,
            )
            self.assertEqual(single_exit_code, 0)
            single_payload = json.loads(single_stdout)
            with ZipFile(single_payload["download"]["destination_path"]) as archive:
                names = set(archive.namelist())
            self.assertIn("README.md", names)
            self.assertIn(f"items/{FIXTURE_THREAD_ID}/timeline.json", names)
            self.assertIn(f"items/{FIXTURE_THREAD_ID}/convert_info.json", names)
            self.assertNotIn(f"items/{ARCHIVED_THREAD_ID}/timeline.json", names)
            self.assertNotIn(f"items/{ARCHIVED_THREAD_ID}/convert_info.json", names)
            self.assertNotIn("status.json", names)

            multi_stdout, _stderr, multi_exit_code = self._invoke_cli(
                outputs_root,
                "items", "refresh",
                "--item-id",
                FIXTURE_THREAD_ID,
                "--item-id",
                ARCHIVED_THREAD_ID,
                "--json",
                runtime_defaults_path=runtime_defaults,
            )
            self.assertEqual(multi_exit_code, 0)
            json.loads(multi_stdout)

            multi_download_stdout, _stderr, multi_download_exit_code = self._invoke_cli(
                outputs_root,
                "items", "download",
                "--to",
                str(Path(temp_dir) / "multi-download"),
                "--item-id",
                FIXTURE_THREAD_ID,
                "--item-id",
                ARCHIVED_THREAD_ID,
                "--json",
            )
            self.assertEqual(multi_download_exit_code, 0)
            multi_download_payload = json.loads(multi_download_stdout)
            with ZipFile(multi_download_payload["destination_path"]) as archive:
                names = set(archive.namelist())
            self.assertIn("README.md", names)
            self.assertIn(f"items/{FIXTURE_THREAD_ID}/timeline.json", names)
            self.assertIn(f"items/{FIXTURE_THREAD_ID}/convert_info.json", names)
            self.assertIn(f"items/{ARCHIVED_THREAD_ID}/timeline.json", names)
            self.assertIn(f"items/{ARCHIVED_THREAD_ID}/convert_info.json", names)
            self.assertNotIn("status.json", names)

    def _invoke_cli(
        self,
        outputs_root: Path,
        *argv: str,
        appdata_root: Path | None = None,
        settings_path: Path | None = None,
        runtime_defaults_path: Path | None = None,
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
        elif settings_path is None:
            settings_path = outputs_root.parent / "settings.json"
        if settings_path is not None:
            env["TIMELINE_FOR_WINDOWS_CODEX_SETTINGS_PATH"] = str(settings_path)
        if runtime_defaults_path is not None:
            env["TIMELINE_FOR_WINDOWS_CODEX_RUNTIME_DEFAULTS"] = str(runtime_defaults_path)
        with patch.dict(os.environ, env, clear=False):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(list(argv))
        return stdout.getvalue(), stderr.getvalue(), exit_code

    def _write_runtime_defaults(self, root: Path, *input_roots: Path) -> Path:
        path = root / "runtime.defaults.json"
        path.write_text(
            json.dumps({"sourceRoots": [str(input_root) for input_root in input_roots]}, ensure_ascii=False),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    unittest.main()
