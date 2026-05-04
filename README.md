# TimelineForWindowsCodex

## What This Product Does

`TimelineForWindowsCodex` is a local CLI tool that converts Windows Codex Desktop history into per-thread JSON artifacts. It preserves the user / assistant / system message chain in a form that can be handed to another LLM or a downstream Timeline product. The source Codex history is read-only; the tool writes only to the configured output root and optional download folder.

This product is CLI-only.

## Input

The tool reads fixed Codex history roots through Docker Compose read-only mounts.

- Current Codex home: `C:\Users\amano\.codex`
- Known archived Codex home: `C:\Codex\archive\migration-backup-2026-03-27\codex-home`

The main transcript source is `sessions/**/*.jsonl`. `session_index.jsonl`, archived `thread_reads`, and `state_5.sqlite` fallback metadata are used only where appropriate for discovery and metadata.

## Output

The primary output is the master artifact directory configured by `settings.json`.

```text
<outputRoot>/
  <thread_id>/
    convert_info.json
    timeline.json
```

Download ZIP files contain the same item structure under `items/`:

```text
README.md
items/
  <thread_id>/
    convert_info.json
    timeline.json
```

## Quick Start

Run from the repository root:

```powershell
cd /d C:\apps\TimelineForWindowsCodex
.\start.bat
.\cli.bat settings status
.\cli.bat items refresh --json
.\cli.bat items download --to C:\TimelineData\windows-codex-downloads --json
```

## Sample

Sample-backed validation uses fixture Codex homes in:

- `tests/fixtures/codex-home-min`
- `tests/fixtures/archived-root-min`

A dedicated packaged sample output is planned but not yet included.

## Common Commands

Use the `.bat` launchers on Windows:

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

Run the operational check suite:

```powershell
.\test-operational.bat
```

## Detailed Docs

- [CLI](docs/CLI.md): read this when you need command details beyond the common commands above.
- [Outputs](docs/OUTPUTS.md): read this when you need the master directory and download ZIP contract.
- [Runtime](docs/RUNTIME.md): read this when you need Docker, settings, source mount, and uninstall behavior.
- [Testing](docs/TESTING.md): read this when you need validation commands and what each test checks.
