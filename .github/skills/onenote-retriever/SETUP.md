# Quick Setup Guide for OneNote Retriever

This guide will help you quickly set up and test the OneNote Retriever skill.

## Prerequisites

- Python 3.8 or higher
- Azure AD account (personal or organizational)
- Admin access to Azure Portal (for app registration)

## Step 1: Install Dependencies

```powershell
# Navigate to the repository root
cd c:\Users\rhu\source\repos\pss-llm-notebook

# Install required packages
pip install -r .github\skills\onenote-retriever\requirements.txt
```

## Step 2: Register Azure AD Application

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **Azure Active Directory** > **App registrations**
3. Click **New registration**
4. Fill in:
   - **Name**: OneNote Content Retriever
   - **Supported account types**: Choose based on your needs
   - **Redirect URI**: Leave blank (not needed for client credentials)
5. Click **Register**
6. **Copy the following values** (you'll need them later):
   - Application (client) ID
   - Directory (tenant) ID

## Step 3: Create Client Secret

1. In your app registration, go to **Certificates & secrets**
2. Click **New client secret**
3. Add description: "OneNote Retriever Secret"
4. Set expiration: Choose based on your security policy
5. Click **Add**
6. **IMPORTANT**: Copy the secret **VALUE** immediately (not the ID)
   - This is shown only once!

## Step 4: Configure API Permissions

1. In your app registration, go to **API permissions**
2. Click **Add a permission**
3. Select **Microsoft Graph**
4. Select **Application permissions** (not Delegated)
5. Search for and add: **Notes.Read.All**
6. Click **Add permissions**
7. Click **Grant admin consent for [Your Organization]**
   - This requires admin privileges
   - Button should show a green checkmark when granted

## Step 5: Set Environment Variables

```powershell
# PowerShell - Set for current session
$env:ONENOTE_CLIENT_ID = "YOUR-CLIENT-ID-HERE"
$env:ONENOTE_CLIENT_SECRET = "YOUR-CLIENT-SECRET-HERE"
$env:ONENOTE_TENANT_ID = "YOUR-TENANT-ID-HERE"

# To set permanently (current user)
[System.Environment]::SetEnvironmentVariable('ONENOTE_CLIENT_ID', 'YOUR-CLIENT-ID-HERE', 'User')
[System.Environment]::SetEnvironmentVariable('ONENOTE_CLIENT_SECRET', 'YOUR-CLIENT-SECRET-HERE', 'User')
[System.Environment]::SetEnvironmentVariable('ONENOTE_TENANT_ID', 'YOUR-TENANT-ID-HERE', 'User')
```

Or create a `.env` file in the repository root (don't commit this):

```
ONENOTE_CLIENT_ID=your-client-id-here
ONENOTE_CLIENT_SECRET=your-client-secret-here
ONENOTE_TENANT_ID=your-tenant-id-here
```

## Step 6: Test the Setup

### Browse Your OneNote Pages

```powershell
# List recent pages
python .github\skills\onenote-retriever\scripts\browse_onenote.py pages

# List all notebooks
python .github\skills\onenote-retriever\scripts\browse_onenote.py notebooks

# Browse full hierarchy
python .github\skills\onenote-retriever\scripts\browse_onenote.py browse
```

### Fetch a Specific Page

```powershell
# Use a page ID from the browse output
python .github\skills\onenote-retriever\scripts\fetch_onenote.py "1-abc123def456"

# Or use a full URL
python .github\skills\onenote-retriever\scripts\fetch_onenote.py "https://www.onenote.com/..."
```

## Step 7: Verify Output

Check the cached file:

```powershell
# List cached files
dir workspace\_cache\onenote-*.md

# View a cached file
Get-Content workspace\_cache\onenote-[page-id].md
```

## Troubleshooting

### Authentication Errors

**"Invalid client secret"**
- Client secret may have expired
- Double-check you copied the VALUE, not the ID
- Generate a new secret in Azure Portal

**"Insufficient privileges"**
- API permissions not granted or admin consent not given
- Go back to Step 4 and ensure green checkmark is shown
- Wait a few minutes for permissions to propagate

### Access Errors

**"Page not found" (404)**
- Page ID may be incorrect
- Application may not have access to the user's notebooks
- For organizational accounts, ensure the app has access across the organization

**"Forbidden" (403)**
- API permissions may not be sufficient
- Ensure `Notes.Read.All` is granted
- Check if Notes API is enabled in your organization

### Content Issues

**"Content could not be retrieved"**
- Page exists but HTML content fetch failed
- This is not critical - metadata will still be cached
- Check network connectivity to Microsoft Graph API

## Next Steps

1. **Integrate with Datacollector Agent**: The datacollector agent should now be able to use this skill
2. **Add OneNote References**: Add OneNote links to `workspace/references-list.md`
3. **Cache Content**: Use `@datacollector` to cache OneNote pages
4. **Analyze Content**: Use `@document-analyst` to analyze cached pages

## Security Notes

- **Never commit** your client secret to version control
- Add `.env` to `.gitignore`
- Rotate secrets regularly
- Use Azure Key Vault for production deployments
- Review Azure AD sign-in logs periodically

## References

- [Microsoft Graph API - OneNote](https://learn.microsoft.com/en-us/graph/api/resources/onenote-api-overview)
- [Register an application](https://learn.microsoft.com/en-us/graph/auth-register-app-v2)
- [Application permissions](https://learn.microsoft.com/en-us/graph/permissions-reference#notes-permissions)
