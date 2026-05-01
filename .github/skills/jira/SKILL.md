---
name: jira
description: Retrieves JIRA ticket content and child issues from on-premises JIRA instance. Use this when you need to fetch and cache JIRA tickets or list child issues under an initiative/epic.
---

Use the provided Python scripts to retrieve JIRA content from on-premises JIRA server:
- **fetch_jira.py**: Retrieve individual ticket details in markdown format
- **fetch_child_issues.py**: List all child issues under a parent initiative or epic

Authenticate using Personal Access Token (PAT).
Convert ticket data to readable markdown format with all relevant fields.

## Use Cases

**Use `fetch_jira.py` when you need to:**
- Get detailed information about a specific JIRA ticket
- Read description, comments, and attachments
- Cache ticket content for analysis
- Export ticket details to markdown

**Use `fetch_child_issues.py` when you need to:**
- List all epics under an initiative
- See all stories under an epic
- Analyze child issue structure
- Track sub-tasks and dependencies
- Export initiative hierarchy

## Process

1. **Parse URL**: Extract issue key from JIRA URL
2. **Authenticate**: Use credentials from environment variables or config
3. **Fetch**: Retrieve issue data via JIRA REST API
4. **Convert**: Transform to markdown with structured information
5. **Cache**: Save to workspace/_cache/ with metadata

## Required Environment Variables

- `JIRA_BASE_URL`: Your on-premises JIRA server URL (e.g., https://jira.company.com)
- `JIRA_API_TOKEN`: Your JIRA API token or password

## Script Usage

### Fetch Individual Ticket

```powershell
python .github\skills\jira\scripts\fetch_jira.py <JIRA_TICKET_URL>
```

**Examples:**
```powershell
python .github\skills\jira\scripts\fetch_jira.py https://jira.amadeus.com/agile/browse/AOP-26060
python .github\skills\jira\scripts\fetch_jira.py PSST-13666
```

### Fetch Child Issues

Retrieve all child issues (epics, stories, tasks) under a parent initiative or epic:

```powershell
python .github\skills\jira\scripts\fetch_child_issues.py <PARENT_ISSUE_KEY> [--json] [--cache]
```

**Options:**
- `--json`: Output results in JSON format (default is human-readable text)
- `--cache`: Save results to `workspace/_cache/jira-{key}-children.json`

**Examples:**
```powershell
# List all child epics under initiative
python .github\skills\jira\scripts\fetch_child_issues.py AOP-26060

# Get JSON output
python .github\skills\jira\scripts\fetch_child_issues.py AOP-26060 --json

# Save to cache
python .github\skills\jira\scripts\fetch_child_issues.py AOP-26060 --cache

# Combine options
python .github\skills\jira\scripts\fetch_child_issues.py AOP-26060 --json --cache
```

## Output Formats

### Individual Ticket Output

The `fetch_jira.py` script outputs markdown with:
- Issue key and summary
- Status, priority, type
- Description (converted from JIRA format)
- Comments
- Custom fields
- Attachments list
- Links to related issues
- Source URL and retrieval date

### Child Issues Output

The `fetch_child_issues.py` script outputs:

**Text format (default):**
```
Found 9 child issues:

- PSST-15686: [Epic] Enhance Data Validation
  Status: Backlog | Assignee: John Doe
- PSST-15685: [Epic] Optimize Event Hub Architecture
  Status: Backlog | Assignee: Unassigned
...
```

**JSON format (--json flag):**
```json
{
  "total": 9,
  "issues": [
    {
      "key": "PSST-15686",
      "fields": {
        "summary": "Enhance Data Validation",
        "status": { "name": "Backlog" },
        "issuetype": { "name": "Epic" },
        ...
      }
    }
  ]
}
```
