# Alternative Access Methods for OneNote

If you don't have permission to create Azure AD applications, here are several alternatives to access OneNote content.

## Option 1: Request IT to Create Application (Recommended)

Contact your IT department or Azure AD administrator and request they create an application for you with these specifications:

### Application Registration Request Template

```
Subject: Request for Azure AD App Registration - OneNote Content Retriever

Hi IT Team,

I need to programmatically access OneNote content for documentation purposes. 
Could you please create an Azure AD application registration with the following configuration?

Application Name: OneNote Content Retriever
Application Type: Web application
Required API Permission: Microsoft Graph - Notes.Read.All (Application permission)
Grant Admin Consent: Yes

Please provide me with:
- Application (Client) ID
- Tenant ID
- Client Secret (or configure certificate-based auth)

The application will be used to fetch OneNote pages and convert them to markdown 
for our documentation workflow.

Thank you!
```

## Option 2: Manual Export (No Setup Required)

Export OneNote pages manually and use existing document skills.

### Export to Word (DOCX)

1. Open your OneNote page
2. Go to **File** > **Export**
3. Choose **Page** or **Section**
4. Select format: **Word Document (*.docx)**
5. Save to your workspace

Then use the existing docx skill:
```powershell
python .github\skills\docx\scripts\extract_docx.py "path\to\exported\page.docx"
```

### Export to PDF

1. Open your OneNote page
2. Go to **File** > **Export**
3. Choose **Page** or **Section**
4. Select format: **PDF (*.pdf)**
5. Save to your workspace

Then use the existing pdf skill:
```powershell
python .github\skills\pdf\scripts\extract_pdf.py "path\to\exported\page.pdf"
```

### Export to HTML

1. Open your OneNote page
2. Go to **File** > **Export**
3. Choose **Page**
4. Select format: **Web Page (*.html)**
5. Save to your workspace

Then process the HTML file directly or use a simple converter.

## Option 3: Use Shared Organizational App

Your organization may already have a shared application for accessing Microsoft Graph. Ask your IT team:

1. "Do we have a shared Azure AD app for Microsoft Graph access?"
2. "Can I get credentials for the shared app?"
3. "What permissions does it have?"

If they provide credentials, use them with the existing scripts:
```powershell
$env:ONENOTE_CLIENT_ID = "organizational-client-id"
$env:ONENOTE_CLIENT_SECRET = "organizational-secret"
$env:ONENOTE_TENANT_ID = "your-tenant-id"
```

## Option 4: Local OneNote Files (.one)

If you have local OneNote files (not cloud-based), you can access them directly.

### Using OneNote Desktop Application

1. Open OneNote desktop application
2. Navigate to the page you need
3. Use export method (Option 2 above)

### Direct File Access (Advanced)

OneNote local files (.one) are in a proprietary binary format. Options:

1. **Use OneNote Object Model (COM)**
   - Requires OneNote desktop installed
   - Can be accessed via Python with `win32com`
   - See [create_onenote_com_script.py](#option-5-script-below)

2. **Third-party libraries**
   - Limited support, may not work with latest OneNote format
   - Not recommended for production use

## Option 5: OneNote COM Automation (Windows Only)

If you have OneNote desktop installed on Windows, you can use COM automation without Azure AD.

### Create COM-based Script

I'll create a Windows-specific script that uses the OneNote COM API:

```python
# .github/skills/onenote-retriever/scripts/fetch_onenote_local.py
```

This requires:
- Windows OS
- OneNote desktop application installed
- Python with `pywin32` package

Usage:
```powershell
pip install pywin32
python .github\skills\onenote-retriever\scripts\fetch_onenote_local.py "Notebook Name" "Section Name" "Page Title"
```

## Option 6: Power Automate Export (No Coding)

Use Microsoft Power Automate to export OneNote pages automatically:

1. Go to [Power Automate](https://make.powerautomate.com)
2. Create a new flow
3. Trigger: Manual or Scheduled
4. Action: **OneNote - Get page content**
5. Action: **Create file** (save as HTML or text)
6. Save files to SharePoint/OneDrive
7. Access files using existing skills

## Option 7: Browser Extension Export

Use browser extensions to save OneNote web pages:

1. Open OneNote page in web browser
2. Use "Save as PDF" or "Print to PDF"
3. Or use browser extension like "SingleFile" to save complete HTML
4. Process with existing pdf/html skills

## Comparison of Methods

| Method | Setup Effort | Automation | Content Fidelity | Requires Admin |
|--------|--------------|------------|------------------|----------------|
| Azure AD App | High | Full | Excellent | Yes |
| IT Request | Medium | Full | Excellent | No (IT handles) |
| Manual Export | Low | None | Excellent | No |
| Shared App | Low | Full | Excellent | No |
| COM Automation | Medium | Full | Good | No |
| Power Automate | Medium | Partial | Good | No |
| Browser Export | Low | None | Fair | No |

## Recommended Approach

**For One-Time Use:**
- Use manual export (Option 2) - quickest, no setup

**For Regular Use:**
- Request IT to create app (Option 1) - best long-term solution
- Or use COM automation (Option 5) if on Windows with OneNote desktop

**For Occasional Use:**
- Check for shared organizational app (Option 3)
- Or use Power Automate (Option 6) for semi-automated export

## Next Steps Based on Your Choice

### If Requesting IT Support (Option 1)
1. Send request email (template above)
2. Wait for credentials
3. Configure environment variables
4. Test with browse script

### If Using Manual Export (Option 2)
1. Export pages to DOCX or PDF
2. Save to `workspace/files/`
3. Use existing docx/pdf skills
4. Update references-list.md with local file paths

### If Using COM Automation (Option 5)
1. Verify OneNote desktop installed
2. Install pywin32: `pip install pywin32`
3. I can create the COM-based script for you
4. Test with local notebooks

Would you like me to:
1. **Create the COM automation script** for local OneNote access (Windows)?
2. **Show you how to set up manual export workflow** with existing skills?
3. **Create the IT request documentation** with more details?
4. **Set up Power Automate flow instructions**?

Let me know which approach works best for your situation!
