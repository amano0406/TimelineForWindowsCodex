# AGENTS.md

## Repo purpose

This repository is `TimelineForWindowsCodex`.
Its job is to turn local Codex Desktop history on Windows into timeline-oriented artifacts, environment ledgers, and export packages for later review and LLM handoff.

## Must preserve

- Keep the product local-first.
- Treat raw session JSONL plus exported artifacts as the source of truth. The web UI is an inspection console, not the primary evidence source.
- Do not delete, overwrite, mass-move, or mass-rename source transcript data.
- Keep gaps, warnings, missing-source cases, and fidelity limits visible instead of hiding them.
- Preserve the current export contract unless a breaking change is explicitly approved.
- Prefer fixed source/output/state roots by default rather than arbitrary one-off path workflows.

## Product-specific guardrails

- Prefer `sessions/**/*.jsonl` when available.
- Treat `state_5.sqlite` as discovery/fallback metadata, not the primary transcript source.
- Keep source roots read-only when mounted into Docker.
- Preserve thread history, environment ledger, and fidelity report traceability.
- If the web app exposes a port, prefer localhost bind rather than broad LAN exposure.

## Standard model

```text
InputSource = configured Codex source root
InputItem   = discovered thread or archived source item
Job         = export request for selected thread(s) and options
Run         = one execution attempt for that export
Artifact    = thread markdown, environment outputs, reports, and ZIP
```

## Safe work without extra confirmation

- read-only investigation
- `AGENTS.md`, README, docs, and `.env.example` updates
- non-destructive small code fixes
- localhost bind / port safety fixes
- lightweight unit or smoke checks
- Docker build / compose smoke checks
- export metadata consistency fixes that do not remove user data

## Ask before doing these

- deleting or rewriting transcript sources
- mass move / mass rename of user files
- direct editing of `state_5.sqlite` or source session files
- breaking export contract changes
- repo or product rename
- new hosted/cloud dependency
- deploy, external posting, or secret changes
- broad architecture rewrites

## Before finishing

- Read the README and source-strategy docs first.
- Keep source ingestion read-only unless the task explicitly says otherwise.
- Update docs when export behavior, fidelity behavior, or source strategy changes.

## Report format

```md
## Current state
## Completed
## Changed files
## Source strategy check
## Export contract check
## Tests
## Risks
## Next safe tasks
## Human decisions needed
```
