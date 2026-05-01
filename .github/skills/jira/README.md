# JIRA Skill

Retrieves JIRA ticket content from on-premises JIRA server and converts it to markdown format.

## Features

- Fetches JIRA issues via REST API
- Supports on-premises JIRA instances
- Converts JIRA markup to markdown
- Includes comments, attachments, linked issues
- Supports Basic Auth and API token authentication

## Setup

### 1. Install Dependencies

```powershell
pip install requests
```

### 2. Configure Environment Variables

Set up your JIRA credentials as environment variables:

```powershell
# PowerShell
$env:JIRA_BASE_URL = "https://jira.company.com"
$env:JIRA_API_TOKEN = "your-api-token-or-password"
```

Or create a `.env` file (not committed to git):

```
JIRA_BASE_URL=https://jira.company.com
JIRA_API_TOKEN=your-api-token-or-password
```

### 3. Get API Token

For JIRA Server/Data Center:
- Use your regular password, OR
- Generate a Personal Access Token from your JIRA profile settings

## Usage

### Command Line

```powershell
python .github\skills\jira\scripts\fetch_jira.py "https://jira.company.com/browse/PROJ-123"
```

### From Agent

The skill is automatically available when invoked by the `@datacollector` agent:

```
@datacollector cache JIRA ticket https://jira.company.com/browse/PROJ-123
```

## Output

The script outputs markdown with:

- Issue key and summary
- Status, priority, type, labels
- Reporter and assignee
- Description (converted from JIRA markup)
- All comments
- Attachments list
- Linked issues
- Subtasks
- Metadata (created date, updated date)

## Supported URL Formats

- `https://jira.company.com/browse/PROJ-123`
- `https://jira.company.com/jira/browse/PROJ-123`
- `https://jira.company.com/secure/IssueNavigator.jspa?selectedIssue=PROJ-123`

## Troubleshooting

### SSL Certificate Errors

If you encounter SSL certificate errors with self-signed certificates, modify the script:

```python
response = requests.get(api_url, auth=auth, params=params, verify=False, timeout=30)
```

**Note:** Only disable SSL verification for trusted internal networks.

### Authentication Errors

- Verify your credentials are correct
- Check if your JIRA instance requires specific API permissions
- Ensure your account has permission to view the ticket

### Connection Errors

- Verify the JIRA base URL is correct
- Check if you're on the corporate network (VPN if remote)
- Ensure firewall allows outbound connections to JIRA server

## Customization

You can extend the script to include custom fields specific to your JIRA instance:

```python
# In format_issue_as_markdown function
custom_field = fields.get('customfield_10001', 'Not set')
md.append(f"- **Custom Field:** {custom_field}")
```

## Security Notes

- Never commit credentials to git
- Use environment variables or secure credential stores
- Consider using API tokens instead of passwords
- Rotate tokens regularly
