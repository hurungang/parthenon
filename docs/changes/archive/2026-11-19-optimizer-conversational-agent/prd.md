# PRD: Conversational Optimizer (Optimization Mode on the Agent Itself)

## Epic Overview

Today optimization is a one-shot command with post-hoc manual feedback: the operator triggers Optimize, one mission runs, and the result is a ready plan or a stop labelled "needs feedback". When replay verification cannot proceed, the optimizer can only stop with a written reason — the operator cannot watch it work, answer mid-run, or avoid a blind re-optimize.

This epic makes optimization a conversation that runs **on the agent itself**. Instead of introducing a separate optimizer agent with its own identity, role and tool access, the platform adds an **optimization mode**: a distinct conversation channel on the very agent type being optimized, in which the optimization mission replaces the agent's normal business instructions and skills for the duration of that conversation. The operator watches it work, answers its questions, and can approve one live run of the specific script under test when replay cannot prove it — or when they explicitly ask for one — all under the agent's own identity and permissions, so the optimizer can never reach further than the agent already can.

Optimization mode works for both typed and conversational agent types, is opened from the **Optimized Plan tab**, and leaves normal business runs of the agent untouched. Replay stays the default and every live script run needs one-time approval, so interactivity never becomes unattended live testing. The optimizer runs on its own configurable workspace model, never the agent's runtime model, and stays limited to that one agent type's plan, scripts and history.

## Business Goals

- Turn dead ends into resolutions and cut wasted spend: materially reduce the share of optimizations that end in "needs feedback" plus a blind retry, so one interactive session replaces repeated one-shot attempts against the same blocker.
- Grant no new access: optimization is performed with exactly the agent's existing identity, role and tool permissions, so the epic adds no new privilege surface and needs no separate role to administer or review.
- Preserve the replay-only safety guarantee: no live script run happens without an explicit, single-use approval of that specific script.
- Put optimization on the right model: each workspace can choose a dedicated optimizer model, defaulting to its existing plan-authoring model when unset.
- Make every live action auditable: which script was put forward, which tool calls it would make, the operator's decision, and the actual script run result are visible to operators and recorded against the agent and the operator.

## Users & Personas

- **Agent Operator** — triggers optimization and owns the resulting plan; wants to watch the optimizer work, answer its questions, approve a single live run of the script under test when needed, and stop guessing what went wrong. Relies on the fact that optimizing the agent cannot do more than the agent could.
- **Workspace Administrator** — owns the workspace's model configuration; wants to choose which approved model powers optimization, independent of the agent's runtime model, and be told when it is unset or unavailable.
- **Platform Administrator / Security Reviewer** — governs agents and their scripts; needs certainty that interactivity never widens live tool access, that no new agent identity or role is created to govern, that every live script run is approved once and recorded, and that optimization cannot reach anything outside its one agent.
- **Business Owner** — benefits silently: more workflows reach a verified optimized plan on the first attempt, so cost and latency gains arrive sooner with no loss of control.

## User Stories

- As an agent operator, I want to start an optimization conversation from the Optimized Plan tab of the agent I am optimizing, so that I can follow and steer optimization instead of starting it and waiting for an outcome.
- As an agent operator, I want that conversation to be a mode of my own agent — same identity and same permissions — so that optimizing can never do anything the agent itself could not already do.
- As an agent operator, I want to see what the optimizer is doing — which steps it takes and which information it looks at — while it works, so that I can tell whether it is on the right track.
- As an agent operator, I want the optimizer to ask me a question or ask me to decide when it is blocked, so that I can resolve it immediately instead of re-optimizing blindly.
- As an agent operator, I want to answer with a normal chat message and have that steer the refinement, so that optimizing feels like a conversation rather than a form.
- As an agent operator, I want the optimizer to ask to run one specific script — identified by its name and version — and show me the tool calls that script will make, so that I can judge the risk before approving anything.
- As an agent operator, I want to approve, deny, or leave that request to expire, so that nothing runs live without my consent and an unanswered request keeps optimization replay-only.
- As a security-conscious administrator, I want each approved live test to be used once and never repeated automatically, so that approval cannot turn into an unattended live-testing loop.
- As a security-conscious administrator, I want optimization to add no agent identity, role, or tool permission of its own, so that governing the agent is enough to govern its optimization.
- As an agent operator, I want replay-only to remain the default, so that optimization stays safe unless I deliberately lift the restriction for a specific test.
- As an agent operator, I want a compact, collapsed summary of what ran in this session — replay versus approved live — that I can expand when I want the detail, so that the chat stays readable without hiding the safety state.
- As an agent operator, I want a live-test request to fold into a single line in the chat history once I have decided, and to expand again if I want the detail, so that the conversation stays clean after the decision.
- As an agent operator, I want the optimizer to stop and ask rather than retry endlessly, so that an unprovable script never burns compute in a loop.
- As an agent operator, I want everything improved in the conversation to end up on the optimized plan, with the Optimized Plan tab updating without a page reload, so that my conversation produces a visible result.
- As an agent operator of a conversational agent, I want the same optimization conversation available to me, so that conversational agents are not a second-class case.
- As a workspace administrator, I want to select which approved model powers optimization for my workspace, so that optimization quality and cost fit my workspace, and I want it to fall back to my existing plan-authoring model if I have not chosen one.
- As a workspace administrator, I want to be told clearly when no usable optimizer model is available, so that I know exactly what to fix instead of facing a silent failure.
- As a platform administrator, I want every live-test request, the script it puts forward, the operator's decision, and the resulting script run recorded and attributed to both the agent and the operator, so that I can audit what the optimizer was allowed to run on which agent's behalf.
- As an agent operator, I want optimization to stay strictly on the agent I am optimizing, so that I never worry about it touching other agents, plans, or workspace configuration.

## Acceptance Criteria

### Entry, Scope & Availability

- The Optimized Plan tab of an agent offers a way to start an optimization conversation for that agent; the conversation is clearly tied to that one agent, and it is unavailable when no agent has been selected.
- Optimization is a mode of the agent: the conversation runs on the agent type itself, with the agent's existing identity, role and tool permissions. There is no separate optimizer agent identity or role to create, administer, edit or remove.
- Optimization mode is available for both typed and conversational agent types, with the same behaviour and the same safety rules on both.
- Entering optimization mode does not change the agent's normal business behaviour: its business instructions, skills and tool permissions are unchanged outside the optimization conversation, and normal runs are unaffected.
- Optimization's scope is exactly the selected agent's optimized plan, its generated scripts, its execution history, and its base plan. Requests to change other agents, other plans, workspace settings, permissions, or any other platform resource are declined with a clear explanation and nothing is changed.
- Optimization never deletes anything: retire/remove requests are declined with a clear "not supported" message.
- Optimization never reveals or requests sensitive material (identity tokens, credentials, database access).
- Starting the conversation is available whenever optimization would be available; when a precondition is missing (for example no successful reference execution), the conversation explains what is missing and does not start optimization work.
- If the agent has no base implementation plan, optimization generates one first with the workspace authoring model so the optimizer has a plan to work from; if that generation cannot complete, the operator is told clearly what is missing and no plan is fabricated.
- Conversation history for optimization is retained and resumable, and a new optimization conversation can be started without losing the previous one.

### Identity & Permission Parity

- The optimizer acts with exactly the agent's permissions and never broader: any operation the agent could not perform is refused with a clear explanation, and no elevated, shared or system-level access is used at any point.
- Optimizing an agent requires the permission to optimize and execute that agent; an operator who may not optimize it cannot start the conversation, and the refusal is explained.
- Tool permissions are not widened for optimization: the agent's granted tools are used only for an approved live test under the same identity, and every other optimization activity stays replay-only.
- A live test approved in the conversation runs the script under test once, end-to-end, as the agent's own operation within the agent's workspace, so the same permission, tenancy and safety rules that govern a normal run also govern the test.

### Visibility of What the Optimizer Is Doing

- While the optimizer works, the conversation shows ongoing activity — that it is working, which steps it is taking, and which information it looked at — so the operator can follow along without guessing.
- Work in progress that takes longer than expected ends in a clear outcome rather than an indefinite waiting state; a hang or failure surfaces as an explicit message with what to do next.
- Finished turns show what was produced (plan authored, script authored or refined, verification attempted) and its outcome in readable language.
- Expansion/collapse of detail is possible so that a busy turn is still readable at a glance.

### Ask and Decide, In-Chat

- The optimizer can ask the operator a question or present a decision inside the conversation, for example which of several interpretations to follow or what to do about something it cannot verify.
- The conversation clearly indicates that it is waiting for the operator, blocks further messages until answered, and re-surfaces the pending question if the operator reconnects or reopens the Optimized Plan tab.
- Choosing an answer, or typing free text, resolves the request; the response is recorded as part of the conversation and is visible in history and session review.
- An unanswered question does not cause the optimizer to proceed with an assumption and does not cause it to retry in the background.

### Live-Test Approval (Replay-Only by Default)

- Replay-only is the default and remains in force unless the operator explicitly approves a live test; nothing runs against a real integration without that approval.
- When replay cannot prove a script — or when the operator explicitly asks for a live verification — the optimizer asks in the conversation to run the **script under test once**, identified by its name and version, and shows the **tool calls the script will make** as an informational preview the operator can review before deciding. The individual tool calls are not approved one by one — the approval is for running that script.
- The operator can approve or deny; the decision is explicit, and denying leaves the session replay-only and the optimizer continues or stops accordingly, without retrying the same request on its own.
- An unanswered live-test request expires after a bounded period: the session stays replay-only, the request is closed, and the optimizer does not retry it.
- On approval, the script under test runs once end-to-end as the agent's own operation in the agent's workspace; the tools it calls are assumed to work, and there is no separate per-tool or per-operation test.
- No automatic repeat is possible: a second live test requires a new request and a new approval, and a previously used approval cannot be re-applied.
- Approval does not persist beyond the single test — later needs are asked again rather than inheriting the earlier consent.
- If the script cannot be run as requested (for example a tool permission the agent lacks, or a failure during the run), the failure is shown in the conversation as the script run result and nothing further runs live; the session returns to replay-only.
- The result of the approved script run returns to the conversation, is visible to the operator, and is usable by the refinement without any further live calls.
- Requests for live testing that would fan out into an unbounded or session-long live mode, or that ask for access beyond the agent's existing capability, are refused with a clear explanation.

### Chat Readability: Session Bar & Approval Card

- The conversation shows a compact, **default-collapsed "What ran in this session"** bar that summarises the session — how many turns were replay-only versus approved live, and whether the session is currently replay-only — instead of a persistent scope header occupying the conversation.
- Expanding the bar reveals the audit detail of what ran, so the summary is a shortcut to the record rather than a replacement for it.
- The bar's counts and replay-only state update as soon as a live test is approved, refused, expires, or completes, without a page reload.
- A live-test approval card is **script-based**: it names the script under test and its version and presents the tool-call preview for review before a decision.
- Once decided — approved, running, executed, failed, denied, expired, or cancelled — the card **collapses into a one-line summary in the chat history** that can be expanded again to see the request, the preview and the outcome.
- Collapsing after a decision does not change the recorded decision or the audit entry; it only affects how the conversation is displayed.

### Safe Stop Instead of Loop

- When the optimizer cannot prove a script from replay data, it asks or stops with a specific, readable explanation of what is missing — and it never retries in a loop to force a match.
- A session always reaches a bounded end state — a ready plan, an explicit needs-input stop the operator can act on in the same session, or an explicit failure — and there is no unbounded retry.

### Optimized Plan Outcome & Refresh

- Improvements agreed in the conversation are reflected on the optimized plan for that agent, and the plan's state (ready, needs input, failed, retired) is visible after the conversation ends.
- After the conversation ends or a turn completes an authoring step, the Optimized Plan tab refreshes automatically to show the current plan state without a manual page reload.
- The Result tab of the optimization run shows the final outcome — successful or not — as a readable, formatted summary, never an empty pane while the execution log holds the result.
- The agent dialog hosting the optimization reflects the completed run (plan and sessions) without reopening, and offers a reload action for an explicit refresh.
- The Optimized Plan tab keeps only what the operator needs at a glance: the optimizer model and a chat button. A question-mark help icon explains what optimization does and how to interact with it; there is no pre-start confirmation dialog.
- Plan steps render as a tree using the optional parent link on each flat step, and a script step's action is a clear button rather than an overlay on its description.
- The agent details dialog separates the topology from the plan: the topology tab is named Agent Topology, and the implementation plan has its own tab. Generating a plan shows a processing spinner until the new plan is ready.
- Steps carry an action icon rather than a number (sub-steps use a lighter icon), so hierarchy stays readable. A step is only an SOP/skill/tool invocation when it actually invokes an existing SOP, skill or tool; validation, selection, formatting and other steps are labelled Processing.
- A plan produced through the conversation follows the same lifecycle and verification rules as any other optimized plan; nothing bypasses verification because it was discussed in chat.
- The existing manual feedback option remains available alongside the conversation, and feedback recorded both ways is used on the next refinement.
- A failure reason remains visible on the plan and in the conversation, so the operator knows what to fix.

### Configurable Optimizer Model (Workspace-Scoped)

- Optimization runs on a model chosen per workspace from that workspace's approved, enabled model catalogue, kept separate from the agent's runtime model.
- When no optimizer model is chosen, optimization uses the workspace's existing plan-authoring model; this fallback is automatic, explicit in the product, and requires no second configuration to keep in sync.
- Changing the optimizer model takes effect for subsequent optimization in that workspace only, and never affects other workspaces or the agent's runtime behaviour.
- The System Config surface exposes the optimizer model choice, explains that it applies to optimization in the current workspace only, and states what it falls back to when unset.
- When no usable model is available (nothing configured and no authoring model, or the chosen model is disabled or removed from the catalogue), the conversation explains the situation, points to System Config, and does not start optimization with an unapproved model.
- Optimization never runs on the agent's runtime model unless that model was explicitly chosen for optimization in the workspace.

### Audit & Visibility of What Ran

- Every live-test request records the **script under test** (name and version), the **preview of the tool calls it will make**, the operator's decision, and the **script run result** — not individual per-operation outcomes — associated with the workspace, the agent, and the conversation.
- Each entry attributes the action to the agent's own identity together with the operator who approved it, so it is clear on whose behalf and under whose consent it ran; nothing is attributed to a separate privileged or shared identity.
- Live script runs are distinguishable from replay/verification work in what the operator sees and in the agent's history, so it is never ambiguous whether a real integration was contacted.
- The conversation record, including questions, answers, previews, decisions and script run results, is retained for audit and session review.
- An operator can review, from the conversation, what the optimizer looked at and what it ran, and the session summary bar expands into that record.

### Conversational Experience Reuse & No Regression

- The optimization conversation uses the platform's existing conversational experience: multi-turn context, working/waiting/progress indicators, inline requests for input, session controls, and persisted history behave as they do elsewhere in the product.
- Optimization mode is a distinct conversation channel for the agent: it never mixes with the agent's normal business conversations, and a conversation started for business use never turns into an optimization session.
- Optimization that is not conducted conversationally keeps working as before; existing optimization outcomes, plan states, retire behaviour, execution preference and fallback are unchanged.
- Execution of an agent is never affected: a normal run never becomes an optimization session, and optimization never alters the agent's runtime behaviour on its own.
- No optimization work starts from the conversation without the operator's explicit action.
- When the operator lacks permission to optimize or to view the agent, the conversation declines with a clear message and no work starts.
- All optimizer-facing text is localised, and error surfaces use the product's standard error presentation.

## Out of Scope

- A new human-intervention dashboard or intervention queue. The optimization conversation reuses the platform's existing waiting/blocked conversation state and presents decisions inline in the conversation; building a separate dashboard or queue for these decisions is not covered.
- Creating a dedicated optimizer agent, agent type, role, or permission set — optimization adds no identity of its own.
- Automatic or unattended re-optimization, and any background or scheduled optimization activity.
- Automatic, bulk, or session-long live execution; any "always allow live" or "remember this approval" mode.
- Approving or testing individual tool calls one at a time — a live test is a single run of the script under test, and its tool calls are previewed, not individually approved.
- A persistent scope header or always-visible audit panel in the optimization conversation; scope is conveyed by a compact, default-collapsed session summary.
- Live testing that goes beyond the agent's existing tool permissions, or that runs under a privileged, shared, or elevated identity.
- Managing anything other than the selected agent's plan, scripts and logs — no cross-agent edits, no workspace setting changes, no permission changes, no deletions.
- Changing how scripts are sandboxed, validated, versioned, or promoted; the script registry and lifecycle stay as they are.
- Changing execution preference and fallback semantics, or the requires-fix marking and alert behaviour.
- Changing the agent's own instructions, skills, or granted tools outside optimization mode.
- Hand-editing plan steps directly, or maintaining multiple plan versions side by side.
- Redesigning the Run Agent dialog, the Agent Type dialog as a whole, or the Control Center Assistant.
- Automatic detection of a semantic error hidden inside an otherwise successful tool response (still deferred).

## Dependencies & Constraints

- Depends on the existing conversational-agent experience: multi-turn context, working/waiting indicators, inline input requests, session persistence and session controls.
- Depends on the existing agent identity, role and tool-permission model — optimization inherits them as-is and adds nothing to them.
- Depends on the existing optimization capabilities (reading plans, scripts and execution logs, authoring scripts, verifying by replay, authoring the optimized plan).
- Depends on the existing workspace configuration and the existing plan-authoring (workflow generation) model selection, which becomes the default for the optimizer model.
- Depends on the existing replay verification capability; this epic widens the operator's ability to unblock it, not the verification rules.
- Depends on the agent already being optimizable (for example a successful reference execution); when that is missing, the conversation explains it rather than working around it.
- Must preserve the platform's top-priority rules: strict service segregation, so each service owns only its own concerns and work crosses between them only through the agreed paths; and agents never receive sensitive material such as identity tokens or credentials.
- Live tests carry real cost and real side effects: the product's defaults (replay-only, explicit script-based approval, single use, no auto re-run) are the control, not an option.
- Approved live-test volume must stay bounded so a session cannot become an unbounded live workload, and an unanswered request expires rather than waiting indefinitely.
- Multi-tenancy: when enabled, optimization conversations, plan work, live-test approvals and model choice are tenant-owned and tenant-scoped; nothing crosses a workspace boundary.
