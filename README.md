# windowscodex2timeline

`windowscodex2timeline` turns local Codex Desktop history on Windows into timeline-oriented markdown, JSON, and ZIP handoff packages.

Current scaffold scope:

- `web`: ASP.NET Core Razor Pages
- `worker`: Python daemon
- `single_thread` first
- primary input:
  - current `.codex`
  - optional backup `.codex`
- primary output:
  - thread timeline markdown
  - events JSONL
  - segments JSON
  - handoff JSON / markdown
  - ZIP export

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
- timeline / handoff / ZIP generation
- ja / en UI switching
- worker integration test against a fixed fixture Codex home
- HTTP smoke path for `jobs/new -> create -> process -> details -> ZIP download`

Not fully verified in this environment:

- `docker compose up` end-to-end, because Docker Desktop daemon was not running at `2026-04-04 11:50 Asia/Tokyo`

## Current MVP boundary

Included:

- thread discovery from `session_index.jsonl` plus session JSONL files
- run creation from selected thread ids
- basic worker rendering for one or more threads
- ZIP export

Deferred:

- full `thread/read` import
- rich file-edit extraction
- advanced segmenting
- full artifact auto-linking

## Testing

Worker integration:

```bash
PYTHONPATH=/mnt/c/apps/windowscodex2timeline/worker/src \
python3 -m unittest discover -s /mnt/c/apps/windowscodex2timeline/worker/tests -v
```

Web smoke:

```bash
python3 /mnt/c/apps/windowscodex2timeline/tests/smoke/run_web_smoke.py
```

Notes:

- the worker test uses `tests/fixtures/codex-home-min`
- the web smoke launches the ASP.NET Core app with Windows `dotnet.exe`
- the smoke script creates temporary outputs under `.tmp/` and removes them after the run
