# Outputs

[Back to README](../README.md)

`TimelineForWindowsCodex` writes one directory per Codex thread in the configured master output root. The output contract is intentionally small so downstream LLMs and Timeline products can consume conversation evidence without product-specific UI state.

## Master Output Layout

```text
<outputRoot>/
  <thread_id>/
    convert_info.json
    timeline.json
```

- `timeline.json` is the normalized conversation item.
- `convert_info.json` is the conversion metadata for that item.
- Job directories, run logs, caches, `current.json`, and refresh history files are not part of the master output contract.

## Download ZIP Layout

```text
README.md
items/
  <thread_id>/
    convert_info.json
    timeline.json
```

The ZIP `README.md` only explains what generated the package and where the item files are located. The JSON contracts are the same as the master output files.

## timeline.json

`timeline.json` stores the normalized conversation messages for one Codex thread.

```json
{
  "schema_version": 1,
  "application": "TimelineForWindowsCodex",
  "thread_id": "11111111-2222-3333-4444-555555555555",
  "title": "Codex timeline sample thread",
  "created_at": "2026-04-03T09:12:10Z",
  "updated_at": "2026-04-03T09:12:30Z",
  "messages": [
    {
      "role": "user",
      "created_at": "2026-04-03T09:12:10Z",
      "text": "Export this Codex thread into Timeline format.",
      "mode": "default",
      "attachments": [
        "image attached"
      ]
    },
    {
      "role": "assistant",
      "created_at": "2026-04-03T09:12:30Z",
      "text": "I will export the thread into the expected JSON files."
    }
  ]
}
```

### timeline.json Fields

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | number | Output schema version for this file. Current value is `1`. |
| `application` | string | Always `TimelineForWindowsCodex`. |
| `thread_id` | string | Codex thread/session id. This is also the master item directory name after path-safe normalization. |
| `title` | string | Preferred thread title from Codex metadata, or the thread id when no title is available. |
| `created_at` | string/null | Timestamp of the first exported message when available. Falls back to thread metadata. |
| `updated_at` | string/null | Latest known thread update timestamp. |
| `messages` | array | Ordered normalized conversation messages. |

### messages[] Fields

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `role` | string | yes | Normalized actor, usually `user`, `assistant`, `system`, or `unknown`. |
| `created_at` | string/null | yes | Message timestamp when available. |
| `text` | string | yes | Normalized message text. Tool-call payloads and terminal output are intentionally not included. |
| `mode` | string | no | Codex collaboration mode observed for a user message, for example `default` or another local mode value. Omitted when unknown. |
| `attachments` | array of strings | no | Attachment labels only. Binary attachment contents are not exported. |
| `source` | string | no | Parser source marker for recovered messages, for example compaction recovery. Omitted for normal messages. |

Messages are sorted by timestamp, then parser sequence, then actor. The message chain is preserved as raw-ish conversation evidence. This product does not turn it into a global readable timeline, summary, or project analysis.

## convert_info.json

`convert_info.json` stores metadata needed to understand and safely reuse the generated item.

```json
{
  "schema_version": 1,
  "application": "TimelineForWindowsCodex",
  "thread_id": "11111111-2222-3333-4444-555555555555",
  "title": "Codex timeline sample thread",
  "source_session": {
    "type": "session_jsonl",
    "path": "C:\\Users\\amano\\.codex\\sessions\\2026\\04\\03\\rollout-2026-04-03T09-12-00-11111111-2222-3333-4444-555555555555.jsonl",
    "size_bytes": 12345,
    "sha256": "..."
  },
  "source_root_path": "C:\\Users\\amano\\.codex",
  "source_root_kind": "primary",
  "message_count": 2,
  "attachment_count": 1,
  "converted_at": "2026-05-13T19:50:36.708692Z",
  "conversion": {
    "parser_version": 2,
    "render_contract_version": 5,
    "cache_key": "...",
    "redaction_note": "Content is redacted according to the active redaction profile before export."
  },
  "known_gaps": [
    "Attachment labels were preserved, but binary attachment contents were not exported."
  ],
  "timeline_path": "C:\\apps\\Timeline\\data\\to_text\\windows-codex\\11111111-2222-3333-4444-555555555555\\timeline.json"
}
```

### convert_info.json Fields

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | number | Output schema version for this file. Current value is `1`. |
| `application` | string | Always `TimelineForWindowsCodex`. |
| `thread_id` | string | Codex thread/session id. |
| `title` | string | Preferred thread title used for the exported item. |
| `source_session` | object | Source file type and stable fingerprint metadata. |
| `source_root_path` | string | Root directory where the chosen source was found. |
| `source_root_kind` | string | Discovery root label such as `primary`, `backup_1`, `backup_2`. |
| `message_count` | number | Number of exported messages in `timeline.json`. |
| `attachment_count` | number | Number of attachment labels preserved across messages. |
| `converted_at` | string | UTC conversion timestamp. |
| `conversion` | object | Parser/render versions and cache key used for incremental reuse. |
| `known_gaps` | array of strings | Known limitations for this item. Empty when no item-specific gaps were detected. |
| `timeline_path` | string | Path to the generated `timeline.json`. |

### source_session Fields

| Field | Type | Meaning |
| --- | --- | --- |
| `type` | string | `session_jsonl`, `thread_read_json`, `missing`, or `unknown`. |
| `path` | string | Source file path when a file was resolved. |
| `size_bytes` | number | Source file size used for fingerprinting. |
| `sha256` | string | Source file hash used for fingerprinting. |

### conversion Fields

| Field | Type | Meaning |
| --- | --- | --- |
| `parser_version` | number | Parser behavior version. |
| `render_contract_version` | number | Output rendering contract version. |
| `cache_key` | string | Stable key used to skip unchanged item generation. |
| `redaction_note` | string | Notes the active redaction behavior. The current profile is `none` during normal refresh. |

## Worker API JSON Responses

The worker also returns JSON payloads from the local API. These are API responses, not stored master artifacts.

### POST /items/list

```json
{
  "schema_version": 1,
  "state": "completed",
  "item_count": 2,
  "total_items": 2,
  "sort": {
    "order": "desc",
    "fields": ["updated_at", "created_at", "thread_id"]
  },
  "pagination": {
    "mode": "page",
    "page": 1,
    "page_size": 50,
    "total_items": 2,
    "total_pages": 1,
    "offset": 0,
    "range_start": 1,
    "range_end": 2,
    "has_previous": false,
    "has_next": false,
    "returned_items": 2
  },
  "items": [
    {
      "item_id": "11111111-2222-3333-4444-555555555555",
      "thread_id": "11111111-2222-3333-4444-555555555555",
      "preferred_title": "Codex timeline sample thread",
      "observed_thread_names": [],
      "created_at": null,
      "source_root_path": "C:\\Users\\amano\\.codex",
      "source_root_kind": "primary",
      "session_path": "C:\\Users\\amano\\.codex\\sessions\\...",
      "updated_at": "2026-04-03T09:12:30Z",
      "cwd": "C:\\apps\\TimelineForWindowsCodex",
      "first_user_message_excerpt": "Export this Codex thread into Timeline format."
    }
  ]
}
```

`POST /items/list` discovers available Codex source items. It does not read only the master output directory.

### POST /items/refresh

```json
{
  "schema_version": 1,
  "refresh_id": "refresh-20260513T195036-785469ec",
  "state": "completed",
  "master_root": "C:\\apps\\Timeline\\data\\to_text\\windows-codex",
  "completed_at": "2026-05-13T19:50:36.708692Z",
  "thread_count": 2,
  "item_count": 2,
  "message_count": 5,
  "attachment_count": 1,
  "reused_thread_count": 0,
  "rendered_thread_count": 2,
  "processing_mode": "full_rebuild",
  "update_counts": {
    "new": 2,
    "changed": 0,
    "unchanged": 0,
    "missing": 0,
    "degraded": 0
  },
  "processing_duration_ms": 63.498,
  "items": [
    {
      "thread_id": "11111111-2222-3333-4444-555555555555",
      "title": "Codex timeline sample thread",
      "update_status": "new",
      "cache_status": "rendered",
      "source_type": "session_jsonl",
      "source_session_path": "C:\\Users\\amano\\.codex\\sessions\\...",
      "message_count": 2,
      "attachment_count": 1,
      "timeline_path": "C:\\apps\\Timeline\\data\\to_text\\windows-codex\\...\\timeline.json",
      "convert_info_path": "C:\\apps\\Timeline\\data\\to_text\\windows-codex\\...\\convert_info.json",
      "cache_key": "...",
      "known_gaps": []
    }
  ]
}
```

`processing_mode` is `full_rebuild` when all selected items were rendered. It is `incremental_reuse` when at least one unchanged item was reused.

### POST /items/download

```json
{
  "schema_version": 1,
  "state": "completed",
  "destination_path": "C:\\apps\\Timeline\\data\\downloads\\windows-codex\\TimelineForWindowsCodex-export-20260513-195036Z.zip",
  "master_root": "C:\\apps\\Timeline\\data\\to_text\\windows-codex",
  "thread_count": 2,
  "item_count": 2,
  "message_count": 5,
  "attachment_count": 1,
  "items": [
    {
      "thread_id": "11111111-2222-3333-4444-555555555555",
      "item_dir_name": "11111111-2222-3333-4444-555555555555",
      "title": "Codex timeline sample thread",
      "message_count": 2,
      "attachment_count": 1,
      "convert_info_path": "C:\\apps\\Timeline\\data\\to_text\\windows-codex\\...\\convert_info.json",
      "timeline_path": "C:\\apps\\Timeline\\data\\to_text\\windows-codex\\...\\timeline.json"
    }
  ]
}
```

### POST /items/remove

```json
{
  "schema_version": 1,
  "state": "completed",
  "master_root": "C:\\apps\\Timeline\\data\\to_text\\windows-codex",
  "removed_count": 1,
  "item_count": 1,
  "message_count": 2,
  "attachment_count": 1,
  "items": [
    {
      "thread_id": "11111111-2222-3333-4444-555555555555",
      "item_dir_name": "11111111-2222-3333-4444-555555555555",
      "title": "Codex timeline sample thread"
    }
  ]
}
```

`POST /items/remove` deletes only `<outputRoot>/<thread_id>/`. It does not delete Codex source history and does not modify previously created ZIP exports.

## Known Non-Goals

- Binary attachment contents are not exported.
- Fine-grained file diffs are not exported.
- Tool-call details, terminal output, and reasoning summaries are not exported into `timeline.json`.
- Exact custom-instruction save timestamps are not reconstructed.
- `state_5.sqlite` is not treated as the primary transcript source.
