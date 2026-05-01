# OneNote Retriever - Quick Reference

## Installation

```powershell
pip install -r .github\skills\onenote-retriever\requirements.txt
```

## Environment Setup

```powershell
$env:ONENOTE_CLIENT_ID = "your-client-id"
$env:ONENOTE_CLIENT_SECRET = "your-secret"
$env:ONENOTE_TENANT_ID = "your-tenant-id"
```

## Quick Commands

### Browse OneNote Content

```powershell
# List recent 20 pages
python .github\skills\onenote-retriever\scripts\browse_onenote.py

# List recent 50 pages
python .github\skills\onenote-retriever\scripts\browse_onenote.py pages 50

# List all notebooks
python .github\skills\onenote-retriever\scripts\browse_onenote.py notebooks

# Browse full hierarchy
python .github\skills\onenote-retriever\scripts\browse_onenote.py browse
```

### Fetch OneNote Page

```powershell
# By page ID
python .github\skills\onenote-retriever\scripts\fetch_onenote.py "1-abc123def456"

# By Graph API URL
python .github\skills\onenote-retriever\scripts\fetch_onenote.py "https://graph.microsoft.com/v1.0/me/onenote/pages/1-abc123"

# By web URL
python .github\skills\onenote-retriever\scripts\fetch_onenote.py "https://www.onenote.com/..."
```

### Check Cache

```powershell
# List cached OneNote files
dir workspace\_cache\onenote-*.md

# View cached content
Get-Content workspace\_cache\onenote-{page-id}.md
```

## Azure AD Setup Checklist

- [ ] Register app in Azure Portal
- [ ] Copy Client ID, Tenant ID
- [ ] Create client secret (copy immediately!)
- [ ] Add API permission: Notes.Read.All (Application)
- [ ] Grant admin consent
- [ ] Set environment variables
- [ ] Test with browse script

## Common Issues

| Error | Solution |
|-------|----------|
| "Invalid client secret" | Regenerate secret, copy VALUE not ID |
| "Insufficient privileges" | Grant admin consent for API permissions |
| "Page not found" | Check page ID, verify app has access |
| "Authentication failed" | Verify all 3 env vars are set correctly |

## File Structure

```
.github/skills/onenote-retriever/
├── SKILL.md              # Copilot skill definition
├── README.md             # Full documentation
├── SETUP.md              # Setup guide
├── EXAMPLES.md           # Usage examples
├── IMPLEMENTATION.md     # Technical summary
├── QUICKREF.md          # This file
├── requirements.txt      # Dependencies
└── scripts/
    ├── fetch_onenote.py # Main fetcher
    └── browse_onenote.py # Browser tool
```

## Supported URL Formats

- `https://graph.microsoft.com/v1.0/me/onenote/pages/{id}`
- `https://www.onenote.com/...`
- `https://onedrive.live.com/view.aspx?...`
- `onenote:https://...`
- Plain page ID: `1-abc123def456`

## Output Format

Markdown files saved to: `workspace/_cache/onenote-{page-id}.md`

Contents:
- Page title as H1
- Metadata section (notebook, section, dates, authors)
- Content (converted to markdown)
- Footer with retrieval info

## Integration with Agents

### Add to references.md

```markdown
### My OneNote Page
- **File Name**: onenote-{page-id}.md
- **Source Type**: onenote
- **Link**: https://www.onenote.com/...
- **Added Date**: 2026-01-20
- **Last Updated**: 2026-01-20
- **Cache Date**: Not cached yet
- **Status**: pending
- **Summary**: Important meeting notes
- **Tags**: meetings, project-planning
```

### Use Datacollector

```
@datacollector please cache all OneNote references
```

The datacollector agent will:
1. Find OneNote source type in references.md
2. Use onenote-retriever skill
3. Fetch and cache content
4. Update cache date in references.md

## Tips

- Use browse script first to find page IDs
- Check Azure AD sign-in logs if auth fails
- Page IDs are in format: `1-abc123def456789`
- Graph API URLs are most reliable format
- Cache files include full metadata
- Images preserved as markdown links

## Documentation

- **Full Setup**: [SETUP.md](SETUP.md)
- **Usage Examples**: [EXAMPLES.md](EXAMPLES.md)
- **Implementation Details**: [IMPLEMENTATION.md](IMPLEMENTATION.md)
- **Main Docs**: [README.md](README.md)

## API Limits

Microsoft Graph throttling:
- Be respectful of API limits
- Script includes error handling for 429 responses
- For bulk operations, add delays between requests

## Security

- Never commit `.env` files
- Rotate secrets regularly
- Use least privilege (Notes.Read.All is read-only)
- Monitor Azure AD sign-in logs
- Consider Azure Key Vault for production
