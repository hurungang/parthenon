#!/usr/bin/env python3
"""
JIRA Ticket Fetcher - Retrieves JIRA issues from on-premises JIRA server
Supports Personal Access Token (PAT) authentication
"""

import os
import sys
import json
import re
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import requests

try:
    import html2text
    HAS_HTML2TEXT = True
except ImportError:
    HAS_HTML2TEXT = False
    import html


def extract_issue_key(url):
    """Extract JIRA issue key from URL"""
    # Handle both browse and issue URLs
    # Example: https://jira.company.com/browse/PROJ-123
    # Example: https://jira.company.com/jira/browse/PROJ-123
    match = re.search(r'/browse/([A-Z]+-\d+)', url)
    if match:
        return match.group(1)
    
    # Try to find issue key in query params
    parsed = urlparse(url)
    if 'selectedIssue' in parse_qs(parsed.query):
        return parse_qs(parsed.query)['selectedIssue'][0]
    
    raise ValueError(f"Could not extract issue key from URL: {url}")


def get_jira_credentials():
    """Get JIRA credentials from environment variables"""
    base_url = os.environ.get('JIRA_BASE_URL')
    token = os.environ.get('JIRA_API_TOKEN')
    
    if not all([base_url, token]):
        raise ValueError(
            "Missing required environment variables:\n"
            "  JIRA_BASE_URL - Your on-premises JIRA server URL\n"
            "  JIRA_API_TOKEN - Your JIRA Personal Access Token (PAT)"
        )
    
    return base_url.rstrip('/'), token


def convert_html_to_markdown(html_text):
    """Convert HTML to markdown"""
    if not html_text:
        return ""
    
    if HAS_HTML2TEXT:
        # Use html2text library for better conversion
        h = html2text.HTML2Text()
        h.body_width = 0  # Don't wrap lines
        h.ignore_links = False
        h.ignore_images = False
        h.ignore_emphasis = False
        return h.handle(html_text).strip()
    else:
        # Fallback: basic HTML to text conversion
        text = html.unescape(html_text)
        # Remove HTML tags
        text = re.sub(r'<br\s*/?>', '\n', text)
        text = re.sub(r'<p>', '\n', text)
        text = re.sub(r'</p>', '\n', text)
        text = re.sub(r'<li>', '- ', text)
        text = re.sub(r'</li>', '\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        # Clean up multiple newlines
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        return text.strip()


def convert_jira_markup_to_markdown(text):
    """Convert JIRA markup to markdown (basic conversion)"""
    if not text:
        return ""
    
    # Headers
    text = re.sub(r'^h1\.\s+(.+)$', r'# \1', text, flags=re.MULTILINE)
    text = re.sub(r'^h2\.\s+(.+)$', r'## \1', text, flags=re.MULTILINE)
    text = re.sub(r'^h3\.\s+(.+)$', r'### \1', text, flags=re.MULTILINE)
    text = re.sub(r'^h4\.\s+(.+)$', r'#### \1', text, flags=re.MULTILINE)
    
    # Bold and italic
    text = re.sub(r'\*(\S.*?\S)\*', r'**\1**', text)
    text = re.sub(r'_(\S.*?\S)_', r'*\1*', text)
    
    # Code blocks
    text = re.sub(r'\{code:?([^}]*)\}(.*?)\{code\}', r'```\1\n\2\n```', text, flags=re.DOTALL)
    text = re.sub(r'\{\{(.+?)\}\}', r'`\1`', text)
    
    # Lists
    text = re.sub(r'^\*\s+', r'- ', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s+', r'1. ', text, flags=re.MULTILINE)
    
    # Links
    text = re.sub(r'\[([^\|]+)\|([^\]]+)\]', r'[\1](\2)', text)
    text = re.sub(r'\[([^\]]+)\]', r'[\1](\1)', text)
    
    return text


def fetch_jira_issue(base_url, issue_key, token):
    """Fetch JIRA issue via REST API"""
    # Handle both standard and context-path based JIRA instances
    # If base_url doesn't end with /rest, add the REST API path
    if '/rest/' in base_url:
        api_url = f"{base_url}/api/2/issue/{issue_key}"
    else:
        api_url = f"{base_url}/rest/api/2/issue/{issue_key}"
    
    # Request all fields including comments and attachments
    params = {
        'expand': 'renderedFields,names,schema,transitions,editmeta,changelog,versionedRepresentations'
    }
    
    # Use Bearer token authentication for PAT
    headers = {
        'Authorization': f'Bearer {token}'
    }
    
    try:
        response = requests.get(api_url, headers=headers, params=params, verify=True, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to fetch JIRA issue: {e}")
    except json.JSONDecodeError as e:
        raise Exception(f"Failed to parse JIRA response: {e}. Response: {response.text[:500]}")


def format_issue_as_markdown(issue_data, source_url):
    """Convert JIRA issue JSON to markdown format"""
    # Use renderedFields as fallback if fields is null
    # renderedFields has pre-rendered string values
    fields = issue_data.get('fields')
    rendered_fields = issue_data.get('renderedFields') or {}
    use_rendered = fields is None
    
    if use_rendered:
        fields = rendered_fields
    
    key = issue_data.get('key', 'UNKNOWN')
    
    # Basic fields - handle both structured and rendered formats
    summary = fields.get('summary', 'No summary')
    
    if use_rendered:
        # renderedFields has simple string values
        issue_type = fields.get('issuetype') or 'Unknown'
        status = fields.get('status') or 'Unknown'
        priority = fields.get('priority') or 'Unknown'
    else:
        # Regular fields have nested structure
        issue_type = fields.get('issuetype', {}).get('name', 'Unknown') if fields.get('issuetype') else 'Unknown'
        status = fields.get('status', {}).get('name', 'Unknown') if fields.get('status') else 'Unknown'
        priority = fields.get('priority', {}).get('name', 'Unknown') if fields.get('priority') else 'Unknown'
    
    created = fields.get('created', '')
    updated = fields.get('updated', '')
    
    # People
    if use_rendered:
        reporter_name = fields.get('reporter') or 'Unknown'
        assignee_name = fields.get('assignee') or 'Unassigned'
    else:
        reporter = fields.get('reporter', {})
        reporter_name = reporter.get('displayName', 'Unknown') if reporter else 'Unknown'
        assignee = fields.get('assignee', {})
        assignee_name = assignee.get('displayName', 'Unassigned') if assignee else 'Unassigned'
    
    # Description
    description = fields.get('description', '')
    if use_rendered:
        # Rendered fields contain HTML
        description_md = convert_html_to_markdown(description)
    else:
        # Regular fields contain JIRA markup
        description_md = convert_jira_markup_to_markdown(description)
    
    # Build markdown
    md = [
        f"# {key}: {summary}",
        "",
        "---",
        "",
        f"**Source:** {source_url}",
        f"**Retrieved:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
        "## Issue Details",
        "",
        f"- **Type:** {issue_type}",
        f"- **Status:** {status}",
        f"- **Priority:** {priority}",
        f"- **Reporter:** {reporter_name}",
        f"- **Assignee:** {assignee_name}",
        f"- **Created:** {created}",
        f"- **Updated:** {updated}",
        "",
    ]
    
    # Labels
    labels = fields.get('labels', [])
    if labels:
        md.append(f"- **Labels:** {', '.join(labels)}")
        md.append("")
    
    # Components
    components = fields.get('components', [])
    if components:
        comp_names = [c.get('name', '') for c in components]
        md.append(f"- **Components:** {', '.join(comp_names)}")
        md.append("")
    
    # Description
    if description_md:
        md.append("## Description")
        md.append("")
        md.append(description_md)
        md.append("")
    
    # Comments
    comments = fields.get('comment', {}).get('comments', [])
    if comments:
        md.append("## Comments")
        md.append("")
        for comment in comments:
            if use_rendered:
                # Rendered comments are simpler strings
                author = 'Unknown'
                created = comment.get('created', '')
                body = comment.get('body', '')
                body_md = convert_html_to_markdown(body) if body else ''
            else:
                author = comment.get('author', {}).get('displayName', 'Unknown')
                created = comment.get('created', '')
                body = comment.get('body', '')
                body_md = convert_jira_markup_to_markdown(body)
            
            md.append(f"### {author} - {created}")
            md.append("")
            md.append(body_md)
            md.append("")
    
    # Attachments
    attachments = fields.get('attachment', [])
    if attachments:
        md.append("## Attachments")
        md.append("")
        for att in attachments:
            filename = att.get('filename', 'unknown')
            size = att.get('size', 0)
            author = att.get('author', {}).get('displayName', 'Unknown')
            url = att.get('content', '#')
            md.append(f"- [{filename}]({url}) ({size} bytes, uploaded by {author})")
        md.append("")
    
    # Linked issues
    issue_links = fields.get('issuelinks', [])
    if issue_links:
        md.append("## Linked Issues")
        md.append("")
        for link in issue_links:
            link_type = link.get('type', {}).get('name', 'Related')
            
            if 'outwardIssue' in link:
                linked = link['outwardIssue']
                linked_key = linked.get('key', '')
                linked_summary = linked.get('fields', {}).get('summary', '')
                md.append(f"- **{link_type}:** {linked_key} - {linked_summary}")
            elif 'inwardIssue' in link:
                linked = link['inwardIssue']
                linked_key = linked.get('key', '')
                linked_summary = linked.get('fields', {}).get('summary', '')
                md.append(f"- **{link_type}:** {linked_key} - {linked_summary}")
        md.append("")
    
    # Subtasks
    subtasks = fields.get('subtasks', [])
    if subtasks:
        md.append("## Subtasks")
        md.append("")
        for subtask in subtasks:
            key = subtask.get('key', '')
            summary = subtask.get('fields', {}).get('summary', '')
            status = subtask.get('fields', {}).get('status', {}).get('name', '')
            md.append(f"- {key}: {summary} ({status})")
        md.append("")
    
    # Custom fields (optional - add important ones)
    # You can extend this to include specific custom fields from your JIRA instance
    
    return '\n'.join(md)


def main():
    if len(sys.argv) < 2:
        print("Usage: python fetch_jira.py <JIRA_TICKET_URL_OR_ID>", file=sys.stderr)
        print("\nExample:", file=sys.stderr)
        print("  python fetch_jira.py https://jira.company.com/browse/PROJ-123", file=sys.stderr)
        print("  python fetch_jira.py PROJ-123", file=sys.stderr)
        sys.exit(1)

    ticket_identifier = sys.argv[1]

    try:
        # Get credentials
        base_url, token = get_jira_credentials()

        # Check if the input is a full URL or just an issue key
        if ticket_identifier.startswith("http"):
            issue_key = extract_issue_key(ticket_identifier)
        else:
            issue_key = ticket_identifier

        print(f"Fetching JIRA issue: {issue_key}", file=sys.stderr)

        # Fetch issue data
        issue_data = fetch_jira_issue(base_url, issue_key, token)

        # Check for errors
        if not issue_data:
            print("Error: No data returned from JIRA API", file=sys.stderr)
            sys.exit(1)

        if 'errorMessages' in issue_data or 'errors' in issue_data:
            print(f"JIRA API Error: {json.dumps(issue_data, indent=2)}", file=sys.stderr)
            sys.exit(1)

        # Convert to markdown
        ticket_url = f"{base_url}/browse/{issue_key}"
        markdown = format_issue_as_markdown(issue_data, ticket_url)

        # Output markdown to stdout
        print(markdown)

    except Exception as e:
        import traceback
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
