# Improve Role & Policy Management — Product Requirements Document (PRD)

## Epic Overview
System administrators currently face friction and errors when managing role-based access policies due to limited UI controls and missing features. Policy statement editing is cumbersome, dropdowns are missing for key fields, tag values do not populate, and there is no way to view or clone roles efficiently. This epic aims to streamline role and policy management, reduce admin errors, and improve security posture by making policy editing more intuitive and robust.

## Business Goals
- Reduce time required to create or update a role by 50%
- Decrease admin errors in policy statement creation by 75%
- Ensure 100% of policy statements use valid resource types, effects, and actions
- Enable administrators to export or review policies in JSON format for audits
- Increase adoption of role cloning for faster onboarding of new roles

## Users & Personas
- **System Administrators**: Responsible for managing user roles and access policies
- **Security Administrators**: Oversee compliance and audit of access controls

## User Stories
- As a system administrator, I want to add or remove policy statements for a role in one place, so that I can manage access efficiently.
- As an admin, I want to select resource types, effects, and actions from dropdowns, so that I avoid manual entry errors.
- As an admin, I want tag values to auto-populate in the statement form, so that I can assign policies accurately.
- As an admin, I want to view all policy statements for a role in JSON format, so that I can document or audit access controls.
- As an admin, I want to clone an existing role, so that I can quickly create similar roles with minor changes.

## Acceptance Criteria
- Admin can add new policy statements to a role using dropdowns for resource type, effect, and actions
- Tag values are auto-populated and selectable in the statement form
- Admin can remove policy statements from a role in the same interface
- All policy statements for a role are visible in a single view
- Admin can switch to a JSON view of all policy statements for a role
- Admin can clone an existing role, including all policy statements, and edit the new role before saving
- After adding, editing, or deleting a statement, the parent table/view refreshes automatically without manual reload
- Validation errors are shown for invalid or duplicate entries
- System enforces required fields and prevents saving incomplete statements

## Out of Scope
- Changes to backend API or database schema
- Bulk import/export of roles or policies
- Advanced policy simulation or testing tools

## Dependencies & Constraints
- Relies on up-to-date list of resource types, effects, and actions
- Must maintain compatibility with existing roles and policies
- Requires coordination with security and compliance teams for audit requirements
