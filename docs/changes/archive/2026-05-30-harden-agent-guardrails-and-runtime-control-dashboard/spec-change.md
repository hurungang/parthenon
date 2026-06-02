# Spec Change: Harden Agent Guardrails and Runtime Control Dashboard

## Affected Spec Areas
- docs/master/product/features/agent-execution.md
- docs/master/product/features/agent-types.md
- docs/master/product/features/agent-a2a-communication-and-slug-enforcement.md
- docs/master/product/features/control-center.md
- docs/master/product/features/agent-session-logs.md
- docs/master/product/features/observability.md
- docs/master/architecture/modules/agent-instance-dashboard.md
- docs/master/operations/runbooks/agent-execution-guardrails.md

## New Capabilities
- A vendor → model → guardrail hierarchy for model-usage guardrails, replacing the previous flat per-model configuration.
- Per-vendor model selection: under a vendor, operators can see and select which of the vendor's models are allowed to be used.
- Per-model guardrail records: each model can have one to four guardrails, one per period (hour, day, week, or month), configured only for the periods the operator actually wants.
- Per-guardrail enforcement posture (terminate or observe-only) and individual enable, disable, and remove controls on each guardrail.
- Per-model temporary disable: while a model is disabled, any agent execution that would use that model is blocked, and the block is surfaced in execution logs.
- Per-vendor temporary disable: while a vendor is disabled, every model under that vendor is treated as disabled; the per-model disable affordances remain visible to show the cascade source.
- Vendor list with expandable models, and models with expandable guardrails, in the operator UI so the three-level hierarchy is navigable.
- Runtime or dashboard visibility of the new hierarchy alongside current usage posture, including within-limit, approaching-limit, and breached states per configured period.
- Reliable guardrail enforcement coverage across direct execution and delegated execution chains.
- Terminate-as-default enforcement mode for newly configured guardrails.
- Observe-only guardrail threshold alert visibility in frontend execution logs.
- Runtime control dashboard showing all currently running agents and their delegated agents.
- Topology diagram view for active agent-to-agent delegation relationships.
- Node-level termination action from the dashboard for authorized users.
- Cascade termination behavior that stops delegated child executions when a parent execution is terminated.
- Recursion/dead-loop risk validation during agent create, update, and run initiation flows.

## Modified Capabilities

Before:
- Model-usage guardrails were configured as a single row per model with all four period limits (hour, day, week, month) baked into one record, forcing a four-period entry.
- There was no vendor-level grouping or vendor-level control; model-usage limits lived at the model level only.
- Operators could not temporarily disable a model or a vendor; misbehaving or risky models had to be removed from configuration to stop being used.
- Runtime or dashboard monitoring did not present a clear vendor → model → guardrail hierarchy for model-usage limits.
- Guardrail behavior could be inconsistently enforced across parent and delegated runs.
- Guardrail enforcement posture relied on observe-oriented handling rather than terminate-as-default governance.
- Observe-only guardrail limit events were not consistently surfaced to operators in execution log views.
- Runtime visibility of active delegations was fragmented and lacked a unified topology view.
- Runtime monitoring did not provide a unified view of model guardrails and current usage posture.
- Operators lacked a unified control surface to terminate running parent or delegated executions.
- Recursive delegation risks in SOP-linked agent configurations were not consistently blocked before execution.

After:
- Model-usage guardrails are organised as a vendor → model → guardrail hierarchy; each model carries one to four guardrail records, one per period, and operators configure only the periods they want.
- Each guardrail has its own enforcement posture and can be individually enabled, disabled, or removed.
- Under each vendor, operators can see and select which of the vendor's models are allowed to be used.
- Any model or any vendor can be temporarily disabled; disabling a vendor cascades to all of its models while leaving the per-model disable affordances visible to show the cascade source.
- Disabled models and models under a disabled vendor block agent execution and surface a clear operator-visible reason in execution logs.
- The operator UI presents vendors as a list, each vendor expands to show its models, and each model expands to show its guardrails — a clear three-level hierarchy.
- Guardrail enforcement is consistently applied across execution and delegation boundaries.
- Newly configured guardrails default to terminate mode, establishing a safer baseline operating posture.
- Observe-only guardrail limit events are surfaced as user-visible alerts in frontend execution logs.
- Operators can view all active running agents and delegated relationships in one dashboard.
- Operators can use a topology diagram to inspect live parent-child execution relationships.
- Operators can see configured model-usage limits and current usage posture within the runtime or dashboard monitoring experience, including whether each period is within limit, approaching limit, or breached.
- Authorized users can terminate selected running nodes, with parent termination cascading to active delegated children.
- Agent create/update/run flows validate recursive delegation risk and prevent dead-loop execution from starting.

## Removed Capabilities
- The "one configuration row per model with all four period limits baked in" model of model-usage guardrails.
- The implicit requirement to enter all four period limits (hour, day, week, month) when configuring model-usage guardrails on a model.
- The absence of a vendor-level grouping in model-usage guardrail configuration; vendor scope did not exist as a first-class concept for guardrail management.
- The lack of a temporary disable affordance on individual models, and the lack of any vendor-level enable/disable control.
- Implicit tolerance for inconsistent guardrail enforcement between parent and delegated execution paths.
- Implicit assumption that observe mode is the standard default for guardrail enforcement.
- Absence of explicit model-level usage governance across standard operating periods.
- Dependence on manual cross-screen monitoring to understand active delegation topology.
- Implicit acceptance of recursion-prone agent delegation configurations at create/update/run time.

## Spec Update Instructions
- Update docs/master/product/features/control-center.md to describe the new vendor → model → guardrail hierarchy as the canonical model-usage guardrail structure, replacing the previous flat per-model configuration.
- Update docs/master/product/features/control-center.md to define per-vendor model selection, per-model temporary disable, per-vendor temporary disable with cascade semantics, and per-guardrail enable/disable/remove and posture controls.
- Update docs/master/product/features/control-center.md to describe the operator UI presentation: vendors as a list, each vendor expanding to its models, each model expanding to its guardrails.
- Update docs/master/product/features/control-center.md and docs/master/architecture/modules/agent-instance-dashboard.md to define a single runtime control dashboard for running agents, delegated agents, topology visibility, and permission-gated termination actions.
- Update docs/master/product/features/control-center.md to require visibility of configured model-usage guardrails and current usage posture alongside execution guardrail status, including disabled-vendor and disabled-model state.
- Update docs/master/product/features/agent-execution.md to require consistent enforcement across direct and delegated execution and to define terminate as the default enforcement mode for newly configured guardrails.
- Update docs/master/product/features/agent-execution.md to require that agent execution is blocked when the requested model is disabled or when the model is under a disabled vendor, and that the block is surfaced in execution logs.
- Update docs/master/product/features/agent-session-logs.md and docs/master/product/features/observability.md to require observe-only limit alerts, termination outcomes, and disabled-model / disabled-vendor block events to appear as user-visible operational signals distinct from standard execution failures.
- Update docs/master/product/features/agent-types.md and docs/master/product/features/agent-a2a-communication-and-slug-enforcement.md to require recursive delegation and dead-loop risk validation at create, update, and run entry points.
- Update docs/master/operations/runbooks/agent-execution-guardrails.md to describe the new vendor → model → guardrail hierarchy, the one-to-four per-period guardrail model, vendor and model disable toggles with cascade behaviour, and the operator posture states shown in dashboard monitoring.
