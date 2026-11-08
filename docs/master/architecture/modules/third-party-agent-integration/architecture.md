# Third-Party Agent Integration Architecture

Third parties consume an agent type's *input interface* through the Communication Hub governed surface using **client credentials** — a primitive distinct from API keys. A client is bound to one agent type and is **not an identity**: it yields no agent identity token, cannot reach the MCP hub, and cannot impersonate an agent. The invoked agent type always runs with its own identity + role as configured.

## Client Model and Credential Types

```mermaid
flowchart LR
    subgraph EXT["Third Party"]
        BE["Consumer Backend<br/>secret client (server-to-server)"]
        BROWSER["Browser Widget / SDK<br/>publishable client"]
    end

    subgraph CH["Communication Hub (governed surface)"]
        GW["Integration Gateway<br/>chat + typed request/response"]
        ENF["Origin Allowlist + Rate Limit"]
        AUTH["Client Credential Auth"]
    end

    subgraph CC["Control Center"]
        MGMT["Client Management<br/>create / list / revoke"]
        RES["Client Resolution<br/>client → agent type + config"]
    end

    AR["Agent Runtime<br/>agent type runs as itself<br/>(own identity + role)"]
    ADMIN["Tenant Administrator"]

    BE -->|"secret credential"| GW
    BROWSER -->|"publishable credential"| GW
    GW --> ENF --> AUTH
    AUTH -->|"mTLS · hashed credential"| RES
    RES --> MGMT
    AUTH -->|"resolved, no identity token"| GW
    GW -->|"delegate input"| AR
    ADMIN -->|"manage clients"| MGMT
```

## Key Properties

- **Two credential types** — `secret` (server-to-server, may carry an optional end-user token held CH-side) and `publishable` (browser-safe; protected by per-client origin allowlist + rate limit instead of secrecy).
- **No identity forwarding** — a client credential resolves to `(client → agent type + config)` only; no agent identity token is issued or forwarded on any client path.
- **Governed surface only** — all third-party traffic enters through the Communication Hub; client lifecycle (create / list / revoke) is owned by Control Center and tenant-scoped.
