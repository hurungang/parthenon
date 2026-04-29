# MCP Hub — Entities

```mermaid
erDiagram
    McpServer {
        uuid id
        string name
        string slug
        string base_url
        enum status
    }
    McpSession {
        uuid id
        uuid server_id
        string name
        enum auth_type
        string identity_subject
        boolean is_active
    }
    McpTool {
        uuid id
        uuid server_id
        string name
        string original_name
        boolean is_active
    }
    ToolPermission {
        uuid id
        uuid tool_id
        uuid role_id
    }

    McpServer ||--o{ McpSession : "has"
    McpServer ||--o{ McpTool : "provides"
    McpTool ||--o{ ToolPermission : "governed by"
```

**Source**: `backend/app/db/models/mcp_hub.py`

| Entity | Description |
|--------|-------------|
| **McpServer** | A registered external tool server with a unique slug; its status (active/inactive) is tracked by the platform. |
| **McpSession** | A named connection configuration on a server that carries a specific identity or credential binding for outbound calls. |
| **McpTool** | A capability synced from an external server; namespaced under the server's slug to ensure platform-wide uniqueness. |
| **ToolPermission** | Grants a Role or Identity the right to invoke a specific tool. |
