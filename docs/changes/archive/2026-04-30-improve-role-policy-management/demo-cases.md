# Demo Cases for improve-role-policy-management

This document lists representative E2E test cases that demonstrate each feature of the change.

## 1. Resource Type Dropdown

Shows admin selecting resource type from dropdown instead of free-text field.

```grep
Describe AddStatementDialog > Add Statement dialog opens with resource type dropdown
```

## 2. Effect Dropdown

Shows admin selecting Allow/Deny from dropdown in the Add Statement dialog.

```grep
Describe AddStatementDialog > Add Statement dialog opens with resource type dropdown
```

## 3. Actions Multi-select

Shows admin selecting one or more actions (read, write, execute, etc.) for the chosen resource type.

```grep
Describe AddStatementDialog > Add Statement dialog opens with resource type dropdown
```

## 4. Tag Value Auto-population

Shows allowed values auto-populated in the tag value field when a tag key is selected.

```grep
Describe AddStatementDialog > Add Statement dialog opens with resource type dropdown
```

## 5. JSON View & Copy

Shows admin opening the JSON view modal for a role and copying the formatted policy JSON.

```grep
Describe JSONViewModal > View JSON button opens modal with formatted JSON
```

## 6. Role Cloning

Shows admin cloning a role with a pre-filled name and the new role appearing in the list.

```grep
Describe CloneRoleDialog > Clone dialog pre-fills source role name with Copy prefix
```
