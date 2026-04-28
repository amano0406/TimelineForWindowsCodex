from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_SRC = REPO_ROOT / "worker" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from timeline_for_windows_codex_worker.contracts import JobRequest, ObservedThreadName, ThreadSelection  # noqa: E402
from timeline_for_windows_codex_worker.fs_utils import ensure_dir, read_json, write_json_atomic  # noqa: E402
from timeline_for_windows_codex_worker.processor import process_job  # noqa: E402
from timeline_for_windows_codex_worker.timeline import export_thread_markdown_name  # noqa: E402


FIXTURE_CODEX_HOME = REPO_ROOT / "tests" / "fixtures" / "codex-home-min"
FIXTURE_THREAD_ID = "11111111-2222-3333-4444-555555555555"
ARCHIVED_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "archived-root-min"
ARCHIVED_THREAD_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class ProcessJobIntegrationTests(unittest.TestCase):
    maxDiff = None

    def test_process_job_builds_redacted_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            job_dir = self._create_job_dir(
                Path(temp_dir),
                fixture_root=FIXTURE_CODEX_HOME,
                thread_id=FIXTURE_THREAD_ID,
                preferred_title="Codex timeline sample thread",
                first_prompt_excerpt="Please summarize the last week of work for [email].",
                include_tool_outputs=True,
            )

            process_job(job_dir)

            status = read_json(job_dir / "status.json")
            result = read_json(job_dir / "result.json")
            manifest = read_json(job_dir / "manifest.json")
            catalog = read_json(job_dir / "catalog.json")
            processing_profile = read_json(job_dir / "processing_profile.json")
            current = read_json(job_dir.parent / "current.json")
            refresh_history_text = (job_dir.parent / "refresh-history.jsonl").read_text(encoding="utf-8")
            environment_ledger = read_json(job_dir / "environment" / "ledger.json")
            timeline_text = (job_dir / "threads" / FIXTURE_THREAD_ID / "timeline.md").read_text(encoding="utf-8")
            timeline_index_text = (job_dir / "threads" / "index.md").read_text(encoding="utf-8")
            export_readme = (job_dir / "readme.html").read_text(encoding="utf-8")

            self.assertEqual(status["state"], "completed")
            self.assertEqual(status["current_stage"], "completed")
            self.assertEqual(result["state"], "completed")
            self.assertEqual(result["thread_count"], 1)
            self.assertEqual(result["event_count"], 7)
            self.assertGreaterEqual(result["segment_count"], 3)
            self.assertEqual(manifest["items"][0]["thread_id"], FIXTURE_THREAD_ID)
            self.assertTrue(manifest["items"][0]["session_path"].endswith(".jsonl"))
            self.assertEqual(catalog["job_id"], "run-fixture")
            self.assertEqual(catalog["threads"][0]["thread_id"], FIXTURE_THREAD_ID)
            self.assertEqual(catalog["threads"][0]["source_type"], "session_jsonl")
            self.assertEqual(catalog["threads"][0]["parser_version"], 1)
            self.assertEqual(catalog["threads"][0]["cache_status"], "rendered")
            self.assertGreaterEqual(catalog["threads"][0]["processing_duration_ms"], 0.0)
            self.assertRegex(catalog["threads"][0]["cache_key"], r"^[0-9a-f]{64}$")
            self.assertRegex(catalog["threads"][0]["timeline_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(len(catalog["source_files"]), 1)
            self.assertRegex(catalog["source_files"][0]["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(processing_profile["job_id"], "run-fixture")
            self.assertEqual(processing_profile["thread_count"], 1)
            self.assertEqual(processing_profile["rendered_thread_count"], 1)
            self.assertEqual(processing_profile["reused_thread_count"], 0)
            self.assertEqual(processing_profile["slowest_threads"][0]["thread_id"], FIXTURE_THREAD_ID)
            self.assertEqual(current["job_id"], "run-fixture")
            self.assertEqual(current["state"], "completed")
            self.assertEqual(current["processing_mode"], "full_rebuild")
            self.assertEqual(current["reused_thread_count"], 0)
            self.assertEqual(current["rendered_thread_count"], 1)
            self.assertTrue(current["archive_path"].endswith("TimelineForWindowsCodex-export-run-fixture.zip"))
            self.assertTrue(current["processing_profile_path"].endswith("processing_profile.json"))
            self.assertIn('"state": "completed"', refresh_history_text)
            self.assertIn('"processing_mode": "full_rebuild"', refresh_history_text)

            self.assertEqual(environment_ledger["observation_count"], 5)
            self.assertEqual(len(environment_ledger["custom_instructions"]), 2)
            self.assertEqual(len(environment_ledger["model_profiles"]), 2)
            self.assertEqual(len(environment_ledger["client_runtimes"]), 1)
            self.assertEqual(environment_ledger["custom_instructions"][0]["id"], "CI-001")
            self.assertIn("Prefer thread history plus environment ledger.", environment_ledger["custom_instructions"][1]["text"])
            self.assertIn("## Transcript", timeline_text)
            self.assertIn("## Thread-local system notes", timeline_text)
            self.assertIn("../environment/ledger.md", timeline_text)
            self.assertIn("Observed thread names from the selected sources", timeline_text)
            self.assertIn("| User", timeline_text)
            self.assertIn("| Assistant", timeline_text)
            self.assertIn("Environment ledger / 環境台帳", timeline_text)
            self.assertIn("Attachments / 添付ファイル", timeline_text)
            self.assertIn("000.txt", timeline_text)
            self.assertIn("[email]", timeline_text)
            self.assertIn("token=[redacted]", timeline_text)
            self.assertNotIn("hello@example.com", timeline_text)
            self.assertNotIn("secret123", timeline_text)
            self.assertIn(f"threads/{FIXTURE_THREAD_ID}.md", timeline_index_text)
            self.assertNotIn(str(job_dir / "threads" / FIXTURE_THREAD_ID / "timeline.md"), timeline_index_text)
            self.assertIn("Included / 含まれるもの", export_readme)
            self.assertIn("Known gaps / 既知の欠損・未収録", export_readme)
            self.assertIn("Confirmed thread rename events are not reconstructed", export_readme)

            archive_path = Path(result["archive_path"])
            self.assertTrue(archive_path.exists())
            with ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                zipped_status = json.loads(archive.read("status.json").decode("utf-8"))
                zipped_result = json.loads(archive.read("result.json").decode("utf-8"))

            self.assertIn("readme.html", names)
            self.assertIn("environment/observations.jsonl", names)
            self.assertIn("environment/ledger.json", names)
            self.assertIn("environment/ledger.md", names)
            self.assertIn("catalog.json", names)
            self.assertIn("processing_profile.json", names)
            self.assertIn("update_manifest.json", names)
            self.assertIn(f"threads/{FIXTURE_THREAD_ID}.md", names)

            self.assertEqual(zipped_status["state"], "completed")
            self.assertEqual(zipped_status["current_stage"], "completed")
            self.assertEqual(zipped_result["state"], "completed")
            self.assertEqual(zipped_result["archive_path"], str(archive_path))

    def test_process_job_honors_date_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            job_dir = self._create_job_dir(
                Path(temp_dir),
                fixture_root=FIXTURE_CODEX_HOME,
                thread_id=FIXTURE_THREAD_ID,
                preferred_title="Codex timeline sample thread",
                first_prompt_excerpt="Please summarize the last week of work for [email].",
                include_tool_outputs=True,
                date_from="2026-04-04",
                date_to="2026-04-04",
            )

            process_job(job_dir)

            status = read_json(job_dir / "status.json")
            result = read_json(job_dir / "result.json")
            timeline_text = (job_dir / "threads" / FIXTURE_THREAD_ID / "timeline.md").read_text(encoding="utf-8")

            self.assertEqual(status["state"], "completed")
            self.assertEqual(result["event_count"], 0)
            self.assertEqual(result["segment_count"], 0)
            self.assertIn("No transcript messages were available for the selected filters.", timeline_text)

    def test_process_job_parses_archived_thread_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            job_dir = self._create_job_dir(
                Path(temp_dir),
                fixture_root=ARCHIVED_FIXTURE_ROOT,
                thread_id=ARCHIVED_THREAD_ID,
                preferred_title="Archived timeline source",
                first_prompt_excerpt="Summarize follow-up for [email] with token=[redacted]",
                include_tool_outputs=True,
            )

            process_job(job_dir)

            result = read_json(job_dir / "result.json")
            environment_ledger = read_json(job_dir / "environment" / "ledger.json")
            timeline_text = (job_dir / "threads" / ARCHIVED_THREAD_ID / "timeline.md").read_text(encoding="utf-8")

            self.assertEqual(result["state"], "completed")
            self.assertEqual(result["thread_count"], 1)
            self.assertGreaterEqual(result["event_count"], 6)
            self.assertIn("[email]", timeline_text)
            self.assertIn("token=[redacted]", timeline_text)
            self.assertEqual(len(environment_ledger["client_runtimes"]), 1)
            self.assertIn("I am checking the archived thread and preparing a handoff.", timeline_text)
            self.assertIn("Archived thread summary is ready.", timeline_text)

    def test_process_job_parses_rich_archived_thread_read_messages(self) -> None:
        rich_thread_id = "bbbbbbbb-1111-2222-3333-cccccccccccc"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            fixture_root = temp_root / "archived-rich-root"
            thread_reads_root = fixture_root / "_codex_tools" / "thread_reads"
            ensure_dir(thread_reads_root)
            thread_reads_path = thread_reads_root / f"{rich_thread_id}.json"
            thread_reads_path.write_text(
                json.dumps(
                    {
                        "thread": {
                            "id": rich_thread_id,
                            "name": "Rich archived thread",
                            "createdAt": "2026-04-10T12:00:00Z",
                            "updatedAt": "2026-04-10T12:30:00Z",
                            "cwd": "C:\\apps\\TimelineForWindowsCodex",
                            "cliVersion": "0.1.0",
                            "source": "desktop",
                            "modelProvider": "openai",
                            "turns": [
                                {
                                    "items": [
                                        {
                                            "type": "userMessage",
                                            "id": "item-user-1",
                                            "content": [
                                                {
                                                    "type": "text",
                                                    "text": "Please review the archived context for rich@example.com. token=rich-secret",
                                                },
                                                {
                                                    "type": "input_file",
                                                    "path": "C:\\Users\\amano\\Desktop\\rich-note.txt",
                                                },
                                            ],
                                        },
                                        {
                                            "type": "agentMessage",
                                            "id": "item-agent-1",
                                            "phase": "conversation",
                                            "content": [
                                                {
                                                    "type": "output_text",
                                                    "text": "I found the archived summary and prepared the export.",
                                                },
                                                {
                                                    "type": "local_file",
                                                    "path": "C:\\Users\\amano\\Desktop\\reply-note.md",
                                                },
                                            ],
                                        },
                                    ]
                                }
                            ],
                        }
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            job_dir = self._create_job_dir(
                temp_root,
                fixture_root=fixture_root,
                thread_id=rich_thread_id,
                preferred_title="Rich archived thread",
                first_prompt_excerpt="Please review the archived context for [email]. token=[redacted]",
                include_tool_outputs=True,
            )

            process_job(job_dir)

            result = read_json(job_dir / "result.json")
            timeline_text = (job_dir / "threads" / rich_thread_id / "timeline.md").read_text(encoding="utf-8")

            self.assertEqual(result["state"], "completed")
            self.assertGreaterEqual(result["event_count"], 3)
            self.assertIn("I found the archived summary and prepared the export.", timeline_text)
            self.assertIn("rich-note.txt", timeline_text)
            self.assertIn("reply-note.md", timeline_text)
            self.assertIn("[email]", timeline_text)
            self.assertIn("token=[redacted]", timeline_text)
            self.assertNotIn("rich@example.com", timeline_text)
            self.assertNotIn("rich-secret", timeline_text)

    def test_process_job_skips_malformed_session_record_and_completes(self) -> None:
        malformed_thread_id = "99999999-aaaa-bbbb-cccc-dddddddddddd"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            fixture_root = temp_root / "codex-home-malformed"
            session_dir = fixture_root / "sessions" / "2026" / "04" / "21"
            ensure_dir(session_dir)
            session_path = session_dir / f"rollout-2026-04-21T12-00-00-{malformed_thread_id}.jsonl"
            session_path.write_text(
                "\n".join(
                    [
                        '{"timestamp":"2026-04-21T12:00:00Z","type":"session_meta","payload":{"id":"99999999-aaaa-bbbb-cccc-dddddddddddd","cwd":"C:\\\\CodexWorkspace","originator":"Codex Desktop","cli_version":"0.1.0","source":"desktop","model_provider":"openai"}}',
                        '{"timestamp":"2026-04-21T12:00:05Z","type":"event_msg","payload":{"type":"user_message","message":"Need the raw conversation export."}}',
                        '{"timestamp":"2026-04-21T12:00:06Z","type":"response_item","payload":{"type":"function_call_output","call_id":"call-001","output":"python3 - <<\'PY\'',
                        'print("broken multiline output")',
                        'PY"}}',
                        '{"timestamp":"2026-04-21T12:00:10Z","type":"event_msg","payload":{"type":"agent_message","message":"I will keep the original message chain.","phase":"conversation"}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            job_dir = self._create_job_dir(
                temp_root,
                fixture_root=fixture_root,
                thread_id=malformed_thread_id,
                preferred_title="Malformed session sample",
                first_prompt_excerpt="Need the raw conversation export.",
                include_tool_outputs=True,
            )

            process_job(job_dir)

            status = read_json(job_dir / "status.json")
            result = read_json(job_dir / "result.json")
            timeline_text = (job_dir / "threads" / malformed_thread_id / "timeline.md").read_text(encoding="utf-8")

            self.assertEqual(status["state"], "completed")
            self.assertEqual(result["state"], "completed")
            self.assertEqual(result["thread_count"], 1)
            self.assertEqual(result["event_count"], 3)
            self.assertIn("Need the raw conversation export.", timeline_text)
            self.assertIn("I will keep the original message chain.", timeline_text)

    def test_export_thread_markdown_name_uses_thread_id(self) -> None:
        filename = export_thread_markdown_name("画像嗜好学習と判別を設計}}៌**", FIXTURE_THREAD_ID)

        self.assertEqual(filename, f"{FIXTURE_THREAD_ID}.md")

    def test_process_job_compares_against_previous_current_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            first_job_dir = self._create_job_dir(
                temp_root,
                job_id="run-fixture-1",
                fixture_root=FIXTURE_CODEX_HOME,
                thread_id=FIXTURE_THREAD_ID,
                preferred_title="Codex timeline sample thread",
                first_prompt_excerpt="Please summarize the last week of work for [email].",
                include_tool_outputs=True,
            )
            process_job(first_job_dir)

            second_job_dir = self._create_job_dir(
                temp_root,
                job_id="run-fixture-2",
                fixture_root=FIXTURE_CODEX_HOME,
                thread_id=FIXTURE_THREAD_ID,
                preferred_title="Codex timeline sample thread",
                first_prompt_excerpt="Please summarize the last week of work for [email].",
                include_tool_outputs=True,
            )
            process_job(second_job_dir)

            second_catalog = read_json(second_job_dir / "catalog.json")
            current = read_json(second_job_dir.parent / "current.json")
            update_manifest = read_json(second_job_dir / "update_manifest.json")
            worker_log = (second_job_dir / "logs" / "worker.log").read_text(encoding="utf-8")

            self.assertEqual(second_catalog["threads"][0]["cache_status"], "reused")
            self.assertRegex(second_catalog["threads"][0]["cache_key"], r"^[0-9a-f]{64}$")
            self.assertEqual(current["processing_mode"], "incremental_reuse")
            self.assertEqual(current["reused_thread_count"], 1)
            self.assertEqual(current["rendered_thread_count"], 0)
            self.assertEqual(update_manifest["previous_job_id"], "run-fixture-1")
            self.assertEqual(update_manifest["processing_mode"], "incremental_reuse")
            self.assertEqual(update_manifest["counts"]["unchanged"], 1)
            self.assertEqual(update_manifest["counts"]["new"], 0)
            self.assertEqual(update_manifest["threads"][0]["status"], "unchanged")
            self.assertEqual(update_manifest["threads"][0]["cache_status"], "reused")
            self.assertIn(f"Reused {FIXTURE_THREAD_ID}", worker_log)

    def test_failed_refresh_keeps_previous_current_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            first_job_dir = self._create_job_dir(
                temp_root,
                job_id="run-fixture-success",
                fixture_root=FIXTURE_CODEX_HOME,
                thread_id=FIXTURE_THREAD_ID,
                preferred_title="Codex timeline sample thread",
                first_prompt_excerpt="Please summarize the last week of work for [email].",
                include_tool_outputs=True,
            )
            process_job(first_job_dir)

            failing_job_dir = self._create_job_dir(
                temp_root,
                job_id="run-fixture-failed",
                fixture_root=FIXTURE_CODEX_HOME,
                thread_id=FIXTURE_THREAD_ID,
                preferred_title="Changed title forces reparse",
                first_prompt_excerpt="Please summarize the last week of work for [email].",
                include_tool_outputs=True,
            )

            with patch(
                "timeline_for_windows_codex_worker.processor.parse_thread_events",
                side_effect=RuntimeError("forced failure"),
            ):
                with self.assertRaises(RuntimeError):
                    process_job(failing_job_dir)

            current = read_json(temp_root / "current.json")
            refresh_history_text = (temp_root / "refresh-history.jsonl").read_text(encoding="utf-8")

            self.assertEqual(current["job_id"], "run-fixture-success")
            self.assertIn('"job_id": "run-fixture-failed"', refresh_history_text)
            self.assertIn('"state": "failed"', refresh_history_text)

    def _create_job_dir(
        self,
        temp_root: Path,
        *,
        job_id: str = "run-fixture",
        fixture_root: Path,
        thread_id: str,
        preferred_title: str,
        first_prompt_excerpt: str,
        include_tool_outputs: bool,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> Path:
        job_dir = ensure_dir(temp_root / job_id)
        ensure_dir(job_dir / "threads")
        ensure_dir(job_dir / "environment")
        ensure_dir(job_dir / "export")
        ensure_dir(job_dir / "logs")

        request = JobRequest(
            job_id=job_id,
            created_at="2026-04-05T00:00:00Z",
            primary_codex_home_path=str(fixture_root),
            backup_codex_home_paths=[],
            include_archived_sources=True,
            include_tool_outputs=include_tool_outputs,
            redaction_profile="strict",
            date_from=date_from,
            date_to=date_to,
            selected_threads=[
                ThreadSelection(
                    thread_id=thread_id,
                    preferred_title=preferred_title,
                    observed_thread_names=[
                        ObservedThreadName(
                            name=preferred_title,
                            observed_at="2026-04-03T09:12:40Z",
                            source="session_index.jsonl",
                        ),
                        ObservedThreadName(
                            name=f"{preferred_title} renamed",
                            observed_at="2026-04-03T09:13:40Z",
                            source="thread_reads",
                        ),
                    ],
                    source_root_path=str(fixture_root),
                    source_root_kind="primary",
                    session_path="",
                    updated_at="2026-04-03T09:12:40Z",
                    first_user_message_excerpt=first_prompt_excerpt,
                )
            ],
        )

        write_json_atomic(job_dir / "request.json", request.to_dict())
        return job_dir


if __name__ == "__main__":
    unittest.main()
