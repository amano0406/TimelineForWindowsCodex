# TimelineForWindowsCodex

`TimelineForWindowsCodex` is a local CLI tool that reads Windows Codex Desktop history and keeps normalized per-thread JSON artifacts.

Japanese README: [README.ja.md](README.ja.md)

This product is CLI-only. There is no Web UI. The main job is to keep a fixed master artifact directory up to date, then create a small ZIP package when the user wants to hand the data to another LLM or downstream Timeline product.

## README Role

This README is the operational front door for users. It should quickly answer what the product does, how to start it, what it outputs, and how to verify it.

Design decisions, progress tracking, and policy notes live in separate documents:

- Progress and remaining work: [TODO.md](TODO.md)
- Settings policy: [SETTINGS_POLICY.md](SETTINGS_POLICY.md)
- Docker-first policy: [DOCKER_ONLY_POLICY.md](DOCKER_ONLY_POLICY.md)

## Position In The Timeline Family

`TimelineForWindowsCodex` is the **Codex Desktop history intake / export adapter** in the Timeline product family.

Its responsibility is to read Windows-local Codex thread history, convert it into thread-scoped evidence data that downstream Timeline products or LLMs can consume, keep that data in a fixed master output root, and package selected items as ZIP files when needed.

Principles:

- Treat source history as the read-only source of truth.
- Preserve raw-ish user / assistant / system message chains before summarization or interpretation.
- Leave global readable timeline rendering, analysis, and visualization to downstream products.
- Keep `timeline.json` and `convert_info.json` as the stable per-thread output contract.
- Prefer local, reproducible CLI / Docker Compose operation over a Web UI.

## Quick Start

Run these commands from the repository root:

```powershell
cd /d C:\apps\TimelineForWindowsCodex
.\start.bat
.\cli.bat settings status
.\cli.bat items refresh --json
.\cli.bat items download --to C:\TimelineData\windows-codex-downloads --json
```

Run the operational check suite:

```powershell
.\test-operational.bat
```

## What It Does

- Reads the fixed local Codex history roots mounted by Docker Compose.
- Discovers threads from `sessions/**/*.jsonl`, `session_index.jsonl`, archived `thread_reads`, and `state_5.sqlite` fallback metadata.
- Writes one master directory per thread.
- Stores normalized conversation text in `timeline.json`.
- Stores source/conversion metadata in `convert_info.json`.
- Lists items newest-first with optional paging.
- Skips unchanged thread output when the source and conversion settings have not changed.
- Builds timestamped download ZIP files on demand.
- Leaves global readable timeline rendering, date filtering, and higher-level analysis to downstream products.

## What It Does Not Do

- It does not provide a Web UI.
- It does not keep job/run directories in the master output root.
- It does not write `current.json` or `refresh-history.jsonl`.
- It does not edit source Codex transcript files.
- It does not treat `state_5.sqlite` as the primary transcript source.
- It does not export binary attachment contents.
- It does not reconstruct exact custom-instruction save timestamps.
- It does not export tool-call details, terminal output, reasoning summaries, or fine-grained file diffs into `timeline.json`.

## Settings

Normal Docker Compose operation uses the repo-root local settings file:

```text
C:\apps\TimelineForWindowsCodex\settings.json
```

`settings.json` is intentionally not committed. It is treated like `.env`: each machine keeps its own output root. The launcher scripts create it from `settings.example.json` when it is missing.

The settings file contains:

- `schemaVersion`: settings file format version
- `outputRoot`: the fixed master artifact directory

The Codex source roots are not user settings. Docker Compose mounts the current Codex home and the known backup location as fixed read-only inputs:

- `C:\Users\amano\.codex` -> `/input/codex-home`
- `C:\Codex\archive\migration-backup-2026-03-27\codex-home` -> `/input/codex-backup`

Default example:

```json
{
  "schemaVersion": 1,
  "outputRoot": "C:\\TimelineData\\windows-codex"
}
```

Archive sources are always read. Tool-output logs, terminal output, and compaction recovery are not user-configurable settings. Conversation text is exported without URL/email/token redaction because this tool is intended to preserve local evidence for later LLM analysis.

## Output Contract

Master output:

```text
<masterPath>/
  <thread_id>/
    convert_info.json
    timeline.json
```

Download ZIP:

```text
README.md
items/
  <thread_id>/
    convert_info.json
    timeline.json
```

`timeline.json` is the final normalized conversation item:

```json
{
  "schema_version": 1,
  "application": "TimelineForWindowsCodex",
  "thread_id": "...",
  "title": "...",
  "created_at": "...",
  "updated_at": "...",
  "messages": [
    {
      "role": "user",
      "created_at": "...",
      "text": "..."
    }
  ]
}
```

`convert_info.json` contains source fingerprint, conversion settings, counts, and known gaps for that item.

## CLI Usage

Windows uses the `.bat` launcher as the stable front door. It runs the PowerShell implementation with the expected execution policy from the repository root:

```powershell
.\cli.bat settings init
.\cli.bat settings status
.\cli.bat settings master show
.\cli.bat settings master set C:\TimelineData\windows-codex

.\cli.bat items list --json
.\cli.bat items list --page 2 --page-size 50 --json
.\cli.bat items refresh --json
.\cli.bat items refresh --download-to C:\TimelineData\windows-codex-downloads --json
.\cli.bat items download --to C:\TimelineData\windows-codex-downloads
```

Notes:

- `items list` is sorted by `updated_at` descending. The newest item is shown first.
- `items list` defaults to all items.
- Pass `--page` / `--page-size` only when you want paging. `--page-size` defaults to `100` when paging is used.
- Omit `--item-id` to refresh or download all discovered items.
- Pass `--item-id` multiple times, or pass comma-separated ids, for selected items.
- `items refresh` updates the fixed master directory.
- `items download` builds a ZIP from the current master directory.
- Host direct Python execution is blocked for normal use. Tests may set `TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN=1`.

## Docker Compose

Docker Compose keeps one project service container, `timeline-for-windows-codex-worker-1`, and the CLI launcher executes commands inside it with `docker compose exec`. CLI commands start the existing worker with `--no-build`; use `start.bat` when the image needs to be built or rebuilt. CLI commands should not create `worker-run-*` one-off containers. This product does not expose a browser UI.

```powershell
cp .env.example .env
.\start.bat
.\cli.bat settings status
.\cli.bat items refresh --json
```

Source mounts are read-only. `settings.json` is mounted into the container as `/shared/app-data/settings.json` and survives container rebuilds because it lives in the repo root.

Operational tests do not rewrite the normal `settings.json`. They override `HOST_TFWC_SETTINGS_FILE`, `HOST_TFWC_APP_DATA`, `HOST_TFWC_DOWNLOADS`, and `COMPOSE_PROJECT_NAME` with temporary values so fixture inputs and temporary outputs stay isolated.

Stop the worker service container:

```powershell
.\stop.bat
```

Uninstall Docker resources:

```powershell
.\uninstall.bat
```

The uninstall script does not delete Codex source history, the configured `outputRoot`, or `downloads`. It asks separately before deleting the app-data Docker volume or local `settings.json`.

## Testing

Unit tests:

```bash
TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN=1 \
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m unittest discover -s /mnt/c/apps/TimelineForWindowsCodex/worker/tests -v
```

Docker production-like smoke test:

```powershell
python tests/smoke/run_docker_compose_refresh.py
```

The smoke test runs refresh twice, verifies the fixed master contract, verifies the download ZIP contract, and checks that unchanged threads are skipped on the second refresh.
By default it prints only compact run summaries. Pass `--include-full-payload` only when item-level debug output is needed.

Local `cli.ps1` download smoke test:

```powershell
python tests/smoke/run_cli_ps1_download.py
```

This test writes a fixture-only `settings.json` to a temporary settings path, runs `cli.ps1 items refresh`, runs `cli.ps1 items download` in a dedicated Docker Compose project, and verifies the ZIP layout. It does not modify the normal local `settings.json` or the normal worker service container.

Raw source to timeline fidelity audit:

```powershell
python tests/smoke/run_fidelity_audit.py
```

This audit reads the expected message chain from representative raw source transcripts, then compares it with generated or existing `timeline.json` / `convert_info.json` artifacts. It checks role, timestamp, text, attachment labels, message count, and absence of legacy `thread.json` / `convert.json` files.

Windows launcher operational smoke test:

```powershell
python tests/smoke/run_windows_launcher_flow.py
```

This test runs `start.bat`, `cli.bat settings status`, `cli.bat items refresh`, `cli.bat items download`, and `stop.bat` in sequence. It uses a temporary settings path, fixture sources, and a dedicated Docker Compose project, so it does not modify the normal local `settings.json`, the normal worker service container, or the normal master output root.

Run the normal operational stability suite:

```powershell
.\test-operational.bat
```

This runs the `cli.ps1` download smoke test, raw source to timeline fidelity audit, the Windows launcher operational smoke test, and the Docker production-like smoke test in sequence. It uses temporary settings / source / output paths, so it does not modify the normal master output root.
