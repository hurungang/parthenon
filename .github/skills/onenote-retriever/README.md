# OneNote Retriever Skill

Retrieves Microsoft OneNote page content and converts it to markdown format.

## Features

- Fetches OneNote pages via Microsoft Graph API
- Supports both personal and organizational accounts
- Converts OneNote HTML to markdown
- Handles images, tables, and formatted content
- OAuth2 authentication with client credentials or device code flow
- Works with cloud-based OneNote notebooks
- **Alternative**: Local OneNote access via COM (Windows, no Azure AD required)

## Two Access Methods

### Method 1: Microsoft Graph API (Cloud)
- **Requires**: Azure AD app registration (admin permissions needed)
- **Best for**: Automation, cloud notebooks, organizational use
- **See**: Standard setup below

### Method 2: Local COM Automation (Windows)
- **Requires**: Windows + OneNote desktop app + pywin32
- **Best for**: Personal use, no admin access, local notebooks
- **See**: [ALTERNATIVES.md](ALTERNATIVES.md) for setup

**Don't have Azure AD admin access?** See [ALTERNATIVES.md](ALTERNATIVES.md) for other options including manual export, IT request templates, and the COM-based local access method.

## Setup

### 1. Install Dependencies

```powershell
pip install -r .github\skills\onenote-retriever\requirements.txt
```

### 2. Register Azure AD Application

To access OneNote via Microsoft Graph API, you need to register an application in Azure AD:

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **Azure Active Directory** > **App registrations**
3. Click **New registration**
4. Enter name: "OneNote Content Retriever"
5. Select account type (single or multi-tenant)
6. Click **Register**

### 3. Configure API Permissions

1. In your app registration, go to **API permissions**
2. Click **Add a permission** > **Microsoft Graph** > **Application permissions**
3. Add permission: **Notes.Read.All**
4. Click **Grant admin consent** (requires admin privileges)

### 4. Create Client Secret

1. Go to **Certificates & secrets**
2. Click **New client secret**
3. Add description and set expiration
4. **Copy the secret value immediately** (it won't be shown again)

### 5. Configure Environment Variables

Set up your credentials as environment variables:

```powershell
# PowerShell
$env:ONENOTE_CLIENT_ID = "your-application-client-id"
$env:ONENOTE_CLIENT_SECRET = "your-client-secret-value"
$env:ONENOTE_TENANT_ID = "your-tenant-id"
```

Or create a `.env` file (not committed to git):

```
ONENOTE_CLIENT_ID=your-application-client-id
ONENOTE_CLIENT_SECRET=your-client-secret-value
ONENOTE_TENANT_ID=your-tenant-id
```

### Finding Your Tenant ID

- In Azure Portal, go to **Azure Active Directory** > **Overview**
- Copy the **Tenant ID** value

## Usage

### Command Line

```powershell
# Fetch a OneNote page
python .github\skills\onenote-retriever\scripts\fetch_onenote.py "https://onedrive.live.com/view.aspx?..."

# Or with a direct page link
python .github\skills\onenote-retriever\scripts\fetch_onenote.py "onenote:https://..."
```

### From Python

```python
from scripts.fetch_onenote import fetch_onenote_page, get_graph_token

# Get access token
token = get_graph_token()

# Fetch page content
markdown_content = fetch_onenote_page(page_url, token)
print(markdown_content)
```

## Output

The script generates markdown files in the workspace cache:

```
workspace/_cache/
  onenote-<page-id>.md
```

Each file contains:
- Page title
- Notebook and section information
- Page content (converted to markdown)
- Metadata (creation date, last modified, author)
- Source URL

## URL Formats

The script supports various OneNote URL formats:

### Web Links
```
https://onedrive.live.com/view.aspx?resid=ABC123&id=XYZ789
https://www.onenote.com/...
```

### OneNote Protocol Links
```
onenote:https://d.docs.live.net/abc123/Documents/Notebook/Section.one#Page&section-id={...}&page-id={...}
```

### Direct Graph API URLs
```
https://graph.microsoft.com/v1.0/me/onenote/pages/{page-id}
```

## Troubleshooting

### Authentication Errors

**Error: "Insufficient privileges to complete the operation"**
- Ensure API permissions are granted and admin consent is given
- Verify Notes.Read.All permission is added

**Error: "AADSTS7000215: Invalid client secret"**
- Client secret may have expired
- Generate a new secret in Azure Portal

### Content Issues

**Images not displaying**
- Images are converted to markdown image links
- Original URLs from Microsoft Graph are preserved
- May require authentication to view in some cases

**Formatting lost**
- Complex OneNote formatting may not translate perfectly to markdown
- Tables and lists are preserved with basic formatting
- Code blocks use fenced code blocks

### API Limits

Microsoft Graph API has rate limits:
- Personal accounts: Lower limits
- Organizational accounts: Higher limits based on license
- Implement retry logic for 429 (Too Many Requests) responses

## Permissions

The `Notes.Read.All` application permission allows:
- Read all OneNote notebooks in the organization
- Access pages, sections, and notebooks
- Read-only access (cannot modify content)

For user-specific access (delegated permissions), use:
- `Notes.Read` - Read user's OneNote notebooks
- `Notes.Read.All` - Read all notebooks user has access to

## Security Best Practices

1. **Protect Client Secrets**: Never commit secrets to version control
2. **Use Key Vault**: Store secrets in Azure Key Vault for production
3. **Limit Permissions**: Request only the permissions you need
4. **Rotate Secrets**: Regularly rotate client secrets
5. **Monitor Access**: Review Azure AD sign-in logs for unusual activity

## Alternative: Device Code Flow

For interactive use without storing secrets:

```powershell
# Set only client ID (no secret)
$env:ONENOTE_CLIENT_ID = "your-client-id"
$env:ONENOTE_TENANT_ID = "your-tenant-id"

# Run script - will prompt for device code authentication
python .github\skills\onenote-retriever\scripts\fetch_onenote.py <URL>
```

The script will display a code and URL to authenticate interactively.

## References

- [Microsoft Graph API - OneNote](https://learn.microsoft.com/en-us/graph/api/resources/onenote-api-overview)
- [Register an application with Microsoft identity platform](https://learn.microsoft.com/en-us/graph/auth-register-app-v2)
- [Get access on behalf of a user](https://learn.microsoft.com/en-us/graph/auth-v2-user)
- [Get access without a user](https://learn.microsoft.com/en-us/graph/auth-v2-service)
