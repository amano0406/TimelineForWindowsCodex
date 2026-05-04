# Runtime

[Back to README](../README.md)

`TimelineForWindowsCodex` is designed for local Docker Compose operation. Windows launcher scripts are the normal front door.

## Required Runtime

- Windows host with the Codex Desktop history to read.
- Docker Desktop with Docker Compose available.
- PowerShell for the launcher scripts.

The normal user path is:

```powershell
.\start.bat
.\cli.bat settings status
.\cli.bat items refresh --json
.\stop.bat
```

## Docker Compose Service

Docker Compose keeps one project service container:

```text
timeline-for-windows-codex-worker-1
```

CLI commands execute inside that existing worker service with `docker compose exec`. They should not create separate one-off `worker-run-*` containers during normal use.

## Source Mounts

Source Codex history is mounted read-only.

```text
C:\Users\amano\.codex -> /input/codex-home
C:\Codex\archive\migration-backup-2026-03-27\codex-home -> /input/codex-backup
```

The source roots are not user settings. They are part of the local runtime contract and are mounted by Docker Compose.

## Settings

Normal operation uses:

```text
C:\apps\TimelineForWindowsCodex\settings.json
```

`settings.json` is not committed. It is created from `settings.example.json` when missing and is mounted into the container as:

```text
/shared/app-data/settings.json
```

The settings file contains:

```json
{
  "schemaVersion": 1,
  "outputRoot": "C:\\TimelineData\\windows-codex"
}
```

- `schemaVersion` is the settings file format version.
- `outputRoot` is the fixed master artifact directory.

Archive sources are always read. Tool-output logs, terminal output, and compaction recovery are not user-configurable settings. Conversation text is exported without URL/email/token redaction because this tool is intended to preserve local evidence for later LLM analysis.

## Environment Files

`.env` is reserved for Docker mount paths and runtime overrides. `settings.json` stores product settings. Normal product settings and test settings should not be mixed in the same file.

Operational tests override settings and runtime paths with temporary values, including:

- `HOST_TFWC_SETTINGS_FILE`
- `HOST_TFWC_APP_DATA`
- `HOST_TFWC_DOWNLOADS`
- `COMPOSE_PROJECT_NAME`

## Host Execution Guard

Direct host Python execution is blocked for normal use. Tests may set:

```text
TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN=1
```

This keeps normal operation Docker-based while still allowing controlled local test execution.

## Uninstall Behavior

Use:

```powershell
.\uninstall.bat
```

The uninstall script does not delete Codex source history, the configured `outputRoot`, or download folders. It asks separately before deleting local app-data Docker resources or the local `settings.json`.
