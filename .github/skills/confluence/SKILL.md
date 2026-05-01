---
name: confluence
description: Retrieves Confluence page content from Confluence Cloud. Use this when you need to fetch and cache Confluence documentation.
---

Use the provided Python script to retrieve Confluence page content from Confluence Cloud.
Authenticate using API token (Cloud) or Personal Access Token.
Convert Confluence storage format to readable markdown.

## Process

1. **Parse URL**: Extract page ID or space/title from Confluence URL
2. **Authenticate**: Use credentials from environment variables or config
3. **Fetch**: Retrieve page data via Confluence REST API
4. **Convert**: Transform storage format HTML to markdown
5. **Cache**: Save to workspace/_cache/ with metadata

## Required Environment Variables

- `CONFLUENCE_BASE_URL`: Your Confluence Cloud URL (e.g., https://yourcompany.atlassian.net/wiki)
- `CONFLUENCE_USERNAME`: Your Atlassian account email
- `CONFLUENCE_API_TOKEN`: Your Confluence API token (generate from Atlassian account settings)

## Script Usage

```powershell
python .github\skills\confluence\scripts\fetch_confluence.py <CONFLUENCE_PAGE_URL>
```

## Output Format

The script outputs markdown with:
- Page title
- Space name
- Content (converted from Confluence storage format)
- Labels/tags
- Attachments list
- Child pages
- Last modified date and author
- Source URL and retrieval date

## Authentication Setup

For Confluence Cloud:
1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Create API token
3. Set environment variables with your email and token
