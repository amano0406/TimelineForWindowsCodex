# CLI

[Back to README](../README.md)

Windows users should use `cli.bat` from the repository root. It runs the PowerShell implementation with the expected execution policy and executes the command inside the Docker Compose worker service.

## Settings Commands

```powershell
.\cli.bat settings init
.\cli.bat settings status
.\cli.bat settings master show
.\cli.bat settings master set C:\TimelineData\windows-codex
```

- `settings init` creates `settings.json` from `settings.example.json` when it is missing.
- `settings status` reports the active settings and source mount status.
- `settings master show` prints the configured master artifact directory.
- `settings master set <path>` updates the configured master artifact directory.

## Item Commands

```powershell
.\cli.bat items list --json
.\cli.bat items list --page 2 --page-size 50 --json
.\cli.bat items refresh --json
.\cli.bat items refresh --download-to C:\TimelineData\windows-codex-downloads --json
.\cli.bat items download --to C:\TimelineData\windows-codex-downloads
```

- `items list` reads the current master artifacts and returns items newest-first.
- `items list` returns every item by default.
- `--page` and `--page-size` are optional and should be used only when paging is useful.
- `items refresh` reads the mounted Codex history and updates the configured master output root.
- `items refresh --download-to <folder>` refreshes the master output and then creates a ZIP package.
- `items download --to <folder>` creates a ZIP package from the current master output.
- Omit `--item-id` to refresh or download every discovered item.
- Pass `--item-id` multiple times, or pass comma-separated ids, for selected items.

## Normal Operation

Start the worker service before normal CLI use:

```powershell
.\start.bat
```

Stop the worker service when finished:

```powershell
.\stop.bat
```

Run the operational validation suite:

```powershell
.\test-operational.bat
```
