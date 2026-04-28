# TimelineForWindowsCodex

`TimelineForWindowsCodex` converts local Codex Desktop history on Windows into Markdown, JSON, environment ledger files, fidelity reports, and ZIP packages.

This product is CLI-only. There is no Web UI. The main use case is to refresh configured local Codex history sources and create a reliable export package that can be read later or handed to another LLM.

## What It Does

- Reads local Codex history from one or more configured source roots.
- Discovers threads from `session_index.jsonl`, `sessions/**/*.jsonl`, archived `thread_reads`, and `state_5.sqlite` fallback metadata.
- Preserves user / assistant message chains as thread Markdown.
- Keeps environment observations such as custom instructions, model profile, and client runtime in `environment/*`.
- Writes fidelity reports so missing or limited data is visible.
- Produces timestamped `TimelineForWindowsCodex-export-<run-id>.zip` files.
- Reuses unchanged thread artifacts during refresh runs.

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

## Settings

Normal Docker Compose operation stores persistent settings in the Docker volume at `/shared/app-data/settings.json`.

The repo also keeps a Git-managed settings template:

```text
C:\apps\TimelineForWindowsCodex\settings.example.json
```

If a host-side `settings.json` is used for development, it is intentionally not committed. It is treated like `.env`: each machine keeps its own source roots and output root.

Use this setup through Docker:

```powershell
.\tfwc.ps1 settings init
.\tfwc.ps1 settings validate
```

The settings file contains application-level configuration:

- `source_roots`: one or more Codex history directories to read
- `outputs_root`: fixed output directory for refresh artifacts
- `redaction_profile`: `strict` or `loose`
- `include_archived_sources`: whether archived thread reads are included
- `include_tool_outputs`: whether tool output text is included when available

`.env` remains for runtime/container variables. If a different settings location is needed, set `TIMELINE_FOR_WINDOWS_CODEX_SETTINGS_PATH`.

The cross-product rationale is summarized in `SETTINGS_POLICY.md`.

## Output Layout

Each refresh writes a run directory under the configured outputs root:

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
    processing_profile.json
    update_manifest.json
    logs/
    environment/
    threads/
    export/TimelineForWindowsCodex-export-<run-id>.zip
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
- `processing_profile.json`
- `update_manifest.json`

## CLI Usage

Normal operation is Windows PowerShell first and Docker-only behind it. Use `.\tfwc.ps1 ...` from PowerShell as the front door. WSL / direct `docker compose ...` usage remains available as a development back door.

Host direct execution with `python3 -m timeline_for_windows_codex_worker ...` is disabled unless an explicit test/development override is set.

Run commands from the repository root:

Show fixed settings:

```powershell
.\tfwc.ps1 settings show
```

Configure source roots and output root:

```powershell
.\tfwc.ps1 settings add-source /input/codex-home

.\tfwc.ps1 settings add-source /input/codex-backup

.\tfwc.ps1 settings set-output /shared/outputs
```

Validate configured paths:

```powershell
.\tfwc.ps1 settings validate
```

Initialize the usual local settings in one step:

```powershell
.\tfwc.ps1 settings init
```

Refresh from configured sources:

```powershell
.\tfwc.ps1 refresh --format json
```

The refresh result reports the ZIP path, thread/event counts, new/changed/unchanged counts, reused/rendered thread counts, fidelity warning count, and slowest threads.

Show the latest artifact:

```powershell
.\tfwc.ps1 current
```

Copy the latest ZIP to a handoff directory:

```powershell
.\tfwc.ps1 export-current --to /shared/outputs/handoff
```

`export-current` does not overwrite an existing file unless `--overwrite` is passed.

Refresh and copy the latest ZIP in one command:

```powershell
.\tfwc.ps1 handoff --to /shared/outputs/handoff
```

`handoff` validates settings, runs `refresh`, and then copies the completed ZIP. Use a path mounted inside the container, such as `/shared/outputs/handoff`.

Discover threads directly:

```powershell
.\tfwc.ps1 discover `
  --primary-root /input/codex-home `
  --include-archived-sources
```

Create an ad-hoc export for all discovered threads:

```powershell
.\tfwc.ps1 run `
  --primary-root /input/codex-home `
  --include-archived-sources `
  --include-tool-outputs `
  --redaction-profile strict `
  --format json
```

Create an export for one or more selected threads:

```powershell
.\tfwc.ps1 run `
  --primary-root /input/codex-home `
  --thread-id 11111111-2222-3333-4444-555555555555 `
  --format json
```

Inspect previous runs:

```powershell
.\tfwc.ps1 list-jobs --format json

.\tfwc.ps1 show-job <run-id> --format json
```

Notes:

- Omit `--thread-id` to export all discovered threads.
- Pass `--thread-id` multiple times for a multi-thread export.
- `refresh` uses `settings.json` first, then falls back to `configs/runtime.defaults.json`.
- Ad-hoc commands can still use command options such as `--primary-root` and `--backup-root`.
- CLI defaults are loaded from `configs/runtime.defaults.json` unless overridden by settings, environment variables, or command options.

## Docker Compose

Docker Compose now runs only the Python worker daemon. It does not expose a browser UI. In normal Windows operation, use the PowerShell wrapper rather than typing Docker commands directly.

```powershell
cp .env.example .env
.\tfwc.ps1 build
.\tfwc.ps1 up
```

Mounted source roots are read-only:

- `/input/codex-home`
- `/input/codex-backup`
- `/input/codex-root`

Default host variables:

- `HOST_CODEX_HOME`
- `HOST_CODEX_BACKUP_HOME`
- `HOST_CODEX_ROOT`

Docker Compose stores its settings at `/shared/app-data/settings.json` through `TIMELINE_FOR_WINDOWS_CODEX_SETTINGS_PATH`, so container settings survive compose restarts through the named volume.

The cross-product Docker-only rationale is summarized in `DOCKER_ONLY_POLICY.md`.

## Testing

Automated tests may run host Python only with the explicit test override:

```bash
TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN=1 \
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m unittest discover -s /mnt/c/apps/TimelineForWindowsCodex/worker/tests -v
```

Docker CLI smoke examples:

```powershell
.\tfwc.ps1 discover --format json

.\tfwc.ps1 run --format json
```

Docker production-like final smoke test:

```powershell
.\tfwc.ps1 smoke
```

This uses Docker Compose for all product commands, mounts real Codex history sources read-only, writes only to a temporary host output root, runs refresh twice, verifies required ZIP entries, and checks that the second refresh reuses unchanged threads.

Host production-like final smoke test is development-only and sets the host-run test override internally:

```bash
python3 tests/smoke/run_production_like_refresh.py
```

By default, both smoke scripts delete their temporary output after the check. Use `--preserve-output` only when manual inspection is needed.

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
- fixed settings for multiple source roots and output root
- `settings validate` for source/output path checks
- `settings init` for one-step local setup
- `refresh` command for normal operation
- `current` and `export-current` for latest ZIP handoff
- `handoff` for one-command refresh and ZIP handoff
- Docker-only guard for normal CLI execution
- timestamped ZIP filename through the run id
- `processing_profile.json` with slowest thread diagnostics

Deferred:

- richer archived `thread_reads` item coverage
- rich file-edit extraction
- confirmed thread rename events beyond point-in-time observations
- exact custom-instruction save timestamps beyond first observation in selected threads
- binary attachment export
- broader state database enrichment beyond discovery / fallback metadata
