# Confluence Skill

Retrieves Confluence page content from Confluence Cloud and converts it to markdown format.

## Features

- Fetches Confluence pages via REST API
- Supports Confluence Cloud (Atlassian)
- Converts storage format HTML to markdown
- Includes labels, child pages, attachments
- Supports API token authentication

## Setup

### 1. Install Dependencies

```powershell
pip install requests
```

### 2. Create API Token

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Give it a name (e.g., "Notebook Data Collector")
4. Copy the generated token

### 3. Configure Environment Variables

Set up your Confluence credentials as environment variables:

```powershell
# PowerShell
$env:CONFLUENCE_BASE_URL = "https://yourcompany.atlassian.net/wiki"
$env:CONFLUENCE_USERNAME = "your.email@company.com"
$env:CONFLUENCE_API_TOKEN = "your-api-token"
```

Or create a `.env` file (not committed to git):

```
CONFLUENCE_BASE_URL=https://yourcompany.atlassian.net/wiki
CONFLUENCE_USERNAME=your.email@company.com
CONFLUENCE_API_TOKEN=your-api-token
```

**Important:** For Confluence Cloud, the username must be your Atlassian account email.

## Usage

### Command Line

```powershell
python .github\skills\confluence\scripts\fetch_confluence.py "https://yourcompany.atlassian.net/wiki/spaces/SPACE/pages/123456/Page+Title"
```

### From Agent

The skill is automatically available when invoked by the `@datacollector` agent:

```
@datacollector cache Confluence page https://yourcompany.atlassian.net/wiki/spaces/SPACE/pages/123456/Page+Title
```

## Output

The script outputs markdown with:

- Page title
- Space name
- Content (converted from storage format)
- Labels/tags
- Breadcrumb navigation
- Child pages list
- Attachments list
- Last modified date and author
- Metadata

## Supported URL Formats

- `https://company.atlassian.net/wiki/spaces/SPACE/pages/123456/Page+Title`
- `https://company.atlassian.net/wiki/pages/viewpage.action?pageId=123456`
- `https://company.atlassian.net/wiki/display/SPACE/Page+Title` (with redirect)

## HTML to Markdown Conversion

The skill includes a converter that handles:

- Headers (h1-h6)
- Bold, italic formatting
- Code blocks and inline code
- Lists (ordered and unordered)
- Links
- Images
- Blockquotes
- Tables (basic support)

Some complex Confluence macros may not convert perfectly - the raw content is preserved where possible.

## Troubleshooting

### Authentication Errors

- Verify you're using your Atlassian account **email** as username
- Check that your API token is valid and not expired
- Ensure you have permission to view the page

### Page Not Found

- Verify the page ID is correct
- Check if the page has been moved or deleted
- Ensure you have access to the space

### Base URL Issues

For Confluence Cloud, use format:
- `https://yourcompany.atlassian.net/wiki` ✅
- NOT `https://confluence.company.com` (Server/Data Center)

## Confluence Server/Data Center

If you're using Confluence Server or Data Center (on-premises), you may need to modify the API endpoints:

```python
# For Confluence Server/Data Center
api_url = f"{base_url}/rest/api/content/{page_id}"
```

The authentication will be similar but may support additional methods like PAT (Personal Access Tokens).

## Extending the Converter

To improve HTML-to-Markdown conversion for specific Confluence macros:

```python
# Add custom macro handling in convert_storage_to_markdown function
if 'ac:structured-macro' in storage_html:
    # Handle Confluence macros
    pass
```

## Security Notes

- Never commit API tokens to git
- Use environment variables or secure credential stores
- Tokens have the same permissions as your account
- Rotate tokens regularly
- Revoke unused tokens at https://id.atlassian.com/manage-profile/security/api-tokens

## Limitations

- Confluence Cloud only (Server/Data Center requires modifications)
- Complex macros may not convert perfectly
- Tables with merged cells may have formatting issues
- Embedded media may need special handling
