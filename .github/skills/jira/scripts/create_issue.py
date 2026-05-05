#!/usr/bin/env python3
"""
JIRA Issue Creator - Creates issues (Epic, Story, Task) under a parent issue.

Usage:
    python create_issue.py --project AOP --type Epic --summary "My Epic" \
        --description-file desc.txt [--parent AOP-14938] [--epic-name "Short Name"]

    python create_issue.py --project AOP --type Story --summary "My Story" \
        --description "Inline description text" --parent AOP-27549

Arguments:
    --project       JIRA project key (e.g. AOP, PSST)
    --type          Issue type name: Epic | Story | Task | Sub-task | Initiative
    --summary       Full summary/title of the issue
    --description   Inline description text (JIRA wiki markup)
    --description-file  Path to a file containing the description text
    --parent        Parent issue key (initiative key for epics, epic key for stories)
    --epic-name     Short display name for Epic issues (defaults to --summary if omitted)

Environment variables required:
    JIRA_BASE_URL   On-premises JIRA base URL (e.g. https://jira.company.com/agile)
    JIRA_API_TOKEN  Personal Access Token (PAT)

Known custom fields (discovered from existing AOP issues):
    customfield_10007  Epic Name       (required for Epic type)
    customfield_12103  Initiative link (parent Initiative key for Epics)
    customfield_10014  Epic Link       (parent Epic key for Stories/Tasks)

Issue type IDs (AOP/PSST projects):
    6   = Epic
    (Story, Task, Sub-task IDs are resolved by name lookup at runtime)

Field discovery:
    Run with --inspect-issue <KEY> to print all non-null custom fields for that issue.
    This helps identify the correct parent-link field for new issue types.
"""

import os
import sys
import json
import argparse
import warnings
import requests

warnings.filterwarnings('ignore')

# Known custom field mappings (discovered empirically from AOP project)
CUSTOM_FIELDS = {
    'epic_name':       'customfield_10007',  # Short epic label shown on boards
    'initiative_link': 'customfield_12103',  # Links an Epic to its parent Initiative
    'epic_link':       'customfield_10014',  # Links a Story/Task to its parent Epic
}

# Known issue type IDs for this JIRA instance
ISSUE_TYPE_IDS = {
    'epic': '6',
}


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


def make_headers(token):
    return {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}


def resolve_issue_type_id(base_url, headers, project_key, type_name):
    """Resolve an issue type name to its ID using an existing issue as reference, or via project metadata."""
    type_lower = type_name.lower()
    if type_lower in ISSUE_TYPE_IDS:
        return ISSUE_TYPE_IDS[type_lower]

    # Try project metadata endpoint
    resp = requests.get(
        base_url + '/rest/api/2/project/' + project_key,
        headers=headers, verify=False
    )
    if resp.status_code == 200:
        data = resp.json()
        for it in data.get('issueTypes', []):
            if it.get('name', '').lower() == type_lower:
                return it['id']

    raise ValueError(
        "Could not resolve issue type '" + type_name + "' for project " + project_key + ".\n"
        "Run --inspect-issue <KEY> on an existing issue of that type to find its ID."
    )


def inspect_issue(base_url, headers, issue_key):
    """Print all non-null fields for an issue — useful for field discovery."""
    resp = requests.get(base_url + '/rest/api/2/issue/' + issue_key, headers=headers, verify=False)
    resp.raise_for_status()
    data = resp.json()
    fields = data.get('fields', {})
    print('Issue: ' + issue_key)
    print('Type:  ' + fields.get('issuetype', {}).get('name', '?'))
    print('Project: ' + fields.get('project', {}).get('key', '?'))
    print('\nNon-null custom fields:')
    for k, v in sorted(fields.items()):
        if k.startswith('customfield') and v is not None:
            print('  ' + k + ': ' + str(v)[:120])


def create_issue(base_url, headers, project_key, type_name, summary, description, parent_key=None, epic_name=None):
    """
    Create a JIRA issue.

    Parent linking behaviour by type:
      Epic       -> parent_key sets customfield_12103 (Initiative link)
      Story/Task -> parent_key sets customfield_10014 (Epic link)
    """
    issuetype_id = resolve_issue_type_id(base_url, headers, project_key, type_name)
    type_lower = type_name.lower()

    fields = {
        'project':     {'key': project_key},
        'summary':     summary,
        'issuetype':   {'id': issuetype_id},
        'description': description,
    }

    if type_lower == 'epic':
        fields[CUSTOM_FIELDS['epic_name']] = epic_name or summary
        if parent_key:
            fields[CUSTOM_FIELDS['initiative_link']] = parent_key
    elif type_lower in ('story', 'task', 'sub-task', 'subtask'):
        if parent_key:
            fields[CUSTOM_FIELDS['epic_link']] = parent_key
    else:
        # For unknown types, attempt initiative link if parent looks like an initiative
        if parent_key:
            fields[CUSTOM_FIELDS['initiative_link']] = parent_key

    payload = {'fields': fields}

    log_fields = {k: v for k, v in fields.items() if k != 'description'}
    print('Creating ' + type_name + ' in ' + project_key + ':')
    print(json.dumps(log_fields, indent=2))

    resp = requests.post(base_url + '/rest/api/2/issue', headers=headers, json=payload, verify=False)

    if resp.status_code not in (200, 201):
        print('\nError ' + str(resp.status_code) + ': ' + resp.text)
        resp.raise_for_status()

    result = resp.json()
    new_key = result.get('key')
    print('\nCreated: ' + new_key)
    print('URL: ' + base_url + '/browse/' + new_key)
    return new_key


def main():
    parser = argparse.ArgumentParser(description='Create a JIRA issue')
    parser.add_argument('--project',          required=False, help='JIRA project key (e.g. AOP)')
    parser.add_argument('--type',             required=False, default='Epic', help='Issue type (Epic, Story, Task)')
    parser.add_argument('--summary',          required=False, help='Issue summary/title')
    parser.add_argument('--description',      required=False, help='Inline description (JIRA wiki markup)')
    parser.add_argument('--description-file', required=False, help='Path to file containing description')
    parser.add_argument('--parent',           required=False, help='Parent issue key')
    parser.add_argument('--epic-name',        required=False, help='Short epic name for board display (Epic type only)')
    parser.add_argument('--inspect-issue',    required=False, help='Print all fields for this issue key and exit')

    args = parser.parse_args()

    base_url, token = get_jira_credentials()
    headers = make_headers(token)

    if args.inspect_issue:
        inspect_issue(base_url, headers, args.inspect_issue)
        return

    if not args.project or not args.summary:
        parser.error('--project and --summary are required')

    if args.description_file:
        with open(args.description_file, 'r', encoding='utf-8') as f:
            description = f.read()
    else:
        description = args.description or ''

    create_issue(
        base_url, headers,
        project_key=args.project,
        type_name=args.type,
        summary=args.summary,
        description=description,
        parent_key=args.parent,
        epic_name=args.epic_name,
    )


if __name__ == '__main__':
    main()
