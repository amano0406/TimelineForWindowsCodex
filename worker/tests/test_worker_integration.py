from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER_SRC = REPO_ROOT / "worker" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))

from timeline_for_windows_codex_worker.contracts import RefreshRequest, ObservedThreadName, ThreadSelection  # noqa: E402
from timeline_for_windows_codex_worker.fs_utils import ensure_dir, read_json  # noqa: E402
from timeline_for_windows_codex_worker.processor import build_download_archive, process_refresh  # noqa: E402
from timeline_for_windows_codex_worker.timeline import (  # noqa: E402
    THREAD_CONVERT_FILE_NAME,
    THREAD_FINAL_FILE_NAME,
    export_thread_dir_name,
)


FIXTURE_CODEX_HOME = REPO_ROOT / "tests" / "fixtures" / "codex-home-min"
FIXTURE_THREAD_ID = "11111111-2222-3333-4444-555555555555"
ARCHIVED_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "archived-root-min"
ARCHIVED_THREAD_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class ProcessRefreshIntegrationTests(unittest.TestCase):
    maxDiff = None

    def test_process_refresh_builds_master_items_and_download_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            master_root = Path(temp_dir) / "master"
            request = self._make_request(
                fixture_root=FIXTURE_CODEX_HOME,
                thread_id=FIXTURE_THREAD_ID,
                preferred_title="Codex timeline sample thread",
                first_prompt_excerpt="Please summarize the last week of work for [email].",
            )

            first_summary = process_refresh(request, master_root)
            second_summary = process_refresh(request, master_root)

            thread_dir = master_root / FIXTURE_THREAD_ID
            thread_payload = read_json(thread_dir / THREAD_FINAL_FILE_NAME)
            convert_payload = read_json(thread_dir / THREAD_CONVERT_FILE_NAME)
            message_text = "\n".join(str(message.get("text") or "") for message in thread_payload["messages"])
            attachment_names = "\n".join(
                str(attachment)
                for message in thread_payload["messages"]
                for attachment in message.get("attachments", [])
            )

            self.assertEqual(first_summary["state"], "completed")
            self.assertEqual(first_summary["update_counts"]["new"], 1)
            self.assertEqual(first_summary["rendered_thread_count"], 1)
            self.assertEqual(second_summary["update_counts"]["unchanged"], 1)
            self.assertEqual(second_summary["reused_thread_count"], 1)
            self.assertFalse((master_root / "current.json").exists())
            self.assertFalse((master_root / "refresh-history.jsonl").exists())
            self.assertFalse((thread_dir / "convert.json").exists())
            self.assertEqual(thread_payload["application"], "TimelineForWindowsCodex")
            self.assertEqual(thread_payload["thread_id"], FIXTURE_THREAD_ID)
            self.assertEqual(thread_payload["title"], "Codex timeline sample thread")
            self.assertGreaterEqual(len(thread_payload["messages"]), 1)
            self.assertNotIn("observed_thread_name", message_text)
            self.assertIn("000.txt", attachment_names)
            self.assertIn("hello@example.com", message_text)
            self.assertIn("token=secret123", message_text)
            self.assertNotIn("git status", message_text)
            self.assertNotIn("On branch main", message_text)
            self.assertEqual(convert_payload["application"], "TimelineForWindowsCodex")
            self.assertEqual(convert_payload["thread_id"], FIXTURE_THREAD_ID)
            self.assertEqual(convert_payload["title"], "Codex timeline sample thread")
            self.assertEqual(convert_payload["source_session"]["type"], "session_jsonl")
            self.assertRegex(convert_payload["source_session"]["sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(convert_payload["conversion"]["cache_key"], r"^[0-9a-f]{64}$")

            download = build_download_archive(master_root, Path(temp_dir) / "download", overwrite=False)
            archive_path = Path(str(download["destination_path"]))
            self.assertTrue(archive_path.exists())
            with ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                zipped_thread = json.loads(
                    archive.read(f"items/{FIXTURE_THREAD_ID}/{THREAD_FINAL_FILE_NAME}").decode("utf-8")
                )
                zipped_convert = json.loads(
                    archive.read(f"items/{FIXTURE_THREAD_ID}/{THREAD_CONVERT_FILE_NAME}").decode("utf-8")
                )

            self.assertIn("README.md", names)
            self.assertIn(f"items/{FIXTURE_THREAD_ID}/{THREAD_FINAL_FILE_NAME}", names)
            self.assertIn(f"items/{FIXTURE_THREAD_ID}/{THREAD_CONVERT_FILE_NAME}", names)
            self.assertNotIn("readme.html", names)
            self.assertNotIn("status.json", names)
            self.assertEqual(zipped_thread["thread_id"], FIXTURE_THREAD_ID)
            self.assertEqual(zipped_convert["thread_id"], FIXTURE_THREAD_ID)

    def test_process_refresh_recovers_compacted_replacement_history_without_tool_noise(self) -> None:
        compacted_thread_id = "22222222-3333-4444-5555-666666666666"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            fixture_root = temp_root / "codex-home-compacted"
            session_dir = fixture_root / "sessions" / "2026" / "04" / "20"
            ensure_dir(session_dir)
            session_path = session_dir / f"rollout-2026-04-20T10-00-00-{compacted_thread_id}.jsonl"
            session_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "timestamp": "2026-04-20T10:00:00Z",
                                "type": "session_meta",
                                "payload": {
                                    "id": compacted_thread_id,
                                    "cwd": "C:\\apps\\TimelineForWindowsCodex",
                                },
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-04-20T10:00:05Z",
                                "type": "event_msg",
                                "payload": {
                                    "type": "user_message",
                                    "message": "Visible prompt before compaction.",
                                    "text_elements": [{"path": "C:\\Users\\amano\\Desktop\\visible.txt"}],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-04-20T10:00:10Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "function_call_output",
                                    "output": "docker compose logs with implementation details",
                                },
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-04-20T10:05:00Z",
                                "type": "compacted",
                                "payload": {
                                    "replacement_history": [
                                        {
                                            "type": "message",
                                            "role": "user",
                                            "content": [
                                                {"type": "input_text", "text": "Visible prompt before compaction."},
                                                {"type": "input_file", "path": "C:\\Users\\amano\\Desktop\\visible.txt"},
                                            ],
                                        },
                                        {
                                            "type": "message",
                                            "role": "user",
                                            "content": [
                                                {"type": "input_text", "text": "Recovered earlier prompt with attachment."},
                                                {"type": "input_file", "path": "C:\\Users\\amano\\Desktop\\earlier.txt"},
                                            ],
                                        },
                                        {
                                            "type": "message",
                                            "role": "assistant",
                                            "content": [
                                                {"type": "output_text", "text": "Recovered earlier assistant answer."}
                                            ],
                                        },
                                    ],
                                },
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-04-20T10:06:00Z",
                                "type": "event_msg",
                                "payload": {
                                    "type": "agent_message",
                                    "message": "Latest answer after compaction.",
                                },
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            request = self._make_request(
                fixture_root=fixture_root,
                thread_id=compacted_thread_id,
                preferred_title="Compacted session sample",
                first_prompt_excerpt="Visible prompt before compaction.",
                include_compaction_recovery=True,
            )
            process_refresh(request, temp_root / "master")

            thread_payload = read_json(temp_root / "master" / compacted_thread_id / THREAD_FINAL_FILE_NAME)
            convert_payload = read_json(temp_root / "master" / compacted_thread_id / THREAD_CONVERT_FILE_NAME)
            message_text = "\n".join(str(message.get("text") or "") for message in thread_payload["messages"])
            attachment_names = "\n".join(
                str(attachment)
                for message in thread_payload["messages"]
                for attachment in message.get("attachments", [])
            )

            self.assertEqual(convert_payload["message_count"], 4)
            self.assertEqual(message_text.count("Visible prompt before compaction."), 1)
            self.assertIn("Recovered earlier prompt with attachment.", message_text)
            self.assertIn("Recovered earlier assistant answer.", message_text)
            self.assertIn("earlier.txt", attachment_names)
            self.assertNotIn("docker compose logs with implementation details", message_text)
            self.assertTrue(
                any(
                    str(message.get("source") or "") == "compaction_replacement_history"
                    for message in thread_payload["messages"]
                )
            )
            self.assertTrue(
                any("compaction replacement_history" in limitation for limitation in convert_payload["known_gaps"])
            )

    def test_process_refresh_parses_archived_thread_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            request = self._make_request(
                fixture_root=ARCHIVED_FIXTURE_ROOT,
                thread_id=ARCHIVED_THREAD_ID,
                preferred_title="Archived timeline source",
                first_prompt_excerpt="Summarize follow-up for archived@example.com with token=legacy-secret",
            )

            summary = process_refresh(request, Path(temp_dir) / "master")

            thread_payload = read_json(Path(temp_dir) / "master" / ARCHIVED_THREAD_ID / THREAD_FINAL_FILE_NAME)
            convert_payload = read_json(Path(temp_dir) / "master" / ARCHIVED_THREAD_ID / THREAD_CONVERT_FILE_NAME)
            message_text = "\n".join(str(message.get("text") or "") for message in thread_payload["messages"])

            self.assertEqual(summary["thread_count"], 1)
            self.assertEqual(convert_payload["source_session"]["type"], "thread_read_json")
            self.assertIn("archived@example.com", message_text)
            self.assertIn("token=legacy-secret", message_text)
            self.assertIn("I am checking the archived thread and preparing a handoff.", message_text)
            self.assertIn("Archived thread summary is ready.", message_text)

    def test_process_refresh_parses_rich_archived_thread_read_messages(self) -> None:
        rich_thread_id = "bbbbbbbb-1111-2222-3333-cccccccccccc"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            fixture_root = temp_root / "archived-rich-root"
            thread_reads_root = fixture_root / "_codex_tools" / "thread_reads"
            ensure_dir(thread_reads_root)
            (thread_reads_root / f"{rich_thread_id}.json").write_text(
                json.dumps(
                    {
                        "thread": {
                            "id": rich_thread_id,
                            "name": "Rich archived thread",
                            "createdAt": "2026-04-10T12:00:00Z",
                            "updatedAt": "2026-04-10T12:30:00Z",
                            "turns": [
                                {
                                    "items": [
                                        {
                                            "type": "userMessage",
                                            "content": [
                                                {
                                                    "type": "text",
                                                    "text": "Please review rich@example.com. token=rich-secret",
                                                },
                                                {"type": "input_file", "path": "C:\\Users\\amano\\Desktop\\rich-note.txt"},
                                            ],
                                        },
                                        {
                                            "type": "agentMessage",
                                            "content": [
                                                {
                                                    "type": "output_text",
                                                    "text": "I found the archived summary and prepared the export.",
                                                },
                                                {"type": "local_file", "path": "C:\\Users\\amano\\Desktop\\reply-note.md"},
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

            request = self._make_request(
                fixture_root=fixture_root,
                thread_id=rich_thread_id,
                preferred_title="Rich archived thread",
                first_prompt_excerpt="Please review rich@example.com. token=rich-secret",
            )
            process_refresh(request, temp_root / "master")

            thread_payload = read_json(temp_root / "master" / rich_thread_id / THREAD_FINAL_FILE_NAME)
            message_text = "\n".join(str(message.get("text") or "") for message in thread_payload["messages"])
            attachment_names = "\n".join(
                str(attachment)
                for message in thread_payload["messages"]
                for attachment in message.get("attachments", [])
            )

            self.assertIn("I found the archived summary and prepared the export.", message_text)
            self.assertIn("rich-note.txt", attachment_names)
            self.assertIn("reply-note.md", attachment_names)
            self.assertIn("rich@example.com", message_text)
            self.assertIn("token=rich-secret", message_text)

    def test_process_refresh_skips_malformed_session_record_and_completes(self) -> None:
        malformed_thread_id = "99999999-aaaa-bbbb-cccc-dddddddddddd"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            fixture_root = temp_root / "codex-home-malformed"
            session_dir = fixture_root / "sessions" / "2026" / "04" / "21"
            ensure_dir(session_dir)
            (session_dir / f"rollout-2026-04-21T12-00-00-{malformed_thread_id}.jsonl").write_text(
                "\n".join(
                    [
                        '{"timestamp":"2026-04-21T12:00:00Z","type":"session_meta","payload":{"id":"99999999-aaaa-bbbb-cccc-dddddddddddd","cwd":"C:\\\\CodexWorkspace"}}',
                        '{"timestamp":"2026-04-21T12:00:05Z","type":"event_msg","payload":{"type":"user_message","message":"Need the raw conversation export."}}',
                        '{"timestamp":"2026-04-21T12:00:06Z","type":"response_item","payload":{"type":"function_call_output","output":"python3 - <<\'PY\'',
                        'print("broken multiline output")',
                        'PY"}}',
                        '{"timestamp":"2026-04-21T12:00:10Z","type":"event_msg","payload":{"type":"agent_message","message":"I will keep the original message chain."}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            request = self._make_request(
                fixture_root=fixture_root,
                thread_id=malformed_thread_id,
                preferred_title="Malformed session sample",
                first_prompt_excerpt="Need the raw conversation export.",
            )
            summary = process_refresh(request, temp_root / "master")

            thread_payload = read_json(temp_root / "master" / malformed_thread_id / THREAD_FINAL_FILE_NAME)
            message_text = "\n".join(str(message.get("text") or "") for message in thread_payload["messages"])

            self.assertEqual(summary["state"], "completed")
            self.assertEqual(summary["thread_count"], 1)
            self.assertIn("Need the raw conversation export.", message_text)
            self.assertIn("I will keep the original message chain.", message_text)

    def test_export_thread_dir_name_uses_thread_id(self) -> None:
        self.assertEqual(export_thread_dir_name(FIXTURE_THREAD_ID), FIXTURE_THREAD_ID)

    def _make_request(
        self,
        *,
        fixture_root: Path,
        thread_id: str,
        preferred_title: str,
        first_prompt_excerpt: str,
        include_compaction_recovery: bool = False,
    ) -> RefreshRequest:
        return RefreshRequest(
            refresh_id="refresh-fixture",
            created_at="2026-04-05T00:00:00Z",
            primary_codex_home_path=str(fixture_root),
            backup_codex_home_paths=[],
            include_archived_sources=True,
            include_tool_outputs=False,
            include_compaction_recovery=include_compaction_recovery,
            redaction_profile="none",
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
                    ],
                    source_root_path=str(fixture_root),
                    source_root_kind="primary",
                    session_path="",
                    updated_at="2026-04-03T09:12:40Z",
                    first_user_message_excerpt=first_prompt_excerpt,
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
