#!/usr/bin/env python3
"""
OneNote Browser - List notebooks, sections, and pages
Useful for finding page IDs and URLs to fetch
"""

import os
import sys
import json
from datetime import datetime
import requests
import msal


def get_credentials():
    """Get Microsoft Graph API credentials from environment variables"""
    client_id = os.environ.get('ONENOTE_CLIENT_ID')
    client_secret = os.environ.get('ONENOTE_CLIENT_SECRET')
    tenant_id = os.environ.get('ONENOTE_TENANT_ID')
    
    if not client_id or not tenant_id:
        raise ValueError(
            "Missing required environment variables:\n"
            "  ONENOTE_CLIENT_ID\n"
            "  ONENOTE_TENANT_ID\n"
            "  ONENOTE_CLIENT_SECRET (optional for device code flow)"
        )
    
    return client_id, client_secret, tenant_id


def get_graph_token():
    """Get Microsoft Graph API access token"""
    client_id, client_secret, tenant_id = get_credentials()
    
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    scopes = ["https://graph.microsoft.com/.default"]
    
    if client_secret:
        app = msal.ConfidentialClientApplication(
            client_id,
            authority=authority,
            client_credential=client_secret
        )
        result = app.acquire_token_for_client(scopes=scopes)
    else:
        app = msal.PublicClientApplication(client_id, authority=authority)
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


def list_notebooks(token):
    """List all OneNote notebooks"""
    endpoint = "https://graph.microsoft.com/v1.0/me/onenote/notebooks"
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        response = requests.get(endpoint, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json().get('value', [])
    except requests.exceptions.RequestException as e:
        print(f"Error listing notebooks: {e}", file=sys.stderr)
        return []


def list_sections(notebook_id, token):
    """List sections in a notebook"""
    endpoint = f"https://graph.microsoft.com/v1.0/me/onenote/notebooks/{notebook_id}/sections"
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        response = requests.get(endpoint, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json().get('value', [])
    except requests.exceptions.RequestException as e:
        print(f"Error listing sections: {e}", file=sys.stderr)
        return []


def list_pages(section_id, token, limit=10):
    """List pages in a section"""
    endpoint = f"https://graph.microsoft.com/v1.0/me/onenote/sections/{section_id}/pages"
    headers = {'Authorization': f'Bearer {token}'}
    params = {'$top': limit, '$select': 'id,title,createdDateTime,lastModifiedDateTime,links'}
    
    try:
        response = requests.get(endpoint, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get('value', [])
    except requests.exceptions.RequestException as e:
        print(f"Error listing pages: {e}", file=sys.stderr)
        return []


def list_all_pages(token, limit=50):
    """List recent pages across all notebooks"""
    endpoint = "https://graph.microsoft.com/v1.0/me/onenote/pages"
    headers = {'Authorization': f'Bearer {token}'}
    params = {
        '$top': limit,
        '$orderby': 'lastModifiedDateTime desc',
        '$select': 'id,title,createdDateTime,lastModifiedDateTime,links,parentSection,parentNotebook'
    }
    
    try:
        response = requests.get(endpoint, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get('value', [])
    except requests.exceptions.RequestException as e:
        print(f"Error listing pages: {e}", file=sys.stderr)
        return []


def format_datetime(dt_string):
    """Format ISO datetime string"""
    if not dt_string:
        return "N/A"
    try:
        dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M')
    except:
        return dt_string


def main():
    """Main entry point"""
    command = sys.argv[1] if len(sys.argv) > 1 else 'pages'
    
    try:
        print("Authenticating...", file=sys.stderr)
        token = get_graph_token()
        print("Authentication successful\n", file=sys.stderr)
        
        if command == 'notebooks':
            # List all notebooks
            notebooks = list_notebooks(token)
            print(f"Found {len(notebooks)} notebook(s):\n")
            for nb in notebooks:
                print(f"📓 {nb['displayName']}")
                print(f"   ID: {nb['id']}")
                print(f"   Created: {format_datetime(nb.get('createdDateTime'))}")
                print(f"   Modified: {format_datetime(nb.get('lastModifiedDateTime'))}")
                web_url = nb.get('links', {}).get('oneNoteWebUrl', {}).get('href')
                if web_url:
                    print(f"   URL: {web_url}")
                print()
        
        elif command == 'browse':
            # Browse notebooks with sections and pages
            notebooks = list_notebooks(token)
            print(f"Found {len(notebooks)} notebook(s):\n")
            
            for nb in notebooks:
                print(f"📓 {nb['displayName']} ({nb['id']})")
                
                sections = list_sections(nb['id'], token)
                for section in sections:
                    print(f"  📂 {section['displayName']} ({section['id']})")
                    
                    pages = list_pages(section['id'], token, limit=5)
                    for page in pages:
                        print(f"    📄 {page['title']}")
                        print(f"       ID: {page['id']}")
                        print(f"       Modified: {format_datetime(page.get('lastModifiedDateTime'))}")
                        web_url = page.get('links', {}).get('oneNoteWebUrl', {}).get('href')
                        if web_url:
                            print(f"       URL: {web_url}")
                    
                    if len(pages) == 5:
                        print(f"    ... (showing first 5 pages)")
                    print()
                print()
        
        else:  # 'pages' or default
            # List recent pages
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
            pages = list_all_pages(token, limit=limit)
            
            print(f"Recent {len(pages)} page(s):\n")
            for page in pages:
                notebook = page.get('parentNotebook', {})
                section = page.get('parentSection', {})
                
                print(f"📄 {page['title']}")
                print(f"   ID: {page['id']}")
                if notebook:
                    print(f"   Notebook: {notebook.get('displayName', 'N/A')}")
                if section:
                    print(f"   Section: {section.get('displayName', 'N/A')}")
                print(f"   Modified: {format_datetime(page.get('lastModifiedDateTime'))}")
                
                web_url = page.get('links', {}).get('oneNoteWebUrl', {}).get('href')
                if web_url:
                    print(f"   URL: {web_url}")
                
                print(f"   Fetch: python .github\\skills\\onenote-retriever\\scripts\\fetch_onenote.py \"{page['id']}\"")
                print()
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


def print_usage():
    print("OneNote Browser - List notebooks, sections, and pages")
    print("\nUsage:")
    print("  python browse_onenote.py [command] [options]")
    print("\nCommands:")
    print("  pages [limit]    List recent pages (default: 20)")
    print("  notebooks        List all notebooks")
    print("  browse           Browse notebooks with sections and pages")
    print("\nExamples:")
    print("  python browse_onenote.py pages 50")
    print("  python browse_onenote.py notebooks")
    print("  python browse_onenote.py browse")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ['-h', '--help', 'help']:
        print_usage()
        sys.exit(0)
    
    sys.exit(main())
