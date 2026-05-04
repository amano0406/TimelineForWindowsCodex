# Outputs

[Back to README](../README.md)

`TimelineForWindowsCodex` writes one directory per Codex thread in the configured master output root. The output contract is intentionally small so downstream LLMs and Timeline products can consume it without product-specific UI state.

## Master Output

```text
<outputRoot>/
  <thread_id>/
    convert_info.json
    timeline.json
```

- `timeline.json` is the normalized conversation item.
- `convert_info.json` is the conversion metadata for that item.
- Job directories, run logs, caches, `current.json`, and refresh history files are not part of the master output contract.

## Download ZIP

```text
README.md
items/
  <thread_id>/
    convert_info.json
    timeline.json
```

The ZIP `README.md` only explains what generated the package and where the item files are located.

## timeline.json

`timeline.json` stores the final normalized thread conversation.

```json
{
  "schema_version": 1,
  "application": "TimelineForWindowsCodex",
  "thread_id": "...",
  "title": "...",
  "created_at": "...",
  "updated_at": "...",
  "messages": [
    {
      "role": "user",
      "created_at": "...",
      "text": "..."
    },
    {
      "role": "assistant",
      "created_at": "...",
      "text": "..."
    },
    {
      "role": "system",
      "created_at": "...",
      "text": "..."
    }
  ]
}
```

The message chain is preserved as raw-ish conversation evidence. This product does not turn it into a global readable timeline, summary, or project analysis.

## convert_info.json

`convert_info.json` contains conversion metadata such as:

- source identifiers and fingerprints
- title and timestamp metadata
- message and attachment counts
- conversion timestamp
- known gaps for the item

The source fingerprint and conversion settings are used to skip unchanged item generation during refresh.

## Known Non-Goals

- Binary attachment contents are not exported.
- Fine-grained file diffs are not exported.
- Tool-call details, terminal output, and reasoning summaries are not exported into `timeline.json`.
- Exact custom-instruction save timestamps are not reconstructed.
- `state_5.sqlite` is not treated as the primary transcript source.
