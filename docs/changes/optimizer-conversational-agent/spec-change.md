# Spec Delta: Conversational Optimizer (Optimization Mode on the Agent Itself)

## Affected Spec Areas

- `docs/master/product/features/sandboxed-scripting.md` — conversational optimization; replay-only default corrected
- `docs/master/product/features/software-3-0-agent-framework.md` — optimization also offered conversationally
- `docs/master/product/features/agent-management.md` — Optimized Plan tab conversation entry and refresh
- `docs/master/product/features/agent-types.md` — optimization mode on typed and conversational agent types; no new agent type
- `docs/master/product/features/conversation-management.md` — optimization channel on the agent itself
- `docs/master/product/features/agent-plan-mode.md` — conversational plan authoring; lifecycle unchanged
- `docs/master/product/features/agent-execution.md` — approved single live script run and attribution
- `docs/master/product/features/agent-session-logs.md` — live script runs distinguishable from replay work
- `docs/master/product/features/agent-identity.md` — optimizer identity/permission parity; no optimizer identity or role
- `docs/master/product/features/control-center.md` — System Config optimizer model setting
- `docs/master/product/features/multi-tenancy.md` / `strict-tenant-isolation.md` — optimization artifacts tenant-owned and scoped
- `docs/master/product/features/model-configurations.md` — optimizer model from approved catalogue
- `docs/master/data-model/modules/agents/entities.md` — optimization conversation channel and live-test approval record
- `docs/master/data-model/modules/tenancy/entities.md` — optimizer model setting, fallback resolution
- `docs/master/data-model/modules/workflow-compilation/entities.md` — live-test audit trail distinct from replay
- `docs/master/ux/README.md` — Optimized Plan tab conversation flow, collapsed session summary, and refresh
- `docs/master/ux/agent-session-log-ui.md` — live script runs visible and distinguishable

## New Capabilities

- **Optimization mode on the agent itself, scoped to that agent**
  - Optimization is a distinct conversation on the agent type being optimized — not a separate seeded agent. The optimization mission takes the place of the agent's business system instruction and skills for the duration of that conversation, and the optimization tools are made available in it.
  - The conversation is available for both typed and conversational agent types, with identical behaviour and safety rules. It is a separate conversation channel: it never mixes with the agent's business conversations, and a business conversation never becomes an optimization one.
  - The agent's normal business behaviour is unchanged outside optimization mode — its instructions, skills, granted tools and runs are as they were.
  - No new agent identity, agent type, role, or permission is introduced; the existing identity and role model is used as-is.
  - The conversation is gated by the existing optimization preconditions — a successful reference execution and a configured plan-authoring model; when either is missing, the conversation explains it and starts no optimization work.
  - Scope is inherent because the conversation belongs to exactly one agent type: other agents, other plans, workspace settings, permissions, and deletions are declined with a clear explanation.
  - Sessions are persistable and resumable, with the product's existing multi-turn, waiting, and progress behaviour.
- **Identity and permission parity**
  - The optimizer acts with exactly the agent's identity, role and permissions and can never act more broadly; the agent's granted tools remain usable only through an approved live test and are not widened for optimization.
  - Starting an optimization conversation uses the existing permission to optimize and execute that agent type — no additional grant is needed and none is implied.
  - Because the agent's own identity is used, the tenancy, permission and safety rules of a normal run apply unchanged to approved live tests.
- **Visible optimizer activity**
  - The operator sees that the optimizer is working, which steps it is taking, and which information it looked at, with expandable detail and clear terminal outcomes instead of an indefinite wait.
- **In-chat ask and decide**
  - The optimizer can ask a question or present a decision in the conversation; the session shows it is waiting, blocks new input until answered, and re-surfaces the pending request after reconnect.
  - Responses become part of the conversation record and feed the refinement; an unanswered request never causes an assumption or a background retry.
- **Single-use live-test approval (script-based)**
  - Replay-only is the default. When replay cannot prove a script — **or when the operator explicitly asks for a live verification** — the optimizer may ask to run the **script under test once**, identified by its name and version, and shows the tool calls the script will make as an **informational preview** — the operator approves running that script, not each individual tool call.
  - The operator approves or denies; on approval the script runs once end-to-end as the agent's own operation in its workspace, the tools it calls are assumed to work, there is no separate per-tool test, and the run result returns to the conversation. Any further live work requires a new request and approval.
  - Denial, silence, or expiry keeps the session replay-only; a previously used approval cannot be re-applied, approval does not persist beyond the single test, and no automatic re-run of the script occurs.
  - Requests for unbounded or session-long live access, or for capability beyond the agent's existing permissions, are refused with a clear explanation.
  - When the script cannot run (a missing permission, or a failure during the run), the failure is shown as the script run result, no further live work starts, and the session returns to replay-only.
- **Chat readability**
  - The conversation shows a compact, **default-collapsed "What ran in this session"** bar — replay versus approved-live counts plus the current replay-only state — in place of a persistent scope header; expanding it reveals the audit.
  - The live-test approval card is script-based and, once decided (approved, running, executed, failed, denied, expired, cancelled), **collapses into a one-line chat-history summary** that can be expanded again; collapsing changes display only, never the decision or the record.
- **Dedicated optimizer model per workspace (tenant)**
  - A workspace (tenant) can select which approved model powers optimization; unset resolves to the workspace's existing plan-authoring model, with no second setting to keep in sync.
  - The optimizer model is never the agent's runtime model unless explicitly chosen for optimization.
  - The not-configured / unavailable state is explained at the point of use and pointed at System Config, never silently substituted.
- **Optimization audit trail**
  - Live-test requests record the script under test (name and version), the tool-call preview it was approved on, the operator's decision, and the script run result — not individual per-operation outcomes; live work is distinguishable from replay verification.
  - Each entry is attributed to the agent's own identity together with the authenticated operator — never to a separate, shared, privileged, or elevated identity.

## Modified Capabilities

- **Optimize-and-Verify (one-shot command execution)**
  - Before: triggering Optimize ran a single optimization mission; the operator could not observe it, could not respond mid-run, and could only receive a written `needs_feedback` reason afterwards.
  - After: the same optimization capability is also available as an interactive conversation on the agent itself — observable, answerable, and able to unblock a replay gap with one approved live test — while the one-shot outcome path still exists and behaves as before.
- **Agent identity and permission surface**
  - Before: optimization was a machine-run mission with no operator-visible identity of its own, so it was unclear what identity and permissions it acted under.
  - After: optimization is an explicit conversation mode of the agent, acting under the agent's own identity and permissions, so nothing broader than the agent's existing access is ever available and no new role has to be governed.
- **Agent type support for optimization**
  - Before: optimization applied to typed (workflow) agent types only.
  - After: optimization mode is available to both typed and conversational agent types, with the same rules and the same safeguards.
- **Blocked-verification outcome**
  - Before: when replay could not proceed, the only options were a stop with a recorded reason or a blind manual re-optimization.
  - After: the optimizer stops and asks, in the conversation, with a specific account of what is missing, and the operator can answer, steer, or approve a single live run of the script under test in the same session; the stop is still bounded and never a loop.
- **Feedback loop**
  - Before: steering happened through a separate manual feedback box, and re-optimization was triggered separately.
  - After: conversation messages can steer refinement in place, and the manual feedback path remains available; both feed the next refinement.
- **Optimization model attribution**
  - Before: optimization used the workspace authoring model with no way to choose a different model specifically for optimization.
  - After: optimization can be pointed at a workspace-chosen optimizer model, defaulting to the authoring model when unset, and never the agent's runtime model by accident.
- **System Config**
  - Before: System Config explained the model used for workflow generation and plan authoring.
  - After: it also exposes the optimizer model, its fallback to the authoring model, its workspace (tenant) scoping, and a reminder when no usable model exists.

## Removed Capabilities

- The separate, seeded optimizer agent identity/role — optimization no longer needs its own agent, role, or permission set, and there is nothing optimizer-specific for an administrator to create, edit, remove, or govern separately.
- The assumption that optimization is always a single uninterrupted machine run with no operator interaction — interactivity is now part of the optimization path.
- The dead-end outcome where a replay gap could only be resolved by leaving the Optimized Plan tab and re-optimizing without new information — the conversation now resolves or explicitly stops with a decision point.
- Any implicit expectation that live tool access during optimization is decided by the platform — every live script run now requires explicit, single-use operator approval of that specific script.
- The idea that a live test is a per-operation or per-tool approval, or a separate test of individual tool calls — the approval covers one end-to-end run of the script under test, whose tool calls are previewed rather than individually approved.
- The restriction that conversational agent types cannot be optimized.

## Spec Update Instructions

- Update **Sandboxed Scripting** spec, two passes:
  - First, correct the existing live-verification wording: state that **replay-only is the documented default** for optimization and that a live verification happens only through an explicitly approved, single-use run of the script under test. This correction is a prerequisite so that the "verification rules unchanged" statement below is accurate.
  - Then add a "Conversational Optimization" section describing optimization mode on the agent itself, its observable activity, its in-chat ask/decide behaviour, the single-use live-test approval of the script under test (named with its version, with an informational preview of the tool calls it will make and a single end-to-end run on approval), the refusal of unbounded or session-long live requests, and that a failed or permission-denied run starts no further live work. State explicitly that the script lifecycle, retire behaviour, and execution preference/fallback are unchanged.
- Update **Software 3.0 Agent Framework** spec: note that the built-in workflow-optimization capability is offered both as a one-shot action and through an interactive, human-gated optimization conversation on a single agent.
- Update **Agent Management** spec: document the conversation entry point on the Optimized Plan tab, the scoped conversation view, the default-collapsed "What ran in this session" summary bar, the script-based live-test approval card that collapses to a one-line history summary once decided, and the automatic refresh of the tab afterwards. Note that opening the conversation is gated by the existing optimization preconditions — a successful reference execution and a configured authoring model.
- Update **Agent Types** spec: state that optimization mode is a distinct conversation channel available on both typed and conversational agent types, that it does not create or alter any agent type, role, or permission, and that an agent's business behaviour outside optimization mode is unchanged. Remove any reference to a seeded optimizer agent type.
- Update **Conversation Management** spec: add optimization as a conversation channel of the agent that owns it — covering the waiting/blocked state for its questions, the separation from business conversations, and the retention of its sessions — noting that the participant identity is the agent's own.
- Update **Agent Identity Management** spec: state that optimization introduces no new agent identity or role — it uses the agent's existing identity and role — that it requires only the existing permission to optimize and execute that agent type, and that it acts with exactly the agent's permissions and never broader.
- Update **Agent Plan Mode** spec: state that an optimized plan can be authored conversationally without changing how plans are verified, served, retired, or flagged requires-fix.
- Update **Agent Execution** spec: document that an operator-approved live test runs the script under test once end-to-end as a real operation under the agent's own identity and workspace, attributed together with the operator who approved it (never a shared or privileged identity), and that this is the only case in which optimization contacts a real integration.
- Update **Agent Session Logs** spec: require that approved live script runs and their results are visible and clearly distinguishable from replay verification work in the agent's history.
- Update **Control Center / System Config** spec: add the optimizer model setting with its workspace (tenant) scoping, its fallback to the plan-authoring model, the not-configured guidance, and the requirement to never substitute an unapproved model.
- Update **Multi-Tenancy / Strict Tenant Isolation** specs: state that optimization conversations, approvals, live tests, and model choice are tenant-owned and tenant-scoped, and that live tests run inside the session's tenant under the agent's identity.
- Update **Model Configurations** spec: state that the optimizer model is chosen only from the workspace's approved, enabled models, that it is never derived from the agent's runtime model, and that a disabled or removed selection produces the not-configured state.
- Update **data-model agents entities** spec: add the optimization conversation channel on the owning agent and the information kept for each live-test request — the script under test (name and version), the tool-call preview, the decision, and the script run result, associated with the agent and conversation — leaving the storage representation to the data model. Do not add an optimizer agent entity.
- Update **data-model tenancy entities** spec: add the optimizer model setting as a per-workspace (tenant) setting whose unset state resolves to the existing plan-authoring model setting.
- Update **data-model workflow-compilation entities** spec: note that optimization live-test requests, the script under test and its preview, the decision, and the script run result belong to the optimization audit trail and are distinct from replay verification runs.
- Update **UX docs** (`README`, `agent-session-log-ui`): reflect the conversation entry on the Optimized Plan tab, the activity/waiting states, the ask/decide interaction, and the **default-collapsed "What ran in this session" summary bar** (replay versus approved-live counts plus the current replay-only state) that expands into the audit instead of a persistent scope header. Reflect the **script-based live-test approval card** — the script under test named with its version plus an informational preview of the tool calls it will make — which **collapses into a one-line chat-history summary once decided** (approved, running, executed, failed, denied, expired, cancelled) and can be expanded again. Also reflect the denial/expiry replay-only state and the post-conversation refresh of the tab.
- Do **not** modify or generalize the **Control Center Assistant** spec: no new seeded conversational agent is introduced, and the assistant's own scope, preview, and approval rules stay as they are.
- Explicitly do NOT modify the script registry lifecycle, sandbox baseline, security model, identity topology, tool permission semantics, execution preference and fallback rules, requires-fix behaviour, or tenant isolation mechanics — this epic changes how optimization is conducted and unblocked, which model powers it, and how live access is approved and audited.
