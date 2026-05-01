#!/usr/bin/env python3
"""
Confluence Page Fetcher - Retrieves Confluence pages from Confluence Cloud
Supports API token authentication for Atlassian Cloud
"""

import os
import sys
import json
import re
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import requests
from requests.auth import HTTPBasicAuth
from html.parser import HTMLParser
from io import StringIO


class HTMLToMarkdown(HTMLParser):
    """Simple HTML to Markdown converter for Confluence storage format"""
    
    def __init__(self):
        super().__init__()
        self.markdown = StringIO()
        self.in_list = False
        self.list_depth = 0
        self.in_code = False
        self.in_pre = False
        self.tags = []
        
    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attrs_dict = dict(attrs)
        
        if tag == 'h1':
            self.markdown.write('\n# ')
        elif tag == 'h2':
            self.markdown.write('\n## ')
        elif tag == 'h3':
            self.markdown.write('\n### ')
        elif tag == 'h4':
            self.markdown.write('\n#### ')
        elif tag == 'h5':
            self.markdown.write('\n##### ')
        elif tag == 'h6':
            self.markdown.write('\n###### ')
        elif tag == 'p':
            self.markdown.write('\n\n')
        elif tag == 'br':
            self.markdown.write('  \n')
        elif tag == 'strong' or tag == 'b':
            self.markdown.write('**')
        elif tag == 'em' or tag == 'i':
            self.markdown.write('*')
        elif tag == 'code':
            if not self.in_pre:
                self.markdown.write('`')
                self.in_code = True
        elif tag == 'pre':
            self.markdown.write('\n```\n')
            self.in_pre = True
        elif tag == 'ul':
            self.in_list = True
            self.list_depth += 1
        elif tag == 'ol':
            self.in_list = True
            self.list_depth += 1
        elif tag == 'li':
            indent = '  ' * (self.list_depth - 1)
            self.markdown.write(f'\n{indent}- ')
        elif tag == 'a':
            href = attrs_dict.get('href', '#')
            self.markdown.write('[')
        elif tag == 'img':
            src = attrs_dict.get('src', '')
            alt = attrs_dict.get('alt', 'image')
            self.markdown.write(f'\n![{alt}]({src})\n')
        elif tag == 'blockquote':
            self.markdown.write('\n> ')
        elif tag == 'hr':
            self.markdown.write('\n---\n')
        elif tag == 'table':
            self.markdown.write('\n\n')
        elif tag == 'tr':
            self.markdown.write('| ')
        elif tag == 'td' or tag == 'th':
            pass  # Will add content in handle_data
            
    def handle_endtag(self, tag):
        if self.tags and self.tags[-1] == tag:
            self.tags.pop()
        
        if tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            self.markdown.write('\n')
        elif tag == 'p':
            self.markdown.write('\n')
        elif tag == 'strong' or tag == 'b':
            self.markdown.write('**')
        elif tag == 'em' or tag == 'i':
            self.markdown.write('*')
        elif tag == 'code':
            if not self.in_pre:
                self.markdown.write('`')
                self.in_code = False
        elif tag == 'pre':
            self.markdown.write('\n```\n')
            self.in_pre = False
        elif tag == 'ul' or tag == 'ol':
            self.list_depth -= 1
            if self.list_depth == 0:
                self.in_list = False
            self.markdown.write('\n')
        elif tag == 'a':
            # Get href from the start tag
            for i in range(len(self.tags) - 1, -1, -1):
                if self.tags[i] == 'a':
                    break
            self.markdown.write('](#)')  # Simplified - we'd need to store href
        elif tag == 'blockquote':
            self.markdown.write('\n')
        elif tag == 'tr':
            self.markdown.write('\n')
        elif tag == 'td' or tag == 'th':
            self.markdown.write(' | ')
            
    def handle_data(self, data):
        # Clean up whitespace but preserve some formatting
        if not self.in_pre:
            data = ' '.join(data.split())
        if data:
            self.markdown.write(data)
    
    def get_markdown(self):
        content = self.markdown.getvalue()
        # Clean up extra newlines
        content = re.sub(r'\n{3,}', '\n\n', content)
        return content.strip()


def extract_page_id(url):
    """Extract Confluence page ID from URL"""
    # Handle various Confluence URL formats
    # Example: https://company.atlassian.net/wiki/spaces/SPACE/pages/123456/Page+Title
    # Example: https://company.atlassian.net/wiki/pages/viewpage.action?pageId=123456
    
    # Try to find pageId in query params
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    if 'pageId' in query_params:
        return query_params['pageId'][0]
    
    # Try to extract from path-based URL
    match = re.search(r'/pages/(\d+)/', url)
    if match:
        return match.group(1)
    
    raise ValueError(f"Could not extract page ID from URL: {url}")


def get_confluence_credentials():
    """Get Confluence credentials from environment variables"""
    base_url = os.environ.get('CONFLUENCE_BASE_URL')
    username = os.environ.get('CONFLUENCE_USERNAME')  # Email for Cloud
    token = os.environ.get('CONFLUENCE_API_TOKEN')
    
    if not all([base_url, username, token]):
        raise ValueError(
            "Missing required environment variables:\n"
            "  CONFLUENCE_BASE_URL - Your Confluence Cloud URL\n"
            "  CONFLUENCE_USERNAME - Your Atlassian account email\n"
            "  CONFLUENCE_API_TOKEN - Your Confluence API token\n"
            "\n"
            "Get API token from: https://id.atlassian.com/manage-profile/security/api-tokens"
        )
    
    return base_url.rstrip('/'), username, token


def fetch_confluence_page(base_url, page_id, username, token):
    """Fetch Confluence page via REST API"""
    # Confluence Cloud API endpoint
    api_url = f"{base_url}/rest/api/content/{page_id}"
    
    # Request page with body content, metadata, and children
    params = {
        'expand': 'body.storage,version,space,metadata.labels,children.page,ancestors'
    }
    
    auth = HTTPBasicAuth(username, token)
    
    try:
        response = requests.get(api_url, auth=auth, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to fetch Confluence page: {e}")


def convert_storage_to_markdown(storage_html):
    """Convert Confluence storage format HTML to markdown"""
    if not storage_html:
        return ""
    
    # Use our HTML to Markdown converter
    converter = HTMLToMarkdown()
    converter.feed(storage_html)
    return converter.get_markdown()


def format_page_as_markdown(page_data, source_url):
    """Convert Confluence page JSON to markdown format"""
    page_id = page_data.get('id', 'unknown')
    title = page_data.get('title', 'Untitled')
    space = page_data.get('space', {})
    space_name = space.get('name', 'Unknown Space')
    
    # Version info
    version_info = page_data.get('version', {})
    last_modified = version_info.get('when', '')
    modified_by = version_info.get('by', {}).get('displayName', 'Unknown')
    
    # Content
    body = page_data.get('body', {}).get('storage', {})
    content_html = body.get('value', '')
    content_md = convert_storage_to_markdown(content_html)
    
    # Build markdown
    md = [
        f"# {title}",
        "",
        "---",
        "",
        f"**Source:** {source_url}",
        f"**Retrieved:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Space:** {space_name}",
        f"**Last Modified:** {last_modified} by {modified_by}",
        "",
        "---",
        "",
    ]
    
    # Labels
    labels_data = page_data.get('metadata', {}).get('labels', {}).get('results', [])
    if labels_data:
        labels = [label.get('name', '') for label in labels_data]
        md.append(f"**Labels:** {', '.join(labels)}")
        md.append("")
    
    # Breadcrumbs (ancestors)
    ancestors = page_data.get('ancestors', [])
    if ancestors:
        md.append("**Breadcrumb:**")
        breadcrumb = ' > '.join([a.get('title', '') for a in ancestors])
        md.append(f"{breadcrumb} > {title}")
        md.append("")
    
    # Main content
    if content_md:
        md.append("## Content")
        md.append("")
        md.append(content_md)
        md.append("")
    
    # Child pages
    children = page_data.get('children', {}).get('page', {}).get('results', [])
    if children:
        md.append("## Child Pages")
        md.append("")
        for child in children:
            child_title = child.get('title', 'Untitled')
            child_id = child.get('id', '')
            md.append(f"- {child_title} (ID: {child_id})")
        md.append("")
    
    # Attachments (if available in expanded data)
    attachments = page_data.get('children', {}).get('attachment', {}).get('results', [])
    if attachments:
        md.append("## Attachments")
        md.append("")
        for att in attachments:
            filename = att.get('title', 'unknown')
            download_link = att.get('_links', {}).get('download', '#')
            md.append(f"- [{filename}]({base_url}{download_link})")
        md.append("")
    
    return '\n'.join(md)


def main():
    if len(sys.argv) < 2:
        print("Usage: python fetch_confluence.py <CONFLUENCE_PAGE_URL>", file=sys.stderr)
        print("\nExample:", file=sys.stderr)
        print("  python fetch_confluence.py https://company.atlassian.net/wiki/spaces/SPACE/pages/123456/Page+Title", file=sys.stderr)
        sys.exit(1)
    
    page_url = sys.argv[1]
    
    try:
        # Extract page ID from URL
        page_id = extract_page_id(page_url)
        print(f"Fetching Confluence page: {page_id}", file=sys.stderr)
        
        # Get credentials
        base_url, username, token = get_confluence_credentials()
        
        # Fetch page data
        page_data = fetch_confluence_page(base_url, page_id, username, token)
        
        # Convert to markdown
        markdown = format_page_as_markdown(page_data, page_url)
        
        # Output markdown to stdout
        print(markdown)
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
