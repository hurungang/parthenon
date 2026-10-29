# Token Refresh Service

## Overview

The Token Refresh Service is a background service that keeps agent access tokens valid without requiring administrator intervention. It monitors token expiry in the Token Store and proactively refreshes access tokens against the `ai_agents` realm using stored refresh tokens, before the access token expires. If a refresh token has itself expired, the service marks the identity as requiring re-authentication and surfaces the status in the management UI.

## Component Architecture

```mermaid
flowchart LR
    TRS[Token Refresh Service]

    subgraph TS[Token Store]
        AT[Access Token]
        RT[Refresh Token]
        Exp[Expiry Metadata]
    end

    IdP[ai_agents Realm]
    AR[Agent Runtime]
    UI[Identity Management UI]

    TRS -->|poll expiry| Exp
    TRS -->|refresh grant| IdP
    IdP -->|new access token| TRS
    TRS -->|update| AT
    AR -->|fetch token on session start| AT
    TRS -.->|update token status| UI
```

## Responsibilities

- **Expiry monitoring** — Polls token expiry metadata at a configured cadence; flags tokens that are expiring soon
- **Proactive refresh** — Issues OAuth 2.0 refresh token grants against the `ai_agents` realm before the access token expires
- **Token Store update** — Writes the new encrypted access token back to the Token Store; the expiry timestamp is updated accordingly
- **Failure handling** — If a refresh grant fails (e.g. the refresh token is expired or revoked), the identity status is updated to `expired`; no further refresh is attempted until an administrator re-authenticates
- **Status surfacing** — Token status (`valid` / `expiring_soon` / `expired`) is surfaced in the Identity Management UI, enabling admins to act before sessions fail

## Token Lifecycle States

| State | Meaning | Action |
|---|---|---|
| **valid** | Access token is current; no action needed | Refresh Service monitors expiry |
| **expiring_soon** | Access token is within the refresh window | Refresh Service issues refresh grant |
| **expired** | Refresh token is expired or revoked | Admin must re-authenticate via OAuth sign-in |

## Expiry Classification (Token Health Service)

The **Token Health Service** (Control Center) is the single owner of token expiry state. It computes an expiry classification per identity token and per MCP session directly from the token metadata the Token Store already holds — Control Center remains the only database-connected service, and no new deployable is introduced.

| State | Meaning | Downstream effect |
|---|---|---|
| `healthy` | Token valid, outside the 7-day window | Execution preflight proceeds |
| `expiring-within-7-days` | Token valid today but expiring soon | Execution proceeds **with a warning**; surfaced on dashboard + topology |
| `expired` | Token (or refresh token) no longer usable | Execution **blocked** at the Communication Hub preflight gate |

```mermaid
flowchart LR
    subgraph CC["Control Center (sole DB reader)"]
        THS[Token Health Service<br/>expired / expiring-7d / healthy]
        DB[("Token metadata")]
    end
    CH["Communication Hub<br/>execution preflight gate"]
    FE["Dashboard + Topology<br/>health cards and badges"]

    THS --> DB
    CH -->|preflight check| THS
    FE -->|token health API| THS
    THS -->|drive refresh| TRS[Token Refresh Service]
```

## Re-Authentication

When a refresh token is expired, an administrator re-authenticates by completing an OAuth sign-in to the agent user account in the `ai_agents` realm. The Platform API exchanges the authorization code for a new access and refresh token pair and stores them in the Token Store. The Token Refresh Service resumes normal monitoring once a valid refresh token is available. See [Identity](identity.md) for the dual-realm topology.
