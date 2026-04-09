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

from timeline_for_windows_codex_worker.contracts import JobRequest, ThreadSelection  # noqa: E402
from timeline_for_windows_codex_worker.fs_utils import ensure_dir, read_json, write_json_atomic  # noqa: E402
from timeline_for_windows_codex_worker.processor import process_job  # noqa: E402


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
            combined_events = self._read_jsonl(job_dir / "normalized" / "events.jsonl")
            thread_segments = read_json(job_dir / "derived" / f"{FIXTURE_THREAD_ID}.segments.json")
            timeline_text = (job_dir / "threads" / FIXTURE_THREAD_ID / "timeline.md").read_text(encoding="utf-8")
            handoff_text = (job_dir / "llm" / "handoff.md").read_text(encoding="utf-8")

            self.assertEqual(status["state"], "completed")
            self.assertEqual(status["current_stage"], "completed")
            self.assertEqual(result["state"], "completed")
            self.assertEqual(result["thread_count"], 1)
            self.assertEqual(result["event_count"], 7)
            self.assertEqual(result["segment_count"], len(thread_segments))
            self.assertGreaterEqual(result["segment_count"], 3)
            self.assertEqual(manifest["items"][0]["thread_id"], FIXTURE_THREAD_ID)
            self.assertTrue(manifest["items"][0]["session_path"].endswith(".jsonl"))

            rendered_payload = json.dumps(combined_events, ensure_ascii=False)
            self.assertIn("[email]", rendered_payload)
            self.assertIn("token=[redacted]", rendered_payload)
            self.assertNotIn("hello@example.com", rendered_payload)
            self.assertNotIn("secret123", rendered_payload)
            self.assertIn("Terminal block", timeline_text)
            self.assertIn("TimelineForWindowsCodex handoff", handoff_text)

            archive_path = Path(result["archive_path"])
            self.assertTrue(archive_path.exists())
            with ZipFile(archive_path) as archive:
                names = set(archive.namelist())
            self.assertIn("llm/handoff.md", names)
            self.assertIn("normalized/events.jsonl", names)
            self.assertIn("timelines/codex-timeline-sample-thread.md", names)

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
            combined_events = self._read_jsonl(job_dir / "normalized" / "events.jsonl")
            timeline_text = (job_dir / "threads" / FIXTURE_THREAD_ID / "timeline.md").read_text(encoding="utf-8")

            self.assertEqual(status["state"], "completed")
            self.assertEqual(result["event_count"], 0)
            self.assertEqual(result["segment_count"], 0)
            self.assertEqual(combined_events, [])
            self.assertIn("No events were available for the selected filters.", timeline_text)

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
            combined_events = self._read_jsonl(job_dir / "normalized" / "events.jsonl")
            timeline_text = (job_dir / "threads" / ARCHIVED_THREAD_ID / "timeline.md").read_text(encoding="utf-8")

            self.assertEqual(result["state"], "completed")
            self.assertEqual(result["thread_count"], 1)
            self.assertGreaterEqual(result["event_count"], 6)
            rendered_payload = json.dumps(combined_events, ensure_ascii=False)
            self.assertIn("[email]", rendered_payload)
            self.assertIn("token=[redacted]", rendered_payload)
            self.assertIn("Context compacted.", timeline_text)
            self.assertIn("Inspect the archived thread.", timeline_text)

    def _create_job_dir(
        self,
        temp_root: Path,
        *,
        fixture_root: Path,
        thread_id: str,
        preferred_title: str,
        first_prompt_excerpt: str,
        include_tool_outputs: bool,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> Path:
        job_dir = ensure_dir(temp_root / "run-fixture")
        ensure_dir(job_dir / "threads")
        ensure_dir(job_dir / "llm")
        ensure_dir(job_dir / "normalized")
        ensure_dir(job_dir / "derived")
        ensure_dir(job_dir / "export")
        ensure_dir(job_dir / "logs")

        request = JobRequest(
            job_id="run-fixture",
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

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, object]]:
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


if __name__ == "__main__":
    unittest.main()
