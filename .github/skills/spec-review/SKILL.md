---
name: spec-review
description: Reviews master product docs for accuracy, structure, and freshness. Checks code references against source files, detects code snippets (which are forbidden), finds redundancy, and verifies docs are at the right detail level. Load this when running a spec review or doc audit.
license: MIT
metadata:
  author: openspec
  version: "2.0"
---

# Spec Review Skill

This skill defines how to review master product docs (`docs/master/`) for quality, accuracy, and freshness. A spec review catches stale docs, wrong code references, forbidden code snippets, structural problems, and redundancy.

This skill is project-agnostic. Always read `docs/config.yaml` first to get project-specific source paths (test directories, schema files, frontend/backend roots) before running any checks.

---

## What to Review

### 0. config.yaml Health Check

Always check `docs/config.yaml` first, regardless of review scope.

**Required fields — flag as Critical if missing or still templated**:
- `project.name` — must not contain `<`, `>`, or `TODO:`
- `project.description` — must be a real one-line description
- `source.frontend` — must exist as a path in the workspace (or `null` if not applicable)
- `source.backend` — must exist as a path in the workspace (or `null` if not applicable)
- `source.tests` — must be a list; each path must exist
- `tech_stack.*` — all fields must be populated, no placeholders

**Staleness checks**:
- For each path in `source.*`: verify the path still exists in the workspace
- Scan for common source directories that aren't listed (e.g. a new `e2e/` folder)
- Check `package.json` / `pyproject.toml` for major tech changes not reflected in `tech_stack`

**Completeness checks**:
- `conventions` list: should have at least 2 entries; more is better
- `domain` list: should have at least 1 entry if the project has domain-specific business rules

**Flag as Warning if**:
- Any field contains `TODO:`
- `source.schema` is null/missing and schema files exist in the workspace
- `conventions` or `domain` lists are empty

**Flag as Critical if**:
- Any field still contains `<` / `>` angle-bracket placeholders
- Any source path listed does not exist in the workspace

---

### 1. Code Reference Accuracy

In `docs/master/technology/` (tech specs), every Code Reference Map entry must point to a real file.

**Check for each entry in Code Reference Map tables**:
- Does the file path exist in the workspace? (`file_search` or `grep_search`)
- Does the symbol (function/class/component) still exist in that file?
- If a file was moved, is the reference updated?

**Flag as stale** if:
- File path does not exist
- Symbol name not found in the referenced file
- File has been significantly restructured since doc was last updated

---

### 2. Forbidden Content Detection

**Code snippets are strictly forbidden in ALL docs under `docs/`.**

Search for:
- Fenced code blocks (` ```language `)
- Inline code that contains actual code logic (not just symbol names in backticks)
- Schema/query language statements embedded in markdown (SQL, GraphQL, ORM code, etc.)
- Configuration blocks that belong in config files
- Shell command sequences in documentation prose (exception: deployment/operations docs may use short commands if truly unavoidable)

**Acceptable uses of backticks in docs**:
- Symbol names: `` `authenticateUser` ``, `` `LoginForm` ``
- File paths: `` `backend/app/api/v1/auth.py` ``
- Short unavoidable commands in deployment/operations docs only

**Any fenced code block in product, UX, architecture, data-model, QA, or reference docs = violation.**

---

### 3. Structure Compliance

Check each master doc folder against its required structure:

#### `docs/master/product/`
**Each feature spec MUST have**:
- Epic Overview (one paragraph, no implementation details)
- Business Goals (bullet points)
- User Stories (As a / I want / so that format)
- Acceptance Criteria (user-observable outcomes)
- Out of Scope

**Violations**:
- Technical implementation details in product docs
- API specs or data models in product docs
- Verbose background sections > one paragraph

#### `docs/master/ux/`
**Must have**:
- `prototype/index.html` — self-contained, working in browser without server
- Prototype covers primary user flows

**Violations**:
- Multiple fragmented HTML files instead of unified prototype
- Broken prototype (missing inline styles/JS)
- Text-based wireframes instead of HTML prototype

#### `docs/master/architecture/`
**Each diagram MUST**:
- Use Mermaid syntax (`flowchart`, `C4Context`, `graph`, `sequenceDiagram`)
- Have no more than 15 nodes in a single diagram
- Show components and their relationships, not implementation details

**Violations**:
- Non-Mermaid diagrams (screenshots, ASCII art, image embeds)
- Diagrams with > 15 nodes
- Low-level implementation details (class names, method signatures)
- Any code or pseudo-code

#### `docs/master/data-model/`
**Must have**:
- `overview.md` with Mermaid `erDiagram` showing business entities and relationships
- Module-level entity lists (entity names only, no schema code)

**Violations**:
- Any schema code (SQL, ORM syntax, migration code, etc.)
- ERD with storage-level details (column types, constraints, indexes) — show entities and relations only
- Tech-specific vocabulary that doesn't apply to the domain model
- Missing entries for entities that exist in the project's schema files

#### `docs/master/technology/`
**Each tech spec MUST have**:
- Code Reference Map table with: Symbol | Type | Description | File
- All symbols in the document appear in the map
- File paths exist in the workspace

**Violations**:
- Code Reference Map entries pointing to non-existent files
- Symbols mentioned in text that are NOT in the Code Reference Map
- Code snippets or implementation pseudo-code
- Duplicate coverage across module specs

#### `docs/master/qa/`
**Each test plan MUST have**:
- Test strategy (approach, not code)
- Coverage areas
- Critical scenarios (WHEN/THEN, no code)
- References to actual test files (paths from `docs/config.yaml` `source.tests`)

**Violations**:
- Test code or pseudo-code in test plans
- References to test files that don't exist
- Duplicate coverage between module test plans

#### `docs/master/deployment/` and `docs/master/operations/`
**Must be**:
- Ordered, actionable steps
- Reference actual config/script files rather than duplicating them

**Violations**:
- Duplicate instructions across files
- References to files/paths that don't exist
- Stale version numbers or configuration key names

---

### 4. Redundancy Detection

Look for:
- The same information documented in multiple files
- Overlapping coverage between module-level and system-level docs
- Change summaries or implementation notes that should have been removed after master update

**Flag** when the same function, endpoint, or concept is described in detail in more than one doc. One doc should be authoritative; others should reference it.

---

### 5. Detail Level Assessment

**Too detailed** (implementation details in wrong place):
- Exact SQL queries described in architecture docs
- Function signatures listed in product specs
- CSS class names in UX documentation

**Too vague** (not useful):
- Architecture docs that say "the system handles X" without showing component relationships
- Tech specs without a Code Reference Map
- Test plans without WHEN/THEN scenarios

---

## Review Process

### Step 1: Check config.yaml (always, regardless of scope)
Read `docs/config.yaml`:
1. Check for uninitialized placeholders (`<`, `>`, `TODO:`)
2. Verify each source path exists in the workspace
3. Check for new directories not yet listed
4. Check `package.json` / lockfile / `pyproject.toml` for major dependency changes

If `docs/config.yaml` is missing entirely, report as Critical and recommend running `/change:init` before continuing the review.

### Step 2: Read Project Config for Source Paths
Read `docs/config.yaml` (now already loaded) to get:
- Source paths (`source.frontend`, `source.backend`, `source.schema`, `source.tests`)
- These are needed to verify Code Reference Map entries and test file references

### Step 3: Scope Decision
Ask the user which area(s) to review, or default to all:
- `all` — Full review of all `docs/master/` folders
- `product` — `docs/master/product/` only
- `ux` — `docs/master/ux/` only
- `architecture` — `docs/master/architecture/` only
- `data-model` — `docs/master/data-model/` only
- `tech` — `docs/master/technology/` only (most common)
- `qa` — `docs/master/qa/` only
- `deployment` — `docs/master/deployment/` only
- `operations` — `docs/master/operations/` only

### Step 4: Gather Documents
For each area being reviewed:
1. List files in the target folder
2. Read docs to understand current state
3. For tech specs: run file_search to verify Code Reference Map entries
4. For architecture/database: verify Mermaid diagrams are valid syntax

### Step 5: Check Code References (if reviewing tech specs)
For each entry in a Code Reference Map:
```
grep_search for the symbol name in the referenced file
→ PASS: symbol found in file
→ FAIL: symbol not found — flag as stale reference
→ FAIL: file does not exist — flag as broken reference
```

Also check in reverse: scan source directories (from `docs/config.yaml` `source`) for key functions/components that should be in the map but aren't.

### Step 6: Generate Review Report

Output format:
```markdown
# Spec Review Report
**Date**: YYYY-MM-DD
**Scope**: <areas reviewed>

## config.yaml Status
- ✓ All paths verified / ✗ <N> issues found
- [ list path issues, placeholder fields, missing entries ]

## Summary
- ✓ Passing: <N> files
- ✗ Critical: <N> issues (must fix)
- ⚠ Warnings: <N> issues (should fix)

---

## Critical Issues (Must Fix)

### 1. config.yaml: Broken source path
**Field**: source.schema  
**Value**: `supabase/schemas/` — directory not found in workspace.  
**Action**: Update to correct path or remove if schema approach changed.

### 2. Broken code reference
**File**: docs/master/technology/modules/auth/tech-spec.md  
**Issue**: `authenticate_user` references `backend/app/api/v1/auth.py` but function not found.  
**Action**: Update reference or remove entry.

### 3. Forbidden code snippet
**File**: docs/master/architecture/system-overview.md  
**Issue**: Contains a code block.  
**Action**: Remove code block, reference the source file instead.

---

## Warnings (Should Fix)

### 4. config.yaml: TODO field
**Field**: tech_stack.auth  
**Value**: `TODO: specify auth library`  
**Action**: Run `/change:init` to complete this field.

### 5. Missing code reference
**File**: docs/master/technology/modules/auth/tech-spec.md  
**Issue**: `loginUser()` mentioned in text but not in Code Reference Map.  
**Action**: Add entry to Code Reference Map.

---

## Passing Areas
- config.yaml — source paths all verified ✓
- docs/master/product/ — All product specs are code-free and properly structured ✓
- docs/master/data-model/ — Data model current, uses Mermaid ER ✓
```

---

## Quick Reference: Common Violations

| Violation | Where Found | Fix |
|-----------|-------------|-----|
| Angle-bracket placeholder | `docs/config.yaml` | Run `/change:init` |
| TODO field | `docs/config.yaml` | Run `/change:init` |
| Broken source path | `docs/config.yaml` | Update path or run `/change:init` |
| Schema code block | `docs/master/data-model/` | Remove code, reference schema files from `docs/config.yaml` |
| Code snippet | `docs/master/architecture/` | Remove code, describe in plain language |
| Broken file reference | `docs/master/technology/` Code Reference Map | Update path or remove entry |
| Symbol not in map | `docs/master/technology/` tech spec | Add to Code Reference Map |
| > 15 nodes in diagram | `docs/master/architecture/` | Split into sub-diagram |
| Non-Mermaid diagram | Any `docs/master/` folder | Convert to Mermaid or remove |
| Prototype not self-contained | `docs/master/ux/` | Inline all CSS/JS |
| Test code in test plan | `docs/master/qa/` | Move code to test file, reference from plan |
| Missing Out of Scope section | `docs/master/product/` feature spec | Add section |
| API spec in product doc | `docs/master/product/` | Move to `docs/master/technology/` |
| Storage-level details in data-model | `docs/master/data-model/` | Remove — show entities/relations only |
