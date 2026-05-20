# Passthrough Sessions — Data Model Changes

## 1. New Entities

None. This change introduces no new entities.

---

## 2. Modified Entities

### McpSession — add `passthrough` auth type

The `auth_type` field is extended with a new value: `passthrough`. When a session uses the passthrough auth type, the platform forwards the executing agent's identity directly to the MCP server instead of presenting stored credentials. No credential storage is required for passthrough sessions.

```mermaid
erDiagram
    McpSession {
        "Session ID"
        "Server"
        "Name"
        "Description"
        "Auth Type"
        "Credentials"
        "Active"
        "Created"
        "Updated"
    }
    McpServer {
        "Server ID"
        "Name"
        "Base URL"
        "Status"
        "Created"
        "Updated"
    }

    McpServer ||--o{ McpSession : "has"
```

**Changed attribute:**

| Attribute | Before | After |
|-----------|--------|-------|
| Auth Type | `api_key`, `bearer_token`, `basic_auth`, `oauth2`, `none` | adds `passthrough` |

**Business rules for the `passthrough` auth type:**
- No credentials are stored on the session; any stored credential fields are ignored at runtime.
- The executing agent's identity is resolved at call time and forwarded to the MCP server.
- No credential configuration is required when creating or editing a passthrough session.

---

## 3. Removed Entities/Fields

None. All existing auth types and session attributes remain unchanged.
