# Quick Start: Local OneNote Access (No Azure AD Required!)

This guide shows you how to access local OneNote notebooks without needing Azure AD permissions.

## Requirements

- ✅ Windows operating system
- ✅ OneNote desktop application installed
- ✅ Python 3.8 or higher
- ❌ NO Azure AD app registration needed
- ❌ NO admin permissions needed

## Setup (5 minutes)

### 1. Install Dependencies

```powershell
# Install required package
pip install pywin32

# Optional: Install for better markdown conversion
pip install beautifulsoup4 html2text
```

### 2. Verify OneNote is Installed

```powershell
# Check if OneNote is installed
Get-Command onenote.exe
```

If not installed, download from Microsoft Store or Office installation.

### 3. Test the Connection

```powershell
# List your notebooks
python .github\skills\onenote-retriever\scripts\fetch_onenote_local.py list-notebooks
```

You should see a list of your OneNote notebooks!

## Usage

### List Notebooks

```powershell
python .github\skills\onenote-retriever\scripts\fetch_onenote_local.py list-notebooks
```

Output:
```
Found 3 notebook(s):

📓 Work Notes
   Path: C:\Users\...\Documents\OneNote Notebooks\Work Notes
   ID: {ABC-123-...}

📓 Personal
   Path: C:\Users\...\Documents\OneNote Notebooks\Personal
   ID: {XYZ-789-...}
```

### List Pages

```powershell
# List recent 20 pages
python .github\skills\onenote-retriever\scripts\fetch_onenote_local.py list-pages

# List pages in specific notebook
python .github\skills\onenote-retriever\scripts\fetch_onenote_local.py list-pages "Work Notes"
```

### Fetch a Page

#### Option 1: By Page Title (searches all notebooks)

```powershell
python .github\skills\onenote-retriever\scripts\fetch_onenote_local.py fetch "Meeting Notes"
```

#### Option 2: By Notebook, Section, and Page (more precise)

```powershell
python .github\skills\onenote-retriever\scripts\fetch_onenote_local.py fetch-from "Work Notes" "Projects" "Project Plan"
```

### Check Cached Files

```powershell
# List cached files
dir workspace\_cache\onenote-local-*.md

# View content
Get-Content workspace\_cache\onenote-local-*.md
```

## Complete Example

```powershell
# 1. List your notebooks
python .github\skills\onenote-retriever\scripts\fetch_onenote_local.py list-notebooks

# 2. List pages to find what you want
python .github\skills\onenote-retriever\scripts\fetch_onenote_local.py list-pages

# 3. Fetch a specific page
python .github\skills\onenote-retriever\scripts\fetch_onenote_local.py fetch "Meeting Notes Jan 2026"

# 4. Check the output
Get-Content workspace\_cache\onenote-local-*.md | Select-Object -First 20
```

## Output Format

Cached files include:

```markdown
# Meeting Notes Jan 2026

## Metadata

**Notebook**: Work Notes
**Section**: Meetings
**Created**: 2026-01-15T10:30:00
**Last Modified**: 2026-01-20T14:22:00
**Page ID**: {ABC-123-...}
**Retrieved**: 2026-01-20 15:00:00
**Source**: Local OneNote via COM

## Content

[Your page content converted to markdown]

---
*Retrieved from local OneNote via COM automation on 2026-01-20*
```

## Integration with Workspace

### Add to references-metainfo.md

```markdown
### Meeting Notes Jan 2026
- **File Name**: onenote-local-ABC-123.md
- **Source Type**: onenote
- **Link**: local:Work Notes/Meetings/Meeting Notes Jan 2026
- **Added Date**: 2026-01-20
- **Last Updated**: 2026-01-20
- **Cache Date**: 2026-01-20
- **Status**: cached
- **Summary**: Meeting notes from project planning session
- **Tags**: meetings, planning
```

### Automate with Datacollector

The datacollector agent can use this method automatically:

1. Add OneNote pages to references.md with `Source Type: onenote`
2. Use `Link: local:Notebook/Section/Page` format for local notebooks
3. Datacollector will detect "local:" prefix and use COM method

## Troubleshooting

### "pywin32 package not installed"

```powershell
pip install pywin32

# If that doesn't work, try:
pip install --upgrade pywin32

# After installation, run:
python Scripts/pywin32_postinstall.py -install
```

### "Failed to connect to OneNote application"

- Ensure OneNote desktop is installed (not just OneNote for Windows 10)
- Try opening OneNote desktop manually first
- On some systems, you may need to run as administrator

### "Page not found"

- Check the exact page title with `list-pages`
- Page titles are case-insensitive but must match
- Try using `fetch-from` with specific notebook and section

### Content looks incorrect

- COM API provides XML format which may not capture all formatting
- For better results, use manual export to DOCX/PDF (see ALTERNATIVES.md)
- Complex formatting (embedded files, drawings) may not convert well

## Comparison: COM vs Graph API

| Feature | COM (Local) | Graph API (Cloud) |
|---------|-------------|-------------------|
| Setup | Easy | Complex |
| Admin Required | No | Yes |
| Auth Required | No | Yes (OAuth2) |
| Notebook Location | Local + Synced | Cloud only |
| Content Quality | Good | Excellent |
| Automation | Full | Full |
| Speed | Fast (local) | Network dependent |

## Best Practices

1. **Close OneNote** while fetching pages (not required but recommended)
2. **Use specific search** with fetch-from for faster results
3. **Sync notebooks** if you need cloud notebooks locally
4. **Test with one page** before bulk operations
5. **Check output quality** - manual export may be better for complex pages

## Next Steps

- **Add more pages**: Fetch additional pages you need
- **Manual export**: For pages with complex formatting, use File > Export in OneNote
- **Integrate with analysis**: Use cached files with document-analyst agent
- **Automate**: Create scripts to fetch multiple pages at once

## Alternative Methods

If COM method doesn't work for you, see [ALTERNATIVES.md](ALTERNATIVES.md) for:
- Manual export to DOCX/PDF
- Power Automate workflows
- IT request templates for Azure AD app
- Browser export methods

## Help

**Need help?** Check:
1. [ALTERNATIVES.md](ALTERNATIVES.md) - Other access methods
2. [README.md](README.md) - Full documentation
3. [SETUP.md](SETUP.md) - Cloud setup (if you get Azure AD access later)
