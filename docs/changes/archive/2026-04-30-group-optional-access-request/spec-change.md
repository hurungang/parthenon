# Affected Spec Areas

- Access Request Flow (User Onboarding)
- Admin Access Request Review
- Group Assignment during Access Approval

# New Capabilities

- Users can submit access requests without selecting a group
- Administrators can assign a group to access requests that have no group specified

# Modified Capabilities

**Before:**
- Users must select a group when requesting access; users without group permissions cannot submit requests
- Administrators only review requests with a group already assigned

**After:**
- Users can submit access requests without group selection if they lack permissions
- Administrators can review and assign groups to such requests during approval

# Removed Capabilities

- None

# Spec Update Instructions

- Update "Access Request Flow" in master product spec to allow group-optional requests
- Update "Admin Access Request Review" to include handling and assignment of groupless requests
- Update acceptance criteria in master spec to reflect new user and admin flows
- Ensure audit and compliance requirements are documented for admin group assignment actions