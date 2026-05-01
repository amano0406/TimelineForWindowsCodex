# TimelineForWindowsCodex

`TimelineForWindowsCodex` converts local Codex Desktop history on Windows into per-thread master artifacts, diagnostics, and ZIP handoff packages.

Japanese README: [README.ja.md](README.ja.md)

This product is CLI-only. There is no Web UI. The main use case is to refresh configured local Codex history sources and create a reliable export package that can be read later or handed to another LLM.

## What It Does

- Reads local Codex history from one or more configured source roots.
- Discovers threads from `session_index.jsonl`, `sessions/**/*.jsonl`, archived `thread_reads`, and `state_5.sqlite` fallback metadata.
- Preserves user / assistant / system message chains as per-thread `thread.json` files.
- Writes per-thread `convert.json` files with stable conversion metadata.
- Keeps environment observations such as custom instructions, model profile, and client runtime in run diagnostics.
- Writes fidelity reports so missing or limited data is visible.
- Produces timestamped `TimelineForWindowsCodex-export-<run-id>.zip` files.
- Reuses unchanged thread artifacts during refresh runs.
- Leaves date filtering and readable global timeline rendering to downstream timeline products.

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
```

The settings file contains application-level configuration:

- `source_roots`: one or more Codex history directories to read
- `outputs_root`: fixed output directory for refresh artifacts
- `redaction_profile`: `strict` or `loose`
- `include_archived_sources`: whether archived thread reads are included
- `include_tool_outputs`: optional diagnostics only. Keep `false` for normal user/assistant transcript exports.
- `include_compaction_recovery`: optional deep recovery from compaction `replacement_history`. Keep `false` for normal refresh performance.

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
    README.md
    fidelity_report.json
    fidelity_report.md
    catalog.json
    processing_profile.json
    update_manifest.json
    logs/
    environment/
    export/TimelineForWindowsCodex-export-<run-id>.zip
  <thread-id>/
    convert.json
    thread.json
  current.json
  refresh-history.jsonl
```

The ZIP is intentionally small and contains only the handoff files:

- `README.md`
- `<thread_id>/convert.json`
- `<thread_id>/thread.json`

`environment/*`, `fidelity_report.*`, `catalog.json`, `processing_profile.json`, and `update_manifest.json` remain in the run directory for inspection and diagnostics, but they are not part of the normal download ZIP.

## CLI Usage

Normal operation is Windows PowerShell first and Docker-only behind it. Use `.\tfwc.ps1 ...` from PowerShell as the front door. WSL / direct `docker compose ...` usage remains available as a development back door.

Host direct execution with `python3 -m timeline_for_windows_codex_worker ...` is disabled unless an explicit test/development override is set.

Run commands from the repository root.

## CLI Concept

The CLI follows the same broad concept as `TimelineForAudio`, but this product does not expose separate source/artifact/job-control surfaces. The normal user-facing model is fixed settings, Codex history items, and run inspection.

| Command group | Role |
|---|---|
| `settings` | Manage fixed local configuration. Inputs are multiple; the master output root is single. |
| `items` | Inspect discoverable Codex threads, refresh the export, and copy the latest ZIP. |
| `runs` | Inspect previous refresh runs. This is a diagnostic/history surface, not the main operation surface. |

Main commands:

```powershell
.\tfwc.ps1 settings init
.\tfwc.ps1 settings status
.\tfwc.ps1 settings inputs add /input/codex-home
.\tfwc.ps1 settings inputs list
.\tfwc.ps1 settings inputs remove input-1234abcd
.\tfwc.ps1 settings master set /shared/outputs
.\tfwc.ps1 settings master show

.\tfwc.ps1 items list --json
.\tfwc.ps1 items refresh --json
.\tfwc.ps1 items download --to /shared/outputs/handoff
.\tfwc.ps1 runs list --json
.\tfwc.ps1 runs show --run-id <run-id> --json
```

Refresh from configured settings:

```powershell
.\tfwc.ps1 items refresh --json
```

Refresh and copy the latest ZIP in one command:

```powershell
.\tfwc.ps1 items refresh --download-to /shared/outputs/handoff --json
```

Refresh from explicit sources without changing settings:

```powershell
.\tfwc.ps1 items refresh `
  --primary-root /input/codex-home `
  --include-archived-sources `
  --redaction-profile strict `
  --json
```

Refresh selected items:

```powershell
.\tfwc.ps1 items refresh `
  --primary-root /input/codex-home `
  --item-id 11111111-2222-3333-4444-555555555555 `
  --json
```

Notes:

- Omit `--item-id` to export all discovered items.
- Pass `--item-id` multiple times, or pass comma-separated ids, for a multi-item export.
- `items refresh` uses `settings.json` first, then falls back to `configs/runtime.defaults.json`.
- `settings inputs remove` accepts the generated `input-...` id from `settings inputs list`.
- `items download` copies the latest ZIP and does not overwrite an existing file unless `--overwrite` is passed.
- CLI defaults are loaded from `configs/runtime.defaults.json` unless overridden by settings, environment variables, or command options.

## Docker Compose

Docker Compose runs the Python worker CLI. It does not expose a browser UI. In normal Windows operation, use the PowerShell wrapper rather than typing Docker commands directly.

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
.\tfwc.ps1 items list --json

.\tfwc.ps1 items refresh --json
```

Docker production-like final smoke test:

```powershell
.\tfwc.ps1 smoke
```

This uses Docker Compose for all product commands, mounts real Codex history sources read-only, writes only to a temporary host output root, runs refresh twice, verifies the per-thread `convert.json` / `thread.json` ZIP contract, and checks that the second refresh reuses unchanged threads.

Host production-like final smoke test is development-only and sets the host-run test override internally:

```bash
python3 tests/smoke/run_production_like_refresh.py
```

By default, both smoke scripts delete their temporary output after the check. Use `--preserve-output` only when manual inspection is needed.

## Current Boundary

Included:

- thread discovery from `session_index.jsonl`, `sessions/**/*.jsonl`, `state_5.sqlite`, and archived `thread_reads`
- single-thread, multi-thread, and all-thread export
- per-thread `thread.json` files focused on raw-like user / assistant / system message chains
- per-thread `convert.json` files for conversion metadata
- optional compaction `replacement_history` user / assistant recovery
- `<thread_id>/thread.json` and `<thread_id>/convert.json` export naming
- observed thread-name points
- environment ledger in run diagnostics
- fidelity report in run diagnostics
- small ZIP handoff with `README.md` and per-thread `convert.json` / `thread.json` files
- current artifact pointer and refresh history
- unchanged thread artifact reuse
- fixed settings for multiple source roots and output root
- `settings init` for one-step local setup
- `settings inputs` and `settings master` commands aligned with TimelineForAudio
- `items list`, `items refresh`, and `items download` for normal operation
- `items refresh --download-to` for one-command refresh and ZIP handoff
- Docker-only guard for normal CLI execution
- timestamped ZIP filename through the run id
- `processing_profile.json` with slowest thread diagnostics

Not included in normal `thread.json`:

- tool call details, terminal command output, reasoning summaries, and fine-grained file diffs
- date range filtering; this product manages the full available Codex thread set

Deferred:

- richer archived `thread_reads` item coverage
- rich file-edit extraction
- confirmed thread rename events beyond point-in-time observations
- exact custom-instruction save timestamps beyond first observation in selected threads
- binary attachment export
- broader state database enrichment beyond discovery / fallback metadata
