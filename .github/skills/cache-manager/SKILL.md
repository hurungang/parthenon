---
name: cache-manager
description: Manages markdown cache files in workspace/_cache directory. Use this when you need to create, read, or update cached markdown files.
---

Manage cached markdown files:
- Check if cache file exists for a given reference
- Create new cache files in workspace/_cache/
- Update existing cache files when source content changes
- Name cache files consistently: {sanitized-source-name}.md
- Include metadata header with source URL, cache date, original format

## Metadata Format

Each cached file should start with a metadata header:

```markdown
# [Document Title]

**Source:** [URL or path]
**Cached:** [Date]
**Format:** [Original format: OneNote, Confluence, PDF, etc.]

---

[Content starts here...]
```
