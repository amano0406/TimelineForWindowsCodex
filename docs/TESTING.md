# Testing

[Back to README](../README.md)

Use `test-operational.bat` for the normal stability check. It runs fixture-backed operational tests without modifying the normal local `settings.json`, the normal worker service container, or the normal master output root.

```powershell
.\test-operational.bat
```

## Included Operational Checks

The operational suite covers:

- worker-hosted local API smoke test
- local API smoke test against the already running worker API
- worker unit tests for source parsing, refresh, download, and API handlers

## Individual Checks

Unit tests:

```powershell
set TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN=1
set PYTHONPATH=C:\apps\TimelineForWindowsCodex\worker\src
python -m unittest discover -s C:\apps\TimelineForWindowsCodex\worker\tests -v
```

## What The Checks Verify

- The fixed master contract is `<thread_id>\convert_info.json` and `<thread_id>\timeline.json`.
- Download ZIP packages contain `README.md` and `items\<thread_id>\convert_info.json` / `items\<thread_id>\timeline.json`.
- The second refresh skips unchanged items when source fingerprints and conversion settings have not changed.
- Generated `timeline.json` preserves the expected role, timestamp, text, attachment labels, and message counts from representative raw source transcripts.
- Legacy `thread.json` and `convert.json` files are not produced.
