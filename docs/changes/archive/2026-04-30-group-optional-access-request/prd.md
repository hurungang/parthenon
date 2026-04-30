# Epic Overview

Currently, users without permission to request access cannot view or select any group, blocking them from submitting access requests. This change enables users to request access without specifying a group, allowing administrators to review such requests and assign the appropriate group during approval. This improves the inclusivity and efficiency of the access request process, ensuring no legitimate user is blocked from onboarding due to missing group permissions.

# Business Goals

- Increase successful access requests from users with no group permissions by 100%
- Reduce support tickets related to access request failures by at least 50%
- Ensure all access requests are reviewable and actionable by administrators
- Improve onboarding satisfaction scores for new users by 20%

# Users & Personas

- **New Users**: Individuals joining the platform who lack initial group permissions
- **Administrators**: Staff responsible for reviewing and approving access requests
- **Support Team**: Handles escalations when users are blocked from requesting access

# User Stories

- As a new user without group permissions, I want to request access without selecting a group, so that I can start the onboarding process without barriers.
- As an administrator, I want to see access requests without groups and assign the correct group during approval, so that users are placed appropriately.
- As a support agent, I want fewer tickets about access request failures, so that I can focus on more complex issues.

# Acceptance Criteria

- Users without group permissions can submit access requests without selecting a group
- The access request form allows submission with no group selected
- Administrators can view and filter access requests that have no group assigned
- Administrators can assign a group to the request during the approval process
- After approval, the user is added to the assigned group and notified
- Error messages are clear if required information is missing
- The parent access request table refreshes automatically after admin actions (approve/assign group)
- System logs all actions for audit purposes

# Out of Scope

- Changes to group creation or management workflows
- Automated group assignment based on user attributes
- Modifications to admin notification or escalation processes

# Dependencies & Constraints

- Relies on existing admin review and approval workflows
- Must comply with current RBAC and audit requirements
- No changes to group visibility rules for users without permissions