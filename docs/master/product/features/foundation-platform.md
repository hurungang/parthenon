# Foundation Platform

## Overview
The Foundation Platform provides the core identity, access, and user experience layer for Parthenon. It enables secure onboarding, role-based access control, and a unified Web UI shell for all users and agents, ensuring that only authorized actions are performed and that setup is streamlined for enterprise environments.

## Who Uses It

- Enterprise Admins: Configure roles, permissions, user tags, user groups, and identity provider integration
- User Group Owners: Approve or reject user group membership requests and manage group membership
- Business Users: Access the Web UI to interact with agents and workflows; request access to user groups as needed
- Compliance Auditors: Verify access controls and user activity

## What It Does
- Supports OIDC-based authentication and role mapping for users and agents
- Provides a setup wizard for initial platform configuration
- Manages user, agent, and hybrid roles with granular permissions
- Enables user tag management for flexible access control
- Allows policy-based user role authoring with fine-grained conditions
- Supports user group creation, assignment of group owners, and binding to IdP claims for automatic group assignment
- Provides user caching and direct user role assignment by admins
- Delivers a unified Web UI shell for all platform features
- Enables a self-service user group request and approval flow for users not auto-assigned to groups

## Key Concepts
- **OIDC Integration**: Connecting to an external identity provider for authentication
- **Role Management**: Assigning and managing user and agent roles
- **Permission Enforcement**: Controlling access to features and actions
- **Setup Wizard**: Guided onboarding for initial configuration
- **Web UI Shell**: The main user interface for all platform operations
- **User Tag**: A reusable label that categorizes users or resources and can be used as a condition in access policies
- **User Policy Statement**: A business rule defining what actions a user or group can perform on which resources, optionally filtered by user tags
- **User Group**: A collection of users managed together, which can be assigned roles and policies and linked to IdP claims for automatic membership
- **IdP Claim Mapping**: The process of binding identity provider attributes (such as group claims) to platform user groups for automatic assignment
- **User Group Request**: A self-service flow where users can request to join user groups, subject to approval by group owners

## Acceptance Criteria
- Users and agents authenticate via OIDC and are assigned correct roles
- Permissions are enforced for all actions in the Web UI
- Setup wizard guides through initial configuration and identity provider setup
- Admins can manage roles, permissions, user tags, user groups, and user policies from the UI
- User tags can be created, updated, and deleted by admins
- Admins can author user policies with conditions based on user tags
- Admins can create user groups, assign group owners, and bind groups to IdP claims for automatic assignment
- All users who have authenticated are visible in a user list with their roles and group memberships
- Admins can assign or remove direct user roles and group memberships for any user
- Users not auto-assigned to groups can request access to available user groups, providing justification
- User group owners can approve or reject membership requests, and users are notified of outcomes
- Users can track the status of their group requests (pending, approved, rejected) from their dashboard
- All access and permission changes, group requests, and approvals are auditable
