# TimelineForWindowsCodex

`TimelineForWindowsCodex` turns local Codex Desktop history on Windows into thread history markdown, environment ledger artifacts, and ZIP export packages.
The web app is positioned as a local inspection console: it shows what was captured, what is missing, how reliable the current artifact is, and what can be downloaded.

As of 2026-04-22 Asia/Tokyo, the repository is at an MVP scaffold stage with a working end-to-end vertical slice.

## Current scope

- `web`: ASP.NET Core Razor Pages
- `worker`: Python daemon
- `cli`: discover / create-job / run / list-jobs / show-job
- `single_thread`, `multi_thread`, `all_threads`

## Current UI

- `/`
  - inspect the current artifact
  - review coverage, warnings, and refresh history
  - jump to the latest ZIP and export details
- `/threads`
  - review discovered threads
  - filter and select threads
  - export the selected range
- `/environment`
  - inspect source roots, defaults, source types, warnings, and limitations
- `/exports`
  - review current artifact status
  - inspect active refreshes
  - browse export history and download ZIP outputs
- `/exports/{id}`
  - view request metadata
  - inspect generated timelines, fidelity, and update summary
  - download the generated ZIP package
- `/settings`
  - set default source roots
  - set default language and processing flags

Current localization support:

- Japanese
- English

## Current inputs

Primary source types currently supported:

- current `.codex` home
  - `session_index.jsonl`
  - `sessions/**/*.jsonl`
  - `state_5.sqlite`
- backup `.codex` homes with the same structure
- archived Codex exports
  - `_codex_tools/thread_reads/*.json`

Current source strategy:

- prefer session JSONL when present
- use `state_5.sqlite` only to improve discovery and fallback metadata
- use archived `thread_reads` when session JSONL is missing or when archived source import is enabled
- use `thread_name` / `thread.name` as the thread-name source when available

## Current exported bundle

- per-thread timeline markdown
- thread-local system notes inside each thread markdown
- thread index markdown
- export `readme.html`
- environment ledger markdown
- environment observations JSONL
- environment ledger JSON
- ZIP export bundle

Current output emphasis:

- preserve the raw user / assistant message chain as markdown
- use `threads/<thread_id>.md` as the exported file naming rule
- keep thread-local observed thread-name points in the thread file
- include user-side mode and attachment file names when the source exposes them
- separate cross-thread environment changes into `environment/*`
- keep the bundle easy to hand to another LLM with `readme.html` as the entry point

## Development

1. Copy `.env.example` to `.env` and adjust the host paths.
2. Make sure Docker Desktop is running.
3. If you use WSL, enable Docker Desktop WSL integration for this distro.

```bash
cp .env.example .env
docker compose build
docker compose up
```

Default host variables:

- `HOST_CODEX_HOME`
- `HOST_CODEX_BACKUP_HOME`
- `HOST_CODEX_ROOT`
- `HOST_WEB_PORT`

The app mounts these source roots read-only inside the containers:

- `/input/codex-home`
- `/input/codex-backup`
- `/input/codex-root`

If you run Compose from PowerShell or `cmd.exe`, use Windows-style values in `.env`.
If you run Compose from WSL, use `/mnt/c/...` style values in `.env`.

## CLI

The worker supports a local CLI path with the same basic lifecycle as the web flow, even though the public web UI is framed around sync / inspect / export instead of job management.

Examples:

```bash
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m timeline_for_windows_codex_worker discover \
  --primary-root /mnt/c/Users/amano/.codex \
  --include-archived-sources
```

```bash
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m timeline_for_windows_codex_worker run \
  --primary-root /mnt/c/Users/amano/.codex \
  --thread-id 11111111-2222-3333-4444-555555555555 \
  --format json
```

```bash
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m timeline_for_windows_codex_worker list-jobs --format json
```

Notes:

- omit `--thread-id` to run all discovered threads
- pass `--thread-id` multiple times for a multi-thread export
- CLI defaults are loaded from `runtime.defaults.json` when available

## Current local verification

Verified on this machine:

- web + worker vertical slice using real local Codex data
- thread discovery from `C:\Users\amano\.codex`
- thread discovery fallback from `state_5.sqlite`
- archived `thread_reads` import
- thread history / environment ledger / ZIP generation
- ja / en UI switching
- bilingual export guidance in `readme.html`, `threads/index.md`, and timeline headers
- thread selection UX on `/threads` with filter + select-all helpers
- worker integration test against a fixed fixture Codex home
- HTTP smoke path for:
  - session JSONL source
  - `state_5.sqlite` + archived `thread_reads` source
  - `/threads -> export -> /exports/{id} -> ZIP download`
- `docker compose up --build -d` with real local Codex data on `2026-04-22` Asia/Tokyo
- Docker Compose runs for:
  - single thread
  - 3 selected threads
  - all discovered threads
- worker CLI verification for:
  - thread discovery from current + archived fixtures
  - single-thread export
  - multi-thread export
  - all-thread export
  - `list-jobs` and `show-job`

## Current MVP boundary

Included:

- thread discovery from `session_index.jsonl`, `state_5.sqlite`, session JSONL files, and archived `thread_reads`
- run creation from selected thread ids
- CLI parity for thread discovery, selection, execution, and job inspection
- basic worker rendering for one or more threads, including archived `thread_reads`
- thread history markdown focused on raw user / assistant message chains
- `threads/<thread_id>.md` export naming
- observed thread-name points from `session_index.jsonl` and archived `thread_reads`
- thread selection helpers for large thread lists in the web UI
- cross-thread environment ledger for custom instructions, model profiles, and client runtime observations
- ZIP bundle centered on `threads/*` and `environment/*`
- ZIP export

Deferred:

- richer `thread/read` item coverage beyond message / reasoning / plan / compaction
- rich file-edit extraction
- confirmed thread rename events beyond point-in-time name observations
- exact custom-instruction save timestamps beyond first observation in selected threads
- full artifact auto-linking and binary attachment export
- broader state database enrichment beyond thread catalog fallback

## Testing

Worker integration:

```bash
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m unittest discover -s /mnt/c/apps/TimelineForWindowsCodex/worker/tests -v
```

CLI examples:

```bash
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m timeline_for_windows_codex_worker discover --format json

PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m timeline_for_windows_codex_worker run --format json
```

Web smoke:

```bash
python3 /mnt/c/apps/TimelineForWindowsCodex/tests/smoke/run_web_smoke.py
```

Notes:

- the worker test uses `tests/fixtures/codex-home-min`
- archived-source coverage uses `tests/fixtures/archived-root-min`
- the web smoke launches the ASP.NET Core app with Windows `dotnet.exe`
- the smoke script creates temporary outputs under `.tmp/` and removes them after the run

## Next priorities

- expand archived `thread_reads` parsing beyond the currently supported item types
- derive richer file-edit and terminal events
- tighten what should be exported for non-text attachments
- polish CLI text output for long thread lists and larger job inventories
