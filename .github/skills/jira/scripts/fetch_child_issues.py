#!/usr/bin/env python3
"""
Fetch all child issues of a JIRA initiative or epic
"""

import os
import sys
import json
import requests

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


def search_child_issues(base_url, parent_key, token, max_results=100):
    """Search for all child issues (epics, stories, etc.) under a parent issue"""
    # Use JQL to find all issues with parent
    jql = f'"Parent Link" = {parent_key}'
    
    api_url = f"{base_url}/rest/api/2/search"
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    params = {
        'jql': jql,
        'maxResults': max_results,
        'fields': 'key,summary,status,issuetype,assignee,created,updated,description,customfield_10014'  # customfield_10014 is often Epic Name
    }
    
    try:
        response = requests.get(api_url, headers=headers, params=params, verify=True, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to search JIRA issues: {e}")


def format_output(results, output_format='text'):
    """Format the search results"""
    issues = results.get('issues', [])
    total = results.get('total', 0)
    
    if output_format == 'json':
        return json.dumps(results, indent=2)
    
    # Text format
    output = []
    output.append(f"Found {len(issues)} of {total} child issues:\n")
    
    for issue in issues:
        key = issue['key']
        fields = issue['fields']
        summary = fields.get('summary', 'No summary')
        issue_type = fields.get('issuetype', {}).get('name', 'Unknown')
        status = fields.get('status', {}).get('name', 'Unknown')
        assignee = fields.get('assignee')
        assignee_name = assignee.get('displayName', 'Unassigned') if assignee else 'Unassigned'
        
        output.append(f"- {key}: [{issue_type}] {summary}")
        output.append(f"  Status: {status} | Assignee: {assignee_name}")
    
    return '\n'.join(output)


def save_to_cache(parent_key, results, cache_dir='workspace/_cache'):
    """Save results to cache directory"""
    os.makedirs(cache_dir, exist_ok=True)
    
    cache_file = os.path.join(cache_dir, f'jira-{parent_key.lower()}-children.json')
    
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"Results cached to: {cache_file}", file=sys.stderr)


def main():
    if len(sys.argv) < 2:
        print("Usage: python fetch_child_issues.py <PARENT_ISSUE_KEY> [--json] [--cache]", file=sys.stderr)
        print("\nExamples:", file=sys.stderr)
        print("  python fetch_child_issues.py AOP-26060", file=sys.stderr)
        print("  python fetch_child_issues.py AOP-26060 --json", file=sys.stderr)
        print("  python fetch_child_issues.py AOP-26060 --cache", file=sys.stderr)
        sys.exit(1)

    parent_key = sys.argv[1]
    output_format = 'json' if '--json' in sys.argv else 'text'
    should_cache = '--cache' in sys.argv

    try:
        base_url, token = get_jira_credentials()
        print(f"Searching for child issues of {parent_key}...", file=sys.stderr)
        
        results = search_child_issues(base_url, parent_key, token)
        
        # Save to cache if requested
        if should_cache:
            save_to_cache(parent_key, results)
        
        # Output results
        print(format_output(results, output_format))
        
    except Exception as e:
        import traceback
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
