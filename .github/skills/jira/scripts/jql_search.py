#!/usr/bin/env python3
"""
JIRA JQL Search - Run arbitrary JQL queries against JIRA
"""
import os
import sys
import json
import requests


def get_jira_credentials():
    base_url = os.environ.get('JIRA_BASE_URL')
    token = os.environ.get('JIRA_API_TOKEN')
    if not all([base_url, token]):
        raise ValueError(
            "Missing required environment variables:\n"
            "  JIRA_BASE_URL - Your on-premises JIRA server URL\n"
            "  JIRA_API_TOKEN - Your JIRA Personal Access Token (PAT)"
        )
    return base_url.rstrip('/'), token


def jql_search(jql, fields='key,summary,status,fixVersions,issuetype', max_results=100):
    base_url, token = get_jira_credentials()
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    params = {
        'jql': jql,
        'maxResults': max_results,
        'fields': fields
    }
    resp = requests.get(
        f'{base_url}/rest/api/2/search',
        headers=headers,
        params=params,
        verify=True,
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: jql_search.py \"<JQL>\"")
        sys.exit(1)

    jql = sys.argv[1]
    data = jql_search(jql)
    total = data.get('total', 0)
    issues = data.get('issues', [])

    print(f"Total results: {total}")
    print()
    print(f"{'Key':<12} {'Status':<20} {'Fix Version':<15} Summary")
    print("-" * 100)
    for i in issues:
        key = i['key']
        summary = i['fields']['summary']
        status = i['fields']['status']['name']
        fix_versions = ', '.join(v['name'] for v in i['fields'].get('fixVersions', []))
        print(f"{key:<12} {status:<20} {fix_versions:<15} {summary}")
