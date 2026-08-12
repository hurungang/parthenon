# Spec Change: Service Segregation Security Audit and Control Center API Allowlists

## Affected Spec Areas
- docs/master/architecture/system-overview.md
- docs/master/architecture/modules/control-center.md
- docs/master/architecture/modules/communication-hub.md
- docs/master/architecture/modules/agent-runtime.md
- docs/master/product/features/security-model.md
- docs/master/product/features/agent-execution.md
- docs/master/product/features/agent-identity.md
- docs/master/qa/test-plans/agent-security-test-plan.md

## New Capabilities
- Formal service-boundary assurance model covering Web UI, Communication Hub, Control Center, Agent Runtime, and Database interaction constraints.
- Separate Control Center API allowlists by caller type (Agent Runtime and Communication Hub).
- Security gap assessment framework that records boundary violations, over-privilege exposure, and remediation priorities with accountable ownership.
- Governance-ready evidence model for proving both permitted paths and blocked disallowed paths.

## Modified Capabilities
Before:
- Service segregation was defined in policy intent but not consistently represented as auditable, caller-specific Control Center access boundaries.
- Internal Control Center access patterns allowed overlap risk between Agent Runtime and Communication Hub.
- Security gaps were handled in a decentralized way, reducing prioritization clarity and audit defensibility.

After:
- Service segregation is defined as an approved business control model with explicit allowed and disallowed interaction paths.
- Control Center access is split into two distinct allowlists, reducing privilege overlap and internal attack surface.
- Security gaps are managed through a single, risk-ranked remediation proposal with business ownership and delivery targets.

## Removed Capabilities
- Implicit, shared, or undocumented internal access assumptions between Agent Runtime and Communication Hub when calling Control Center.
- Tolerance for boundary ambiguities that cannot be demonstrated through audit evidence.

## Spec Update Instructions
- Update architecture specifications to include a clear interaction matrix for Web UI, Communication Hub, Control Center, Agent Runtime, and Database responsibilities.
- Add caller-specific Control Center API policy sections that define allowlisted access for Agent Runtime and Communication Hub separately, with deny-by-default for all other paths.
- Update security model documentation to include boundary enforcement outcomes, evidence expectations, and escalation criteria for violations.
- Update product-level identity and agent execution specs to reinforce that sensitive identity handling remains centralized and not exposed to runtime execution surfaces.
- Add quality and assurance guidance for validating allowlist enforcement and tracking remediation outcomes for critical and high-severity gaps.
