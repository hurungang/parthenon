#!/usr/bin/env python3
"""
OneNote Page Fetcher - Retrieves OneNote pages via Microsoft Graph API
Supports OAuth2 authentication with client credentials or device code flow
"""

import os
import sys
import json
import re
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote
import requests
import msal
from bs4 import BeautifulSoup
import html2text


def get_credentials():
    """Get Microsoft Graph API credentials from environment variables"""
    client_id = os.environ.get('ONENOTE_CLIENT_ID')
    client_secret = os.environ.get('ONENOTE_CLIENT_SECRET')
    tenant_id = os.environ.get('ONENOTE_TENANT_ID')
    
    if not client_id or not tenant_id:
        raise ValueError(
            "Missing required environment variables:\n"
            "  ONENOTE_CLIENT_ID - Your Azure AD application client ID\n"
            "  ONENOTE_TENANT_ID - Your Azure AD tenant ID\n"
            "  ONENOTE_CLIENT_SECRET - Your client secret (optional for device code flow)"
        )
    
    return client_id, client_secret, tenant_id


def get_graph_token():
    """Get Microsoft Graph API access token"""
    client_id, client_secret, tenant_id = get_credentials()
    
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    scopes = ["https://graph.microsoft.com/.default"]
    
    if client_secret:
        # Use client credentials flow (non-interactive)
        app = msal.ConfidentialClientApplication(
            client_id,
            authority=authority,
            client_credential=client_secret
        )
        
        result = app.acquire_token_for_client(scopes=scopes)
    else:
        # Use device code flow (interactive)
        app = msal.PublicClientApplication(
            client_id,
            authority=authority
        )
        
        flow = app.initiate_device_flow(scopes=scopes)
        
        if "user_code" not in flow:
            raise Exception("Failed to create device flow")
        
        print(flow["message"])
        sys.stdout.flush()
        
        result = app.acquire_token_by_device_flow(flow)
    
    if "access_token" in result:
        return result["access_token"]
    else:
        error = result.get("error_description", result.get("error", "Unknown error"))
        raise Exception(f"Failed to acquire token: {error}")


def extract_page_info_from_url(url):
    """
    Extract page ID and other info from OneNote URL
    Supports various URL formats
    """
    # Direct Graph API URL
    # https://graph.microsoft.com/v1.0/me/onenote/pages/{page-id}
    match = re.search(r'/onenote/pages/([0-9a-zA-Z\-]+)', url)
    if match:
        return {'page_id': match.group(1)}
    
    # OneNote web URL with id parameter
    # https://onedrive.live.com/view.aspx?resid=...&id=documents
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    
    if 'id' in params:
        # Sometimes the page ID is in the id parameter
        page_id = params['id'][0]
        if page_id and len(page_id) > 10:  # Basic validation
            return {'page_id': page_id}
    
    # OneNote protocol URL
    # onenote:https://d.docs.live.net/...#...&page-id={...}
    match = re.search(r'page-id=\{?([0-9a-zA-Z\-]+)\}?', url)
    if match:
        return {'page_id': match.group(1)}
    
    # Extract from fragment
    if parsed.fragment:
        match = re.search(r'page-id=\{?([0-9a-zA-Z\-]+)\}?', parsed.fragment)
        if match:
            return {'page_id': match.group(1)}
    
    raise ValueError(
        f"Could not extract page ID from URL: {url}\n"
        "Supported formats:\n"
        "  - https://graph.microsoft.com/v1.0/me/onenote/pages/{{page-id}}\n"
        "  - OneNote web links with page IDs\n"
        "  - OneNote protocol URLs with page-id parameter"
    )


def fetch_page_content(page_id, token):
    """Fetch OneNote page content via Microsoft Graph API"""
    # Try different API endpoints
    endpoints = [
        f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page_id}",
        f"https://graph.microsoft.com/v1.0/users/me/onenote/pages/{page_id}",
        f"https://graph.microsoft.com/v1.0/sites/root/onenote/pages/{page_id}"
    ]
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json'
    }
    
    last_error = None
    for endpoint in endpoints:
        try:
            response = requests.get(endpoint, headers=headers, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                last_error = "Page not found"
                continue
            else:
                response.raise_for_status()
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            continue
    
    raise Exception(f"Failed to fetch page from all endpoints. Last error: {last_error}")


def fetch_page_content_html(page_id, token):
    """Fetch OneNote page HTML content"""
    endpoint = f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page_id}/content"
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'text/html'
    }
    
    try:
        response = requests.get(endpoint, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        # If HTML content fetch fails, return None - we'll work with metadata only
        print(f"Warning: Could not fetch HTML content: {e}", file=sys.stderr)
        return None


def convert_onenote_html_to_markdown(html_content):
    """Convert OneNote HTML to markdown"""
    if not html_content:
        return ""
    
    # Parse HTML with BeautifulSoup to clean it up
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()
    
    # Convert to markdown using html2text
    h = html2text.HTML2Text()
    h.body_width = 0  # Don't wrap lines
    h.ignore_links = False
    h.ignore_images = False
    h.ignore_emphasis = False
    h.ignore_tables = False
    h.unicode_snob = True
    h.skip_internal_links = True
    
    markdown = h.handle(str(soup))
    
    # Clean up excessive newlines
    markdown = re.sub(r'\n\s*\n\s*\n+', '\n\n', markdown)
    
    return markdown.strip()


def format_page_as_markdown(page_data, html_content, source_url):
    """Format OneNote page data as markdown"""
    lines = []
    
    # Title
    title = page_data.get('title', 'Untitled Page')
    lines.append(f"# {title}")
    lines.append("")
    
    # Metadata
    lines.append("## Metadata")
    lines.append("")
    
    # Parent notebook/section info
    parent_section = page_data.get('parentSection')
    if parent_section:
        section_name = parent_section.get('displayName', 'Unknown Section')
        lines.append(f"**Section**: {section_name}")
    
    parent_notebook = page_data.get('parentNotebook')
    if parent_notebook:
        notebook_name = parent_notebook.get('displayName', 'Unknown Notebook')
        lines.append(f"**Notebook**: {notebook_name}")
    
    # Dates
    created_datetime = page_data.get('createdDateTime')
    if created_datetime:
        created = datetime.fromisoformat(created_datetime.replace('Z', '+00:00'))
        lines.append(f"**Created**: {created.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    last_modified = page_data.get('lastModifiedDateTime')
    if last_modified:
        modified = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
        lines.append(f"**Last Modified**: {modified.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    # Author
    created_by = page_data.get('createdBy')
    if created_by:
        user = created_by.get('user', {})
        display_name = user.get('displayName', 'Unknown')
        lines.append(f"**Created By**: {display_name}")
    
    last_modified_by = page_data.get('lastModifiedBy')
    if last_modified_by:
        user = last_modified_by.get('user', {})
        display_name = user.get('displayName', 'Unknown')
        lines.append(f"**Last Modified By**: {display_name}")
    
    # Links
    web_url = page_data.get('links', {}).get('oneNoteWebUrl', {}).get('href')
    if web_url:
        lines.append(f"**Web URL**: {web_url}")
    
    lines.append(f"**Source URL**: {source_url}")
    lines.append(f"**Retrieved**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    
    # Page content
    lines.append("## Content")
    lines.append("")
    
    if html_content:
        content_markdown = convert_onenote_html_to_markdown(html_content)
        lines.append(content_markdown)
    else:
        lines.append("*Content could not be retrieved*")
    
    lines.append("")
    lines.append("---")
    lines.append(f"*Retrieved from OneNote via Microsoft Graph API on {datetime.now().strftime('%Y-%m-%d')}*")
    
    return '\n'.join(lines)


def save_to_cache(markdown_content, page_id):
    """Save markdown content to cache directory"""
    # Determine cache directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, '..', '..', '..'))
    cache_dir = os.path.join(repo_root, 'workspace', '_cache')
    
    # Create cache directory if it doesn't exist
    os.makedirs(cache_dir, exist_ok=True)
    
    # Generate filename
    # Sanitize page_id for filename
    safe_page_id = re.sub(r'[^\w\-]', '-', page_id)
    filename = f"onenote-{safe_page_id}.md"
    filepath = os.path.join(cache_dir, filename)
    
    # Write to file
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(markdown_content)
    
    return filepath


def main():
    if len(sys.argv) < 2:
        print("Usage: python fetch_onenote.py <ONENOTE_PAGE_URL>")
        print("\nExamples:")
        print("  python fetch_onenote.py 'https://graph.microsoft.com/v1.0/me/onenote/pages/{page-id}'")
        print("  python fetch_onenote.py 'https://onedrive.live.com/view.aspx?...'")
        print("  python fetch_onenote.py 'onenote:https://...'")
        sys.exit(1)
    
    page_url = sys.argv[1]
    
    try:
        # Extract page info from URL
        print(f"Parsing URL: {page_url}", file=sys.stderr)
        page_info = extract_page_info_from_url(page_url)
        page_id = page_info['page_id']
        print(f"Page ID: {page_id}", file=sys.stderr)
        
        # Get access token
        print("Authenticating with Microsoft Graph API...", file=sys.stderr)
        token = get_graph_token()
        print("Authentication successful", file=sys.stderr)
        
        # Fetch page metadata
        print("Fetching page metadata...", file=sys.stderr)
        page_data = fetch_page_content(page_id, token)
        print(f"Page title: {page_data.get('title', 'Untitled')}", file=sys.stderr)
        
        # Fetch page HTML content
        print("Fetching page content...", file=sys.stderr)
        html_content = fetch_page_content_html(page_id, token)
        
        # Convert to markdown
        print("Converting to markdown...", file=sys.stderr)
        markdown_content = format_page_as_markdown(page_data, html_content, page_url)
        
        # Save to cache
        filepath = save_to_cache(markdown_content, page_id)
        print(f"Saved to: {filepath}", file=sys.stderr)
        
        # Output the markdown (for potential piping/capture)
        print(markdown_content)
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
