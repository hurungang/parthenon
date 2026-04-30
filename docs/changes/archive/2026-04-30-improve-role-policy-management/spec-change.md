# Improve Role & Policy Management — Specification Delta

## Affected Spec Areas
- docs/master/product/roles.md
- docs/master/product/policy-statements.md
- docs/master/ux/role-management.md

## New Capabilities
- JSON view for all policy statements associated with a role
- Ability to clone/duplicate an existing role, including its policy statements

## Modified Capabilities
- Policy statement editor now uses dropdowns for resource type, effect, and actions
- Tag values are auto-populated in the statement form
- Improved add/remove statement workflow in the roles UI
- All policy statements for a role are visible in a single consolidated view

## Removed Capabilities
- None

## Spec Update Instructions
- Update product spec for roles to describe JSON view and clone role features
- Update policy statement management spec to require dropdowns for resource type, effect, and actions, and tag value auto-population
- Update UX spec for role management to reflect improved statement editor and consolidated policy view
- No changes to backend API or data model specs required
