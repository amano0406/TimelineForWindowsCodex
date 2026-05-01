# TimelineForWindowsCodex

`TimelineForWindowsCodex` is a local CLI tool that reads Windows Codex Desktop history and keeps normalized per-thread JSON artifacts.

Japanese README: [README.ja.md](README.ja.md)

This product is CLI-only. There is no Web UI. The main job is to keep a fixed master artifact directory up to date, then create a small ZIP package when the user wants to hand the data to another LLM or downstream Timeline product.

## What It Does

- Reads one or more configured Codex history source roots.
- Discovers threads from `sessions/**/*.jsonl`, `session_index.jsonl`, archived `thread_reads`, and `state_5.sqlite` fallback metadata.
- Writes one master directory per thread.
- Stores normalized conversation text in `timeline.json`.
- Stores source/conversion metadata in `convert_info.json`.
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

`settings.json` is intentionally not committed. It is treated like `.env`: each machine keeps its own source roots and output root. The launcher scripts create it from `settings.example.json` when it is missing.

The settings file contains:

- `source_roots`: one or more Codex history directories to read
- `outputs_root`: the fixed master artifact directory
- `redaction_profile`: `strict` or `loose`
- `include_archived_sources`: whether archived thread reads are included
- `include_tool_outputs`: kept for compatibility, but normal `timeline.json` does not include tool-output logs
- `include_compaction_recovery`: optional deep recovery from compaction `replacement_history`

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

Windows PowerShell is the front door. Run commands from the repository root:

```powershell
.\cli.ps1 settings init
.\cli.ps1 settings status
.\cli.ps1 settings inputs list
.\cli.ps1 settings inputs add /input/codex-home
.\cli.ps1 settings inputs remove input-1234abcd
.\cli.ps1 settings inputs clear
.\cli.ps1 settings master show
.\cli.ps1 settings master set /shared/outputs

.\cli.ps1 items list --json
.\cli.ps1 items refresh --json
.\cli.ps1 items refresh --download-to /shared/downloads --json
.\cli.ps1 items download --to /shared/downloads
```

Notes:

- Omit `--item-id` to refresh or download all discovered items.
- Pass `--item-id` multiple times, or pass comma-separated ids, for selected items.
- `items refresh` updates the fixed master directory.
- `items download` builds a ZIP from the current master directory.
- Host direct Python execution is blocked for normal use. Tests may set `TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN=1`.

## Docker Compose

Docker Compose keeps one project service container, `timeline-for-windows-codex-worker-1`, and `cli.ps1` executes commands inside it with `docker compose exec`. CLI commands should not create `worker-run-*` one-off containers. This product does not expose a browser UI.

```powershell
cp .env.example .env
.\start.ps1
.\cli.ps1 settings status
.\cli.ps1 items refresh --json
```

Source mounts are read-only. `settings.json` is mounted into the container as `/shared/app-data/settings.json` and survives container rebuilds because it lives in the repo root.

Stop the worker service container:

```powershell
.\stop.ps1
```

Uninstall Docker resources:

```powershell
.\uninstall.ps1
```

The uninstall script does not delete Codex source history, `outputs`, or `downloads`. It asks separately before deleting the app-data Docker volume or local `settings.json`.

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
