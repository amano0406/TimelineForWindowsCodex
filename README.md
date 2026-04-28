# TimelineForWindowsCodex

`TimelineForWindowsCodex` converts local Codex Desktop history on Windows into Markdown, JSON, environment ledger files, fidelity reports, and ZIP packages.

This product is CLI-only. There is no Web UI. The main use case is to create a reliable export package that can be read later or handed to another LLM.

## What It Does

- Reads local Codex history from a configured `.codex` source root.
- Discovers threads from `session_index.jsonl`, `sessions/**/*.jsonl`, archived `thread_reads`, and `state_5.sqlite` fallback metadata.
- Preserves user / assistant message chains as thread Markdown.
- Keeps environment observations such as custom instructions, model profile, and client runtime in `environment/*`.
- Writes fidelity reports so missing or limited data is visible.
- Produces `TimelineForWindowsCodex-export.zip`.

## What It Does Not Do

- It does not provide a Web UI.
- It does not edit or rewrite source Codex transcript files.
- It does not treat `state_5.sqlite` as the primary transcript source.
- It does not export binary attachment contents.
- It does not reconstruct confirmed rename events beyond observed thread-name points.
- It does not recover exact custom-instruction save timestamps.

## Source Strategy

Priority:

1. `sessions/**/*.jsonl`
2. archived `_codex_tools/thread_reads/*.json`
3. `state_5.sqlite` as discovery / fallback metadata only

The source roots should be treated as read-only. The exported artifacts, not the Web UI, are the reviewable product output.

## Output Layout

Each run writes a run directory under the configured outputs root:

```text
<outputs-root>/
  <run-id>/
    request.json
    status.json
    result.json
    manifest.json
    fidelity_report.json
    fidelity_report.md
    catalog.json
    update_manifest.json
    logs/
    environment/
    threads/
    export/TimelineForWindowsCodex-export.zip
  current.json
  refresh-history.jsonl
```

The ZIP contains the human-readable entry files:

- `readme.html`
- `threads/index.md`
- `threads/<thread_id>.md`
- `environment/ledger.md`
- `fidelity_report.md`
- `catalog.json`
- `update_manifest.json`

## CLI Usage

Run from the repository root:

```bash
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m timeline_for_windows_codex_worker discover \
  --primary-root /mnt/c/Users/amano/.codex \
  --include-archived-sources
```

Create an export for all discovered threads:

```bash
TIMELINE_FOR_WINDOWS_CODEX_OUTPUTS_ROOT=/mnt/c/Codex/archive/TimelineForWindowsCodex/outputs \
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m timeline_for_windows_codex_worker run \
  --primary-root /mnt/c/Users/amano/.codex \
  --include-archived-sources \
  --include-tool-outputs \
  --redaction-profile strict \
  --format json
```

Create an export for one or more selected threads:

```bash
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m timeline_for_windows_codex_worker run \
  --primary-root /mnt/c/Users/amano/.codex \
  --thread-id 11111111-2222-3333-4444-555555555555 \
  --format json
```

Inspect previous runs:

```bash
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m timeline_for_windows_codex_worker list-jobs --format json

PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m timeline_for_windows_codex_worker show-job <run-id> --format json
```

Notes:

- Omit `--thread-id` to export all discovered threads.
- Pass `--thread-id` multiple times for a multi-thread export.
- CLI defaults are loaded from `configs/runtime.defaults.json` unless overridden by environment variables or command options.

## Docker Compose

Docker Compose now runs only the Python worker daemon. It does not expose a browser UI.

```bash
cp .env.example .env
docker compose build
docker compose up
```

Mounted source roots are read-only:

- `/input/codex-home`
- `/input/codex-backup`
- `/input/codex-root`

Default host variables:

- `HOST_CODEX_HOME`
- `HOST_CODEX_BACKUP_HOME`
- `HOST_CODEX_ROOT`

## Testing

Worker integration tests:

```bash
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m unittest discover -s /mnt/c/apps/TimelineForWindowsCodex/worker/tests -v
```

CLI smoke examples:

```bash
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m timeline_for_windows_codex_worker discover --format json

PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m timeline_for_windows_codex_worker run --format json
```

## Current Boundary

Included:

- thread discovery from `session_index.jsonl`, `sessions/**/*.jsonl`, `state_5.sqlite`, and archived `thread_reads`
- single-thread, multi-thread, and all-thread export
- thread Markdown focused on raw user / assistant message chains
- `threads/<thread_id>.md` export naming
- observed thread-name points
- environment ledger
- fidelity report
- ZIP export
- current artifact pointer and refresh history
- unchanged thread artifact reuse

Deferred:

- richer archived `thread_reads` item coverage
- rich file-edit extraction
- confirmed thread rename events beyond point-in-time observations
- exact custom-instruction save timestamps beyond first observation in selected threads
- binary attachment export
- broader state database enrichment beyond discovery / fallback metadata
