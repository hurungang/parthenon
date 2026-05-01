---
name: sdd-prompts-sync
description: "Sync SDD (Spec-Driven Development) change-lifecycle slash command prompts across all IDE prompt folders. Use when: syncing change-* prompts, updating SDD commands, sdd-prompts-sync, prompts are out of date, prompt versions differ between IDEs. Scans change-*.prompt.md files across VSCode, VSCode Insiders, Agents Insiders, and .copilot prompt directories, detects version differences by timestamp and content, copies newer files to folders missing them, and AI-merges conflicting edits before syncing everywhere."
argument-hint: "Optional: specific prompt name to sync (e.g. change-apply), or leave blank to sync all"
---

# SDD Prompts Sync

Synchronizes `change-*.prompt.md` slash command files across all IDE prompt directories so every IDE always has the latest version of each SDD lifecycle command.

## Prompt Directories

| Alias | Path |
|-------|------|
| `.copilot` | `~\.copilot\prompts` |
| `code-insiders` | `~\AppData\Roaming\Code - Insiders\User\prompts` |
| `code` | `~\AppData\Roaming\Code\User\prompts` |
| `agents-insiders` | `~\AppData\Roaming\Agents - Insiders\User\prompts` |

## When to Use

- After editing a `change-*` prompt in one IDE and wanting to propagate to all others
- When you notice an IDE is missing a prompt command
- As part of the change-lifecycle skill update workflow
- Routine maintenance to ensure consistency

## Procedure

### Step 1 — Run the Inventory Script

Run [sync-sdd-prompts.ps1](./scripts/sync-sdd-prompts.ps1) with no arguments to produce a structured report:

```powershell
~/.copilot/skills/sdd-prompts-sync/scripts/sync-sdd-prompts.ps1
```

The script outputs one of three statuses per file:
- **MISSING** — file exists in some folders but not all; newest copy will be used
- **DIVERGED** — file exists everywhere but content differs between newer versions; requires AI merge
- **IN-SYNC** — all folders have identical content (may still copy if timestamps differ but content matches)

### Step 2 — Handle MISSING files

For each MISSING file, the script prints the source path (newest version). Copy it to all folders that lack it. The script can do this automatically when passed `-Apply`.

### Step 3 — Handle DIVERGED files (AI merge required)

When two or more folders have the same file at different (newer) timestamps AND different content:

1. Read all differing versions shown in the script output.
2. Identify what changed in each version relative to the oldest common ancestor.
3. Merge the changes: keep all additive improvements from each version; for conflicting edits in the same section, prefer the semantically correct/complete version and note the decision.
4. Write the merged result back to ALL folders, overwriting each copy.

> **Merge principle**: SDD prompts are instructional markdown. Merges should preserve every step, example, and edge case from all versions. When instructions conflict, use judgment to keep the more complete and precise wording.

### Step 4 — Verify

Re-run the script to confirm all files show **IN-SYNC**.

## Quick Reference — Current File Set

| File | Purpose |
|------|---------|
| `change-init.prompt.md` | Initialize a new change doc set |
| `change-propose.prompt.md` | Draft a change proposal |
| `change-apply.prompt.md` | Apply an approved change to code |
| `change-review.prompt.md` | Review a proposed change |
| `change-refinement.prompt.md` | Refine / iterate on a change proposal |
| `change-update-master.prompt.md` | Sync approved changes back to master docs |

## Archive Behavior

Before overwriting any existing file the script archives the current version to:
```
<prompts-folder>/_archive/<yyyy-MM-dd_HHmmss>/<filename>
```
Each sync run gets its own timestamped subfolder, so you can always roll back by copying a file out of `_archive/`. Archives are never deleted automatically.

For AI-assisted merges, archive the pre-merge versions in each folder first (the script comment at the bottom of the apply block shows the pattern), then write the merged content.

## Notes

- Only `change-*.prompt.md` files are in scope (not agents, instructions, or skills).
- If a new `change-*` file appears in any folder it is considered authoritative and gets copied to all others.
- The script never deletes files — it only copies newer or missing versions.
- `_archive/` subfolders inside each prompts directory are ignored by the `change-*` glob filter.
