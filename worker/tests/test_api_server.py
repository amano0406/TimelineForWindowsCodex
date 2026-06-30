from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_SRC = REPO_ROOT / "worker" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from timeline_for_windows_codex_worker.api_server import handle_request  # noqa: E402
from timeline_for_windows_codex_worker.api_services import runtime_path_to_config_text  # noqa: E402
from timeline_for_windows_codex_worker.settings import load_runtime_paths  # noqa: E402


FIXTURE_CODEX_HOME = REPO_ROOT / "tests" / "fixtures" / "codex-home-min"
FIXTURE_THREAD_ID = "11111111-2222-3333-4444-555555555555"
ARCHIVED_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "archived-root-min"


class WorkerApiServerTests(unittest.TestCase):
    maxDiff = None

    def test_runtime_paths_default_settings_path_is_repo_root(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            runtime = load_runtime_paths()

        self.assertEqual(runtime.settings_path, (REPO_ROOT / "settings.json").resolve())

    def test_runtime_path_to_config_text_returns_windows_host_path_for_wsl_mount(self) -> None:
        with patch("timeline_for_windows_codex_worker.api_services.os.name", "posix"):
            result = runtime_path_to_config_text("/mnt/c/apps/Timeline/data/work/downloads/windows-codex/export.zip")

        self.assertEqual(result, r"C:\apps\Timeline\data\work\downloads\windows-codex\export.zip")

    def test_worker_api_handles_settings_items_detail_download_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            appdata_root = temp_root / "appdata"
            outputs_root = temp_root / "api-outputs"
            download_root = temp_root / "api-download"
            runtime_defaults = self._write_runtime_defaults(temp_root, FIXTURE_CODEX_HOME, ARCHIVED_FIXTURE_ROOT)

            env = {
                "TIMELINE_FOR_WINDOWS_CODEX_OUTPUTS_ROOT": str(temp_root / "ignored-outputs"),
                "TIMELINE_FOR_WINDOWS_CODEX_APPDATA_ROOT": str(appdata_root),
                "TIMELINE_FOR_WINDOWS_CODEX_SETTINGS_PATH": str(appdata_root / "settings.json"),
                "TIMELINE_FOR_WINDOWS_CODEX_RUNTIME_DEFAULTS": str(runtime_defaults),
            }
            with patch.dict(os.environ, env, clear=False):
                health_status, health_payload = handle_request("GET", "/health", None)
                self.assertEqual(health_status, 200)
                self.assertTrue(health_payload)

                init_status, init_payload = handle_request(
                    "POST",
                    "/settings/init",
                    {"outputRoot": str(outputs_root)},
                )
                self.assertEqual(init_status, 200)
                self.assertEqual(init_payload["outputRoot"], str(outputs_root.resolve()))
                self.assertEqual(init_payload["sourceRoots"], [str(FIXTURE_CODEX_HOME), str(ARCHIVED_FIXTURE_ROOT)])

                empty_list_status, empty_list_payload = handle_request(
                    "POST",
                    "/items/list",
                    {"pageSize": 1, "page": 1},
                )
                self.assertEqual(empty_list_status, 200)
                self.assertEqual(empty_list_payload["pagination"]["mode"], "page")
                self.assertEqual(empty_list_payload["pagination"]["returned_items"], 0)

                refresh_status, refresh_payload = handle_request(
                    "POST",
                    "/items/refresh",
                    {
                        "itemIds": [FIXTURE_THREAD_ID],
                        "downloadTo": str(download_root),
                    },
                )
                self.assertEqual(refresh_status, 200)
                self.assertEqual(refresh_payload["state"], "completed")
                self.assertEqual(refresh_payload["master_root"], str(outputs_root.resolve()))
                self.assertTrue((outputs_root / FIXTURE_THREAD_ID / "timeline.json").exists())
                self.assertTrue(Path(refresh_payload["download"]["destination_path"]).exists())

                jobs_status, jobs_payload = handle_request(
                    "POST",
                    "/jobs",
                    {
                        "type": "refresh",
                        "options": {
                            "itemIds": [FIXTURE_THREAD_ID],
                        },
                    },
                )
                self.assertEqual(jobs_status, 200)
                self.assertEqual(jobs_payload["productId"], "windows-codex")
                self.assertTrue(jobs_payload["jobId"])
                job_id = jobs_payload["jobId"]
                job_payload = jobs_payload
                for _ in range(50):
                    job_status, job_payload = handle_request("GET", f"/jobs/{job_id}", None)
                    self.assertEqual(job_status, 200)
                    if job_payload["state"] not in {"queued", "running"}:
                        break
                    time.sleep(0.05)
                self.assertEqual(job_payload["state"], "completed")
                self.assertEqual(job_payload["progress"]["percent"], 100)
                self.assertEqual(job_payload["result"]["state"], "completed")

                max_items_status, max_items_payload = handle_request(
                    "POST",
                    "/jobs",
                    {
                        "type": "refresh",
                        "options": {
                            "maxItems": 1,
                        },
                    },
                )
                self.assertEqual(max_items_status, 200)
                max_items_job_id = max_items_payload["jobId"]
                for _ in range(50):
                    max_job_status, max_items_payload = handle_request("GET", f"/jobs/{max_items_job_id}", None)
                    self.assertEqual(max_job_status, 200)
                    if max_items_payload["state"] not in {"queued", "running"}:
                        break
                    time.sleep(0.05)
                self.assertEqual(max_items_payload["state"], "completed")
                self.assertEqual(max_items_payload["progress"]["total"], 1)
                self.assertEqual(max_items_payload["result"]["thread_count"], 1)

                list_status, list_payload = handle_request(
                    "POST",
                    "/items/list",
                    {"pageSize": 1, "page": 1},
                )
                self.assertEqual(list_status, 200)
                self.assertEqual(list_payload["source"], "master")
                self.assertEqual(list_payload["pagination"]["mode"], "page")
                self.assertEqual(list_payload["pagination"]["returned_items"], 1)
                self.assertEqual(list_payload["items"][0]["item_id"], FIXTURE_THREAD_ID)

                default_list_status, default_list_payload = handle_request("POST", "/items/list", {})
                self.assertEqual(default_list_status, 200)
                self.assertEqual(default_list_payload["pagination"]["mode"], "page")
                self.assertLessEqual(default_list_payload["pagination"]["returned_items"], 100)

                detail_status, detail_payload = handle_request(
                    "POST",
                    "/items/detail",
                    {"itemId": FIXTURE_THREAD_ID},
                )
                self.assertEqual(detail_status, 200)
                self.assertTrue(detail_payload["available"])
                self.assertEqual(detail_payload["itemId"], FIXTURE_THREAD_ID)
                self.assertGreater(detail_payload["messageCount"], 0)

                download_status, download_payload = handle_request(
                    "POST",
                    "/items/download",
                    {"itemIds": [FIXTURE_THREAD_ID], "to": str(temp_root / "manual-download")},
                )
                self.assertEqual(download_status, 200)
                self.assertTrue(Path(download_payload["destination_path"]).exists())

                remove_status, remove_payload = handle_request(
                    "POST",
                    "/items/remove",
                    {"itemIds": [FIXTURE_THREAD_ID]},
                )
                self.assertEqual(remove_status, 200)
                self.assertEqual(remove_payload["removed_count"], 1)
                self.assertFalse((outputs_root / FIXTURE_THREAD_ID).exists())

    def _write_runtime_defaults(self, root: Path, *input_roots: Path) -> Path:
        path = root / "runtime.defaults.json"
        path.write_text(
            json.dumps({"sourceRoots": [str(input_root) for input_root in input_roots]}, ensure_ascii=False),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    unittest.main()
