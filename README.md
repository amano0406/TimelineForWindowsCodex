# TimelineForWindowsCodex

`TimelineForWindowsCodex` turns local Codex Desktop history on Windows into timeline-oriented markdown, JSON, and ZIP handoff packages.

As of 2026-04-06 Asia/Tokyo, the repository is at an MVP scaffold stage with a working end-to-end vertical slice.

## Current scope

- `web`: ASP.NET Core Razor Pages
- `worker`: Python daemon
- `single_thread` first

## Current UI

- `jobs/new`
  - select a Codex source root
  - discover available threads
  - choose date filters and redaction profile
- `jobs`
  - list recent runs
  - inspect progress and download ZIP outputs
- `jobs/{id}`
  - view request metadata
  - inspect generated timelines
  - download the generated ZIP package
- `settings`
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
- use `state_5.sqlite` to improve discovery and fallback metadata
- use archived `thread_reads` when session JSONL is missing or when archived source import is enabled

## Current outputs

- per-thread timeline markdown
- combined `events.jsonl`
- per-thread and combined `segments.json`
- LLM handoff markdown
- LLM handoff JSON
- ZIP export bundle

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

## Current local verification

Verified on this machine:

- web + worker vertical slice using real local Codex data
- thread discovery from `C:\Users\amano\.codex`
- thread discovery fallback from `state_5.sqlite`
- archived `thread_reads` import
- timeline / handoff / ZIP generation
- ja / en UI switching
- worker integration test against a fixed fixture Codex home
- HTTP smoke path for:
  - session JSONL source
  - `state_5.sqlite` + archived `thread_reads` source
  - `jobs/new -> create -> process -> details -> ZIP download`

Not fully verified in this environment:

- `docker compose up` end-to-end, because Docker Desktop daemon was not running during the latest verification pass on `2026-04-06` Asia/Tokyo

## Current MVP boundary

Included:

- thread discovery from `session_index.jsonl`, `state_5.sqlite`, session JSONL files, and archived `thread_reads`
- run creation from selected thread ids
- basic worker rendering for one or more threads, including archived `thread_reads`
- ZIP export

Deferred:

- richer `thread/read` item coverage beyond message / reasoning / plan / compaction
- rich file-edit extraction
- advanced segmenting
- full artifact auto-linking
- broader state database enrichment beyond thread catalog fallback
- Docker Compose end-to-end verification on a live daemon

## Testing

Worker integration:

```bash
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m unittest discover -s /mnt/c/apps/TimelineForWindowsCodex/worker/tests -v
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
- improve segment grouping so timelines are shorter and more readable
- validate the same flow through Docker Compose
