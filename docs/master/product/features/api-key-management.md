# API Key Management

## Overview
API Key Management enables Platform Administrators to create, view, and revoke API keys that allow third-party AI agents — such as Claude Code, Cursor, or custom-built agents — to securely connect to Parthenon's MCP Hub. Each API key is bound to an existing agent identity and agent role, inheriting the role's full permission set for skill and tool access. Keys are hashed at rest in Control Center's database and never retrievable after creation, ensuring that clear-text credentials cannot be leaked through the platform.

## Who Uses It
- Platform Administrators: Create and manage API keys for third-party integrations, bind keys to agent identities and roles, view and revoke keys as needed
- Security Administrators: Audit API key usage and lifecycle events through the platform audit log
- Third-party Agent Developers: Receive API keys from Platform Administrators and configure their agents to authenticate to Parthenon

## What It Does
- Provides a dedicated API Keys management page in the Web UI, accessible under the Agents or Integrations section
- Allows Platform Administrators to create a new API key by selecting an existing agent identity and agent role from dropdowns
- Displays the clear-text key once at creation time for the administrator to copy; the key value is never shown again
- Stores API keys in hashed form, making the clear-text key unrecoverable after the initial display
- Lists all API keys with columns for name or label, bound agent identity, bound agent role, creation date, last used date, and status (active or revoked)
- Supports filtering the API key list by status to quickly find active or revoked keys
- Allows Platform Administrators to revoke an API key with a confirmation dialog; revoked keys immediately become unusable
- Retains revoked keys in the list with a "revoked" status indicator for audit trail purposes
- Records API key creation and revocation events in the platform audit log
- Logs API key usage events (authentication) with the key identifier and bound identity — never the key value itself
- Automatically refreshes the key list after create or revoke operations without requiring a manual page reload

## Key Concepts
- **API Key**: A bearer credential issued to a third-party agent for MCP Hub authentication. The clear-text value is shown only once at creation and is never stored or retrievable afterward.
- **Key Binding**: Each API key is bound to a specific agent identity and agent role at creation time. The key inherits the complete permission set of the bound role.
- **Hashed Storage**: API keys are stored as cryptographic hashes in Control Center's database. Authentication involves hashing the presented key and comparing against the stored hash.
- **Revocation**: The permanent deactivation of an API key. Once revoked, the key cannot be re-activated and immediately fails all authentication attempts. Revoked keys remain visible in the UI for audit purposes.
- **One Key Per Identity-Role Pair**: Only one active API key is permitted per combination of agent identity and agent role.

## Acceptance Criteria
### Key Creation
- Platform Administrator can create a new API key by selecting an existing agent identity and agent role from dropdowns
- The clear-text API key is displayed once at creation for the administrator to copy; the value cannot be retrieved afterward
- The created API key immediately appears in the API keys list with "active" status
- The API key list automatically refreshes after creation — no manual page reload required

### Key Viewing and Filtering
- Platform Administrator can view a list of all API keys with columns: name or label, bound agent identity, bound agent role, creation date, last used date, and status
- Platform Administrator can filter the API key list by status (active or revoked)
- The key value is never displayed in the list or any other UI after the initial creation screen

### Key Revocation
- Platform Administrator can revoke an API key through a confirmation dialog
- Revoked API key immediately becomes unusable for authentication
- After revocation, the key remains in the list with status "revoked" and cannot be re-activated
- The API key list automatically refreshes after revocation — no manual page reload required

### Audit and Logging
- API key creation and revocation events are recorded in the audit log
- API key usage (authentication events) is logged with the key identifier and bound identity, not the key value
- Failed authentication attempts with invalid or revoked keys are logged for security monitoring

## Out of Scope
- API key scoping beyond role-based permissions — keys inherit the full permission set of the bound role
- API key expiration dates or automatic rotation — keys are valid until manually revoked
- Multiple active API keys per agent identity-role pair — only one active key per combination
- Self-service API key generation by external developers — keys can only be created by Platform Administrators
- Client SDKs or libraries for third-party agent developers — they interact via standard MCP protocol
- Rate limiting or quota enforcement on tool calls made via API keys, beyond basic authentication rate limiting

## Dependencies & Constraints
- Requires existing agent identities to be provisioned before an API key can be created for them
- Requires existing agent roles with permission sets to be defined before binding
- API key validation requires Communication Hub to call Control Center's internal API over mTLS-secured channels
- Rate limiting is applied to authentication attempts to prevent brute-force attacks
- External agents must support the MCP protocol with Bearer token or query parameter authentication
