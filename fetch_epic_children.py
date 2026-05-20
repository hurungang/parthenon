#!/usr/bin/env python3
"""Fetch child stories for a list of JIRA Epics using Epic Link"""
import os
import sys
import requests

EPICS = [
    "PSST-18811", "PSST-18810", "PSST-18627", "PSST-18384",
    "PSST-16659", "PSST-16242", "PSST-16052", "PSST-15902",
    "PSST-12731", "PSST-13021", "PSST-12938", "PSST-12935",
    "PSST-12923", "PSST-12792", "PSST-12859", "PSST-16175",
    "PSST-12997", "PSST-18369"
]

def get_children(base_url, token, epic_key):
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    # Try Epic Link (customfield_10014) first, then parent
    jql = f'"Epic Link" = {epic_key} ORDER BY created ASC'
    params = {
        'jql': jql,
        'maxResults': 100,
        'fields': 'key,summary,status,issuetype'
    }
    resp = requests.get(f'{base_url}/rest/api/2/search', headers=headers, params=params, verify=True, timeout=30)
    if resp.status_code == 400:
        # Try alternate JQL
        jql2 = f'parent = {epic_key} ORDER BY created ASC'
        params['jql'] = jql2
        resp = requests.get(f'{base_url}/rest/api/2/search', headers=headers, params=params, verify=True, timeout=30)
    resp.raise_for_status()
    return resp.json()

def main():
    base_url = os.environ.get('JIRA_BASE_URL', '').rstrip('/')
    token = os.environ.get('JIRA_API_TOKEN', '')
    if not base_url or not token:
        print('ERROR: JIRA_BASE_URL or JIRA_API_TOKEN not set')
        sys.exit(1)

    for epic_key in EPICS:
        print(f"\n=== CHILDREN OF {epic_key} ===")
        try:
            data = get_children(base_url, token, epic_key)
            issues = data.get('issues', [])
            total = data.get('total', 0)
            print(f"Total: {total}")
            if issues:
                print(f"{'Key':<15} {'Status':<20} Summary")
                print("-" * 80)
                for issue in issues:
                    key = issue['key']
                    summary = issue['fields']['summary']
                    status = issue['fields']['status']['name']
                    print(f"{key:<15} {status:<20} {summary}")
            else:
                print("(no child issues)")
        except Exception as e:
            print(f"ERROR fetching children: {e}")

if __name__ == '__main__':
    main()
