---
name: onenote-retriever
description: Retrieves Microsoft OneNote page content. Use this when you need to fetch and cache OneNote pages from local or cloud notebooks.
---

Use the provided Python script to retrieve OneNote page content via Microsoft Graph API.
Authenticate using OAuth2 with client credentials or device code flow.
Convert OneNote HTML content to readable markdown format.

## Process

1. **Parse URL**: Extract notebook ID and page ID from OneNote URL or web link
2. **Authenticate**: Use Microsoft Graph API with OAuth2 authentication
3. **Fetch**: Retrieve page content via Microsoft Graph API
4. **Convert**: Transform OneNote HTML to markdown
5. **Cache**: Save to workspace/_cache/ with metadata

## Required Environment Variables

### Option 1: Client Credentials (Recommended for automation)
- `ONENOTE_CLIENT_ID`: Your Azure AD application client ID
- `ONENOTE_CLIENT_SECRET`: Your Azure AD application client secret
- `ONENOTE_TENANT_ID`: Your Azure AD tenant ID

### Option 2: Device Code Flow (Interactive)
- `ONENOTE_CLIENT_ID`: Your Azure AD application client ID
- `ONENOTE_TENANT_ID`: Your Azure AD tenant ID

## Script Usage

```powershell
python .github\skills\onenote-retriever\scripts\fetch_onenote.py <ONENOTE_PAGE_URL>
```

## Output Format

The script outputs markdown with:
- Page title
- Notebook and section names
- Content (converted from OneNote HTML)
- Creation date and last modified date
- Last modified by
- Source URL and retrieval date
- Tags (if present)

## Authentication Setup

### Register Azure AD Application

1. Go to https://portal.azure.com
2. Navigate to Azure Active Directory > App registrations
3. Click "New registration"
4. Set name: "OneNote Content Retriever"
5. Set redirect URI (optional for client credentials): `http://localhost`
6. Click Register

### Configure API Permissions

1. In your app, go to API permissions
2. Add permission > Microsoft Graph > Application permissions
3. Add these permissions:
   - `Notes.Read.All` - Read all OneNote notebooks
4. Grant admin consent for your organization

### Create Client Secret

1. Go to Certificates & secrets
2. Click "New client secret"
3. Add description and expiration
4. Copy the secret value immediately (won't be shown again)

### Set Environment Variables

```powershell
# PowerShell
$env:ONENOTE_CLIENT_ID = "your-client-id"
$env:ONENOTE_CLIENT_SECRET = "your-client-secret"
$env:ONENOTE_TENANT_ID = "your-tenant-id"
```

## URL Format Examples

OneNote URLs can be in various formats:
- Web link: `https://onedrive.live.com/view.aspx?resid=...&id=...`
- OneNote web: `https://www.onenote.com/...`
- Desktop link: `onenote:https://...`

The script will extract the necessary IDs from any of these formats.
