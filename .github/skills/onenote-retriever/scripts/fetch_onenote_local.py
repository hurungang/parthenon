#!/usr/bin/env python3
"""
OneNote Local Fetcher - Access local OneNote notebooks via COM automation
Works with OneNote desktop application on Windows
NO Azure AD registration required!
"""

import os
import sys
import re
from datetime import datetime
from xml.etree import ElementTree as ET

try:
    import win32com.client
    HAS_WIN32COM = True
except ImportError:
    HAS_WIN32COM = False
    print("ERROR: pywin32 package not installed", file=sys.stderr)
    print("Install with: pip install pywin32", file=sys.stderr)
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
    import html2text
    HAS_HTML_TOOLS = True
except ImportError:
    HAS_HTML_TOOLS = False
    print("Warning: beautifulsoup4 or html2text not installed. Using basic conversion.", file=sys.stderr)


def get_onenote_app():
    """Connect to OneNote application via COM"""
    try:
        onenote = win32com.client.Dispatch("OneNote.Application")
        return onenote
    except Exception as e:
        raise Exception(
            f"Failed to connect to OneNote application: {e}\n"
            "Make sure OneNote desktop is installed on Windows."
        )


def list_notebooks(onenote):
    """List all OneNote notebooks"""
    xml = onenote.GetHierarchy("", 1)  # 1 = notebooks only
    root = ET.fromstring(xml)
    
    notebooks = []
    for notebook in root.findall('.//{http://schemas.microsoft.com/office/onenote/2013/onenote}Notebook'):
        notebooks.append({
            'name': notebook.get('name'),
            'id': notebook.get('ID'),
            'path': notebook.get('path', '')
        })
    return notebooks


def list_sections(onenote, notebook_id=None):
    """List sections in a notebook or all sections"""
    scope = notebook_id if notebook_id else ""
    xml = onenote.GetHierarchy(scope, 2)  # 2 = sections
    root = ET.fromstring(xml)
    
    sections = []
    for section in root.findall('.//{http://schemas.microsoft.com/office/onenote/2013/onenote}Section'):
        sections.append({
            'name': section.get('name'),
            'id': section.get('ID'),
            'path': section.get('path', '')
        })
    return sections


def list_pages(onenote, section_id=None):
    """List pages in a section or all pages"""
    scope = section_id if section_id else ""
    xml = onenote.GetHierarchy(scope, 3)  # 3 = pages
    root = ET.fromstring(xml)
    
    pages = []
    for page in root.findall('.//{http://schemas.microsoft.com/office/onenote/2013/onenote}Page'):
        pages.append({
            'title': page.get('name'),
            'id': page.get('ID'),
            'date_time': page.get('dateTime', ''),
            'last_modified': page.get('lastModifiedTime', '')
        })
    return pages


def find_page_by_title(onenote, notebook_name=None, section_name=None, page_title=None):
    """Find a page by notebook, section, and/or title"""
    xml = onenote.GetHierarchy("", 4)  # 4 = all levels
    root = ET.fromstring(xml)
    
    ns = {'one': 'http://schemas.microsoft.com/office/onenote/2013/onenote'}
    
    for notebook in root.findall('.//one:Notebook', ns):
        nb_name = notebook.get('name')
        
        # Filter by notebook name if specified
        if notebook_name and notebook_name.lower() not in nb_name.lower():
            continue
        
        for section in notebook.findall('.//one:Section', ns):
            sec_name = section.get('name')
            
            # Filter by section name if specified
            if section_name and section_name.lower() not in sec_name.lower():
                continue
            
            for page in section.findall('.//one:Page', ns):
                page_name = page.get('name')
                
                # Filter by page title if specified
                if page_title and page_title.lower() not in page_name.lower():
                    continue
                
                return {
                    'notebook': nb_name,
                    'section': sec_name,
                    'title': page_name,
                    'id': page.get('ID'),
                    'date_time': page.get('dateTime', ''),
                    'last_modified': page.get('lastModifiedTime', '')
                }
    
    return None


def get_page_content(onenote, page_id):
    """Get page content as XML"""
    xml = onenote.GetPageContent(page_id)
    return xml


def convert_onenote_xml_to_markdown(xml_content):
    """Convert OneNote XML to markdown"""
    try:
        root = ET.fromstring(xml_content)
        ns = {'one': 'http://schemas.microsoft.com/office/onenote/2013/onenote'}
        
        lines = []
        
        # Extract page title
        page_title = root.get('name', 'Untitled')
        
        # Find all outline elements (content containers)
        for outline in root.findall('.//one:Outline', ns):
            for oe_children in outline.findall('.//one:OEChildren', ns):
                for oe in oe_children.findall('.//one:OE', ns):
                    # Extract text content
                    text_elements = oe.findall('.//one:T', ns)
                    for text in text_elements:
                        if text.text:
                            # Try to detect list items
                            if oe.get('list'):
                                lines.append(f"- {text.text}")
                            else:
                                lines.append(text.text)
        
        markdown = '\n'.join(lines)
        
        # If we have HTML tools, try to improve conversion
        if HAS_HTML_TOOLS and '<' in markdown:
            try:
                h = html2text.HTML2Text()
                h.body_width = 0
                markdown = h.handle(markdown)
            except:
                pass
        
        return markdown.strip()
        
    except Exception as e:
        print(f"Warning: Failed to parse XML content: {e}", file=sys.stderr)
        # Fallback: extract all text content
        try:
            root = ET.fromstring(xml_content)
            text_parts = []
            for elem in root.iter():
                if elem.text and elem.text.strip():
                    text_parts.append(elem.text.strip())
            return '\n'.join(text_parts)
        except:
            return "(Could not extract page content)"


def format_page_as_markdown(page_info, content):
    """Format page data as markdown"""
    lines = []
    
    # Title
    title = page_info.get('title', 'Untitled Page')
    lines.append(f"# {title}")
    lines.append("")
    
    # Metadata
    lines.append("## Metadata")
    lines.append("")
    lines.append(f"**Notebook**: {page_info.get('notebook', 'Unknown')}")
    lines.append(f"**Section**: {page_info.get('section', 'Unknown')}")
    
    if page_info.get('date_time'):
        lines.append(f"**Created**: {page_info['date_time']}")
    
    if page_info.get('last_modified'):
        lines.append(f"**Last Modified**: {page_info['last_modified']}")
    
    lines.append(f"**Page ID**: {page_info.get('id', 'Unknown')}")
    lines.append(f"**Retrieved**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Source**: Local OneNote via COM")
    lines.append("")
    
    # Content
    lines.append("## Content")
    lines.append("")
    lines.append(content)
    lines.append("")
    
    lines.append("---")
    lines.append(f"*Retrieved from local OneNote via COM automation on {datetime.now().strftime('%Y-%m-%d')}*")
    
    return '\n'.join(lines)


def save_to_cache(markdown_content, page_id):
    """Save markdown content to cache directory"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, '..', '..', '..'))
    cache_dir = os.path.join(repo_root, 'workspace', '_cache')
    
    os.makedirs(cache_dir, exist_ok=True)
    
    # Generate filename from page ID
    safe_id = re.sub(r'[^\w\-]', '-', page_id)
    filename = f"onenote-local-{safe_id[:50]}.md"
    filepath = os.path.join(cache_dir, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(markdown_content)
    
    return filepath


def main():
    if len(sys.argv) < 2:
        print("OneNote Local Fetcher - Access local OneNote via COM")
        print("\nUsage:")
        print("  python fetch_onenote_local.py list")
        print("  python fetch_onenote_local.py list-notebooks")
        print("  python fetch_onenote_local.py list-pages [notebook-name]")
        print("  python fetch_onenote_local.py fetch <page-title>")
        print("  python fetch_onenote_local.py fetch-from <notebook> <section> <page-title>")
        print("\nExamples:")
        print('  python fetch_onenote_local.py list-notebooks')
        print('  python fetch_onenote_local.py list-pages "My Notebook"')
        print('  python fetch_onenote_local.py fetch "Meeting Notes"')
        print('  python fetch_onenote_local.py fetch-from "Work" "Projects" "Project Plan"')
        sys.exit(0)
    
    command = sys.argv[1].lower()
    
    try:
        print("Connecting to OneNote...", file=sys.stderr)
        onenote = get_onenote_app()
        print("Connected successfully", file=sys.stderr)
        
        if command == 'list-notebooks' or command == 'list':
            notebooks = list_notebooks(onenote)
            print(f"\nFound {len(notebooks)} notebook(s):\n")
            for nb in notebooks:
                print(f"📓 {nb['name']}")
                if nb['path']:
                    print(f"   Path: {nb['path']}")
                print(f"   ID: {nb['id']}")
                print()
        
        elif command == 'list-pages':
            notebook_name = sys.argv[2] if len(sys.argv) > 2 else None
            
            if notebook_name:
                print(f"Listing pages in notebook: {notebook_name}\n", file=sys.stderr)
                page_info = find_page_by_title(onenote, notebook_name=notebook_name)
                # This is a hack - we need to find all pages in the notebook
                # For now, list all pages and filter
                print("(Showing all pages - filtering not fully implemented)\n")
            
            xml = onenote.GetHierarchy("", 4)  # All levels
            root = ET.fromstring(xml)
            ns = {'one': 'http://schemas.microsoft.com/office/onenote/2013/onenote'}
            
            print("\nRecent Pages:\n")
            count = 0
            for page in root.findall('.//one:Page', ns):
                if count >= 20:  # Limit to 20
                    break
                title = page.get('name')
                page_id = page.get('ID')
                modified = page.get('lastModifiedTime', 'N/A')
                print(f"📄 {title}")
                print(f"   Modified: {modified}")
                print(f'   Fetch: python fetch_onenote_local.py fetch "{title}"')
                print()
                count += 1
        
        elif command == 'fetch':
            if len(sys.argv) < 3:
                print("Error: Please provide page title", file=sys.stderr)
                print('Usage: python fetch_onenote_local.py fetch "Page Title"', file=sys.stderr)
                sys.exit(1)
            
            page_title = sys.argv[2]
            print(f"Searching for page: {page_title}", file=sys.stderr)
            
            page_info = find_page_by_title(onenote, page_title=page_title)
            
            if not page_info:
                print(f"Error: Page not found with title matching: {page_title}", file=sys.stderr)
                print("\nTry: python fetch_onenote_local.py list-pages", file=sys.stderr)
                sys.exit(1)
            
            print(f"Found: {page_info['title']}", file=sys.stderr)
            print(f"Notebook: {page_info['notebook']}", file=sys.stderr)
            print(f"Section: {page_info['section']}", file=sys.stderr)
            
            print("Fetching content...", file=sys.stderr)
            xml_content = get_page_content(onenote, page_info['id'])
            
            print("Converting to markdown...", file=sys.stderr)
            markdown_content_only = convert_onenote_xml_to_markdown(xml_content)
            
            markdown_full = format_page_as_markdown(page_info, markdown_content_only)
            
            filepath = save_to_cache(markdown_full, page_info['id'])
            print(f"Saved to: {filepath}", file=sys.stderr)
            
            print(markdown_full)
        
        elif command == 'fetch-from':
            if len(sys.argv) < 5:
                print("Error: Please provide notebook, section, and page title", file=sys.stderr)
                print('Usage: python fetch_onenote_local.py fetch-from "Notebook" "Section" "Page"', file=sys.stderr)
                sys.exit(1)
            
            notebook_name = sys.argv[2]
            section_name = sys.argv[3]
            page_title = sys.argv[4]
            
            print(f"Searching in {notebook_name} > {section_name} > {page_title}", file=sys.stderr)
            
            page_info = find_page_by_title(onenote, notebook_name, section_name, page_title)
            
            if not page_info:
                print(f"Error: Page not found", file=sys.stderr)
                sys.exit(1)
            
            print(f"Found: {page_info['title']}", file=sys.stderr)
            print("Fetching content...", file=sys.stderr)
            
            xml_content = get_page_content(onenote, page_info['id'])
            markdown_content_only = convert_onenote_xml_to_markdown(xml_content)
            markdown_full = format_page_as_markdown(page_info, markdown_content_only)
            
            filepath = save_to_cache(markdown_full, page_info['id'])
            print(f"Saved to: {filepath}", file=sys.stderr)
            
            print(markdown_full)
        
        else:
            print(f"Unknown command: {command}", file=sys.stderr)
            print("Use --help for usage information", file=sys.stderr)
            sys.exit(1)
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
