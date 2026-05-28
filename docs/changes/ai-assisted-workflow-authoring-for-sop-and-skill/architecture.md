# Architecture: AI-Assisted Workflow Authoring for SOP and Skill

## Changed Components

This change updates existing authoring interactions to use workflow terminology and preserves service boundaries where the agent runtime handles authoring while Control Center remains the only database-facing service.
It also adds a system configuration entry point for selecting the workflow generation model, reusing the existing model configuration surface so administrators can control the generator used by Skill and SOP authoring.
Default SOP (renamed from Primary SOP) is now configurable for every agent input type, and two components — PlanGenerationService and RuntimeInstructionBuilder — are updated to apply system-instruction-aware SOP selection.

```mermaid
flowchart LR
    UI[Workflow Authoring UI - Changed]
    CFG[System Configuration Page - New]
    TERM[Workflow Terminology in Authoring - Changed]
    GEN[Generate Workflow Action - Changed]
    PREV[Workflow Preview Dialog - Changed]
    DSOP[Default SOP Configuration - Changed]
    PGS[PlanGenerationService - Changed]
    RIB[RuntimeInstructionBuilder - Changed]
    CH[Communication Hub Routing - Changed]
    AR[Agent Runtime Authoring Path - Changed]
    CC[Control Center Policy and Context - Integration Change]
    DB[(Platform DB via Control Center only)]

    UI --> TERM
    UI --> GEN
    UI --> PREV
    UI --> CFG
    UI --> DSOP
    GEN --> CH
    PREV --> CH
    DSOP --> PGS
    DSOP --> RIB
    CFG --> GEN
    CH --> AR
    AR --> PGS
    AR --> RIB
    AR --> CH
    CH --> CC
    CC --> DB
```

## New Components

New workflow-focused authoring capabilities are introduced in the runtime path to generate and preview workflow drafts for both skill and SOP contexts.
The design also introduces a system configuration surface for selecting the generation model, and two new services that implement system-instruction-aware SOP routing for plan generation and runtime execution.

```mermaid
flowchart LR
    AR[Agent Runtime]
    CFG[System Configuration Page - New]
    WD[Workflow Draft Generator - New]
    SC[Skill Workflow Context Assembler - New]
    SOC[SOP Workflow Context Assembler - New]
    WPC[Workflow Preview Composer - New]
    PGS[PlanGenerationService - New]
    RIB[RuntimeInstructionBuilder - New]
    CH[Communication Hub]

    AR --> WD
    AR --> SC
    AR --> SOC
    AR --> WPC
    AR --> PGS
    AR --> RIB
    AR --> CH
    CFG --> WD
```

## SOP Routing Logic

Both plan generation and runtime execution apply the same decision rule: if the system instruction names specific SOPs, only those SOPs are used; otherwise the Default SOP is applied as a fallback.
At runtime, the Default SOP is never injected alongside named SOPs — it is appended only when the system instruction references no SOP by name.

```mermaid
flowchart TB
    SI[System Instruction]
    CHECK{SOP Names in System Instruction?}
    NAMED[Referenced SOP Content]
    DSOP[Default SOP Content]
    PGS[Plan Context - PlanGenerationService]
    RIB[Runtime Instruction - RuntimeInstructionBuilder]

    SI --> CHECK
    CHECK -->|Yes - extract named SOPs| NAMED
    CHECK -->|No - use Default SOP| DSOP
    NAMED -->|Included in plan context| PGS
    DSOP -->|Fallback in plan context| PGS
    NAMED -->|Injected, Default SOP skipped| RIB
    DSOP -->|Appended as fallback| RIB
    SI --> RIB
```

## Integration Points

Integration remains hub-mediated end to end: UI requests route through the Communication Hub to Agent Runtime, while governed context comes from Control Center using sanitized data only.
The system configuration page feeds the selected generation model into the governed path so the chosen model is used consistently by both authoring flows and is visible in preview headers.
Default SOP is now configurable for all agent input types and feeds into both PlanGenerationService and RuntimeInstructionBuilder through the same governed path.

```mermaid
flowchart TB
    AU[Author or Reviewer]
    UI[Skill or SOP Workflow Dialog]
    CFG[System Configuration Page]
    DSOP[Default SOP - All Agent Input Types]
    CH[Communication Hub]
    AR[Agent Runtime]
    PGS[PlanGenerationService]
    RIB[RuntimeInstructionBuilder]
    CC[Control Center]
    DB[(Platform DB)]

    AU -->|Generate or Preview| UI
    AU -->|Select model| CFG
    AU -->|Configure Default SOP| DSOP
    CFG --> UI
    DSOP --> PGS
    DSOP --> RIB
    UI --> CH
    CH --> AR
    AR --> PGS
    AR --> RIB
    AR --> CH
    CH --> CC
    CC --> DB
```

## Data Flow Changes

Workflow generation and preview now combine author inputs with governed context so that output quality improves without allowing direct agent runtime access to sensitive data stores.
The configured generation model is part of that governed context and is surfaced in preview headers for reviewer clarity.
SOP context — whether named SOPs or the Default SOP fallback — is resolved from the governed context package before reaching PlanGenerationService or RuntimeInstructionBuilder.

```mermaid
flowchart LR
    I1[Selected Tools and Steps]
    I2[Business Description and Edits]
    I3[Configured Generation Model]
    R[Workflow Generation or Preview Request]
    CH[Communication Hub]
    AR[Agent Runtime]
    CC[Control Center]
    DB[(Platform DB)]
    C[Governed Context Package]
    O1[Generated Workflow Draft]
    O2[Workflow Preview Output]

    I1 --> R
    I2 --> R
    I3 --> R
    R --> CH
    CH --> AR
    AR --> CH
    CH --> CC
    CC --> DB
    DB --> CC
    CC --> C
    C --> CH
    CH --> AR
    AR --> O1
    AR --> O2
```

## Business Entity Relationships

The workflow authoring domain centers on request, draft, and preview entities, with context supplied from governed sources rather than direct runtime data access.
Default SOP is now an agent-level configuration entity that applies to any agent input type and participates in both plan context and runtime instruction assembly.

```mermaid
erDiagram
    WORKFLOW_REQUEST ||--o{ WORKFLOW_DRAFT : produces
    WORKFLOW_REQUEST ||--o{ WORKFLOW_PREVIEW : generates
    WORKFLOW_REQUEST }o--|| WORKFLOW_CONTEXT : uses
    WORKFLOW_CONTEXT }o--|| SKILL_WORKFLOW : references
    WORKFLOW_CONTEXT }o--|| SOP_WORKFLOW : references
    AGENT_CONFIGURATION ||--o| DEFAULT_SOP : assigns
    DEFAULT_SOP }o--o{ PLAN_CONTEXT : "fallback or referenced"
    DEFAULT_SOP }o--o{ RUNTIME_INSTRUCTION : "appended when no SOP named"
```

## Master Arch Update Instructions

The following master architecture pages should be updated to reflect the workflow authoring flow, governed context boundary, consistent workflow terminology, and the system-instruction-aware Default SOP routing behavior.

```mermaid
flowchart TB
    A[docs/master/architecture/system-overview.md]
    B[docs/master/architecture/modules/communication-hub/architecture.md]
    C[docs/master/architecture/modules/agent-runtime/architecture.md]
    D[docs/master/architecture/modules/control-center/architecture.md]
    E[docs/master/architecture/modules/agent-types.md]

    U1[Add workflow generation and preview interaction]
    U2[Document hub-mediated routing for workflow requests]
    U3[Document PlanGenerationService and RuntimeInstructionBuilder SOP routing]
    U4[Document Control Center governed context and DB boundary]
    U5[Default SOP available for all agent input types and terminology update]

    A --> U1
    B --> U2
    C --> U3
    D --> U4
    E --> U5
```
