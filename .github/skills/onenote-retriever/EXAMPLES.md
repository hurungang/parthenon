# OneNote Retriever Examples

## Example URLs

### Microsoft Graph API URL (Direct)
```
https://graph.microsoft.com/v1.0/me/onenote/pages/1-abc123def456
```

### OneNote Web URL
```
https://www.onenote.com/notebooks/abc123def456?page-id={1-abc123def456}&section-id={1-xyz789}
```

### OneDrive Link to OneNote Page
```
https://onedrive.live.com/view.aspx?resid=ABC123&id=documents&wd=target%28Notebook.one%7C1-abc123def456%7CPage%20Title%29
```

## Setup Example

```powershell
# Set environment variables
$env:ONENOTE_CLIENT_ID = "12345678-1234-1234-1234-123456789abc"
$env:ONENOTE_CLIENT_SECRET = "your-client-secret-here"
$env:ONENOTE_TENANT_ID = "87654321-4321-4321-4321-cba987654321"

# Install dependencies
pip install -r .github\skills\onenote-retriever\requirements.txt

# Fetch a page
python .github\skills\onenote-retriever\scripts\fetch_onenote.py "YOUR_ONENOTE_URL"
```

## Testing the Skill

### 1. List All Notebooks (for testing)

```python
import requests
import msal

# Get token
client_id = "your-client-id"
client_secret = "your-client-secret"
tenant_id = "your-tenant-id"

authority = f"https://login.microsoftonline.com/{tenant_id}"
app = msal.ConfidentialClientApplication(
    client_id,
    authority=authority,
    client_credential=client_secret
)

result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
token = result["access_token"]

# List notebooks
headers = {'Authorization': f'Bearer {token}'}
response = requests.get('https://graph.microsoft.com/v1.0/me/onenote/notebooks', headers=headers)
notebooks = response.json()

for notebook in notebooks.get('value', []):
    print(f"Notebook: {notebook['displayName']} - ID: {notebook['id']}")
```

### 2. List Pages in a Notebook

```python
notebook_id = "your-notebook-id"
response = requests.get(
    f'https://graph.microsoft.com/v1.0/me/onenote/notebooks/{notebook_id}/pages',
    headers=headers
)
pages = response.json()

for page in pages.get('value', []):
    print(f"Page: {page['title']} - ID: {page['id']}")
    print(f"  URL: {page['links']['oneNoteWebUrl']['href']}")
```

## Expected Output

When you run the fetch script, it will:

1. Authenticate with Microsoft Graph API
2. Fetch the page metadata and content
3. Convert HTML to markdown
4. Save to `workspace/_cache/onenote-{page-id}.md`
5. Print the markdown content to stdout

### Sample Output File

```markdown
# My Meeting Notes

## Metadata

**Section**: Project Planning
**Notebook**: Work Notes
**Created**: 2026-01-15 10:30:00 UTC
**Last Modified**: 2026-01-20 14:22:00 UTC
**Created By**: John Doe
**Last Modified By**: Jane Smith
**Web URL**: https://www.onenote.com/...
**Source URL**: https://graph.microsoft.com/v1.0/me/onenote/pages/1-abc123
**Retrieved**: 2026-01-20 15:00:00

## Content

## Discussion Points

- Budget review for Q1
- Team allocation
- Timeline adjustments

## Action Items

1. [ ] Update project timeline
2. [ ] Schedule follow-up meeting
3. [ ] Review resource allocation

---
*Retrieved from OneNote via Microsoft Graph API on 2026-01-20*
```

## Troubleshooting

### Common Issues

**Authentication Failed**
- Check that all environment variables are set correctly
- Verify client secret hasn't expired
- Ensure API permissions are granted in Azure Portal

**Page Not Found (404)**
- Page ID may be incorrect
- User/app may not have access to the page
- Try using the direct Graph API URL format

**Permission Denied**
- Ensure `Notes.Read.All` permission is granted
- Grant admin consent in Azure Portal
- Check if the account has access to the notebook

### Getting Help

For Microsoft Graph API documentation:
- [OneNote API Overview](https://learn.microsoft.com/en-us/graph/api/resources/onenote-api-overview)
- [Get OneNote Page](https://learn.microsoft.com/en-us/graph/api/page-get)
- [Authentication](https://learn.microsoft.com/en-us/graph/auth/)
