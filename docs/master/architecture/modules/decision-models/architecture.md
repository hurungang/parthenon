# Decision Model Providers Architecture

## Overview

Decision Model Providers generalise the former single "System One Provider" into multiple vendors, each with its own catalogue of decision models. The design mirrors the LLM [Model Configuration](../model-config.md) pattern: administrators manage providers and their enabled models centrally in Control Center; each Decision Tool carries a reference to one enabled model, resolved at execution time. Control Center is the only DB-connected service — Agent Runtime and Communication Hub never see credentials or query the database, and decision execution always routes through Control Center internal endpoints over signed tenant headers.

## Component Architecture

```mermaid
flowchart LR
    subgraph CC["Control Center (sole DB owner)"]
        PCFG["Decision Provider Config Service<br/>(multi-provider CRUD, encrypted credentials)"]
        MMGMT["Decision Model Catalogue Service<br/>(per-model enable/disable)"]
        DE["Decision Engine<br/>(resolves per-tool selected model)"]
        GUARD["Guardrail & Budget Enforcement"]
        USAGE["Usage Metering & Spend Reporting"]
        DB[("PostgreSQL")]
    end
    ADMIN["Platform Admin"]
    AR["Agent Runtime"]
    CH["Communication Hub<br/>(MCP decision____ tools)"]
    V["Decision Vendors"]

    ADMIN -->|configure providers & models| PCFG
    ADMIN -->|enable/disable models| MMGMT
    AR -->|"decision____tool"| CH
    CH -->|internal /decision/execute| DE
    DE --> GUARD
    GUARD --> USAGE
    DE --> PCFG
    PCFG --> V
    PCFG --> DB
    MMGMT --> DB
```

## Key Properties

- **Multi-provider, multi-model** — one provider entity per vendor; each provider holds an encrypted credential (write-only, never returned on read) and a vendor catalogue with per-model enable/disable.
- **Per-tool model selection** — each Decision Tool stores a reference to one enabled Decision Model; deletion of a provider/model is blocked while referenced by any tool.
- **Full guardrail/budget coverage** — decision evaluations pass the same pre-call checks as regular agent model calls. Decision-provider guardrails reuse `model_guardrail_configurations` with a `config_source` discriminator (`decision_provider`) plus a `decision_provider_id` FK, enforced by the decision pre-call path in Control Center before any vendor call.
- **Usage & spend reporting** — decision model usage is metered into the same pipeline as regular LLM usage.
- **Auditability** — execution responses and logs include provider/model identity.
- **Segregation respected** — configuration and credential decryption are CC-only; agents receive only structured decision results.

## Execution Flow

```mermaid
sequenceDiagram
    participant A as Agent (Agent Runtime)
    participant CH as Communication Hub
    participant CC as Control Center
    participant G as Guardrail/Budget (CC)
    participant V as Decision Vendor

    A->>CH: call decision____tool
    CH->>CC: internal /decision/execute (signed tenant headers)
    CC->>CC: resolve tool → selected enabled model
    CC->>G: pre-call guardrail + budget/spend check
    alt blocked
        CC-->>CH: blocked result + audit trail
        CH-->>A: tool error outcome
    else allowed
        CC->>CC: decrypt provider credential (call time only)
        CC->>V: evaluate (questions payload, selected model)
        V-->>CC: decision result
        CC->>G: record usage against budget
        CC-->>CH: structured result + provider/model identity
        CH-->>A: decision result
    end
```

## Data Model (business entities)

```mermaid
erDiagram
    DECISION_PROVIDER ||--o{ DECISION_MODEL : "offers"
    DECISION_TOOL }o--|| DECISION_MODEL : "selects one enabled model"
    DECISION_PROVIDER ||--o{ MODEL_GUARDRAIL_CONFIGURATION : "guardrails (config_source = decision_provider)"
```

- **Decision Provider** — vendor configuration (provider type, endpoint, encrypted credential). Migrated from the former single-provider configuration via an idempotent one-time Alembic migration.
- **Decision Model** — a model within a provider's catalogue; can be individually enabled or disabled.
- **Decision Tool** — references exactly one enabled decision model; referential integrity prevents deleting models still in use.
- **Guardrail configuration** — shared `model_guardrail_configurations` store, discriminated by `config_source = decision_provider` and bound to the owning provider.
