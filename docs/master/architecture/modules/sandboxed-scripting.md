# Sandboxed Scripting & LLM Mocking (Software 3.0 — Phase 2)

Software 3.0 agent workflows can be executed as **sandboxed, model-authored
Python scripts** in Agent Runtime, with a first-class **LLM Mock Layer** for
zero-LLM test runs. This module documents the sandboxed execution model, the
model-authored composition flow, and the mock layer.

## Sandboxed Script Engine (Agent Runtime)

Model-authored script source (`ScriptVersion.python_source`) executes in a
hardened, fail-closed sandbox built on
[RestrictedPython](https://github.com/zopefoundation/RestrictedPython)
(`backend/app/agent_runtime/scripts/sandbox.py`):

- **Compile-time restriction** — `compile_restricted_exec`; disallowed
  constructs fail closed with a typed `SandboxCompileError` before anything
  runs.
- **Allowlisted runtime** — `safe_builtins` plus safe computation helpers;
  the modules `json`, `math`, and `statistics` are pre-bound; there is **no
  `import` statement**, no `open`/`eval`/`exec`/`compile`/`__import__`.
  Filesystem, network, database, and subprocess access all fail closed
  (`SandboxViolationError`).
- **MCP-only egress** — the script's ONLY external binding is the injected
  `tools` facade (`SandboxToolFacade`), a thin sync wrapper over the
  session-bound `CommHubToolClient`: same mTLS path, dual identities,
  per-call token injection by Communication Hub, `provenance=script`
  tagging. Scripts never hold credentials.
- **Resource caps (N1)** — per-version caps (`cpu_limit_seconds`,
  `memory_limit_mb`, `wall_time_limit_seconds`) with platform defaults when
  null. Wall-time is enforced with a daemon worker thread + join timeout
  (safe abandonment: the request/event loop stays healthy); memory via
  `resource.RLIMIT_AS` around execution where the platform supports it; the
  CPU budget is enforced through the wall-time cap (in-process sandboxing
  cannot signal-kill one thread without risking the service process).
  Breaches raise `ResourceLimitExceededError` with
  `sandbox_termination=True` and a one-line human-readable detail.

Script contract: the source defines `run(context, tools)` and returns a
JSON-able dict.

## Model-authored composition (two-layer plan model)

The base implementation plan stays a plain high-level step list. The
workflow composition is authored by the **opt-in optimization step of the
Run Agent flow**: when the user launches an agent with no fresh optimized
plan, the flow offers "Run with optimization" or "Skip optimization";
opting in launches a **command-driven side execution** whose prompt is the
stored `optimize-and-verify` command mission (a `CommandPrompt`) plus the
user's real task. The side execution reads its own state first (existing
scripts, execution logs, prior optimized plan — skipping re-authoring when
nothing is wrong), and when authoring is needed it authors the full
composition — sandboxed Python script segments (`python_source` per
scriptable step), LLM bridge steps, decision steps, and the `fully_scripted`
mark — verifying each script against the real integration (the verification
IS the real run). On success it persists an **`OptimizedImplementationPlan`**
(a separate entity from the base `AgentPlan`); "Retire plan" marks the row
`retired` so the next run re-triggers the optimized-plan check.

The Script Compiler
(`backend/app/agent_runtime/scripts/compiler.py`) is a **validator /
normalizer** of that model-authored Python — RestrictedPython compile check,
AST safety scan (no imports, no I/O calls, no dunder traversal),
secret-shape guard (SEC3), resource-cap annotations. Validation failure
keeps the candidate in draft with a recorded `sandbox_validation_reason`.
No step is ever auto-appended — the previous hardcoded
`semantic____render` append was removed.

**Serving rule (freshness gate):** the Script-First Dispatcher serves the
optimized composition only while it is ready **and newer than the base
plan**: `fully_scripted` → zero-LLM script; otherwise the scripts are
exposed as invocable tools and the LLM orchestrates. An absent, stale, or
failed optimized plan falls back to the base plan's LLM path.

## Execution, fallback & accounting

- The Script-First Dispatcher runs `python_source` versions in the sandbox
  (whole-script path) or authored `script_segment` steps inside step graphs;
  every tool call flows MCP-only through the injected client.
- Sandbox violations and cap terminations are **unconditional LLM fallback
  triggers** (`sandbox_violation`, `resource_limit_exceeded`) recorded on
  `FallbackEvent` — a run never fails solely because a script failed.
- Script execution logs are **humanized one-liners** (step name, what ran,
  natural-language outcome summary) — no truncated JSON blobs.
- `tokens_saved_actual` is **measured** against the reference LLM run's real
  token usage when known; `tokens_saved_estimate` remains only on
  historical rows.

## LLM Mock Layer

A deterministic mock provider
(`backend/app/services/agents/llm_mock_provider.py`) is registered in the
model dispatch layer (`LangChainModelFactory`). Selected via configuration —
test environments only; production default is off:

| Env var | Values | Purpose |
|---|---|---|
| `LLM_MOCK_MODE` | `off` (default) / `scripted` / `record` / `replay` | Mock layer selection; invalid values fail fast |
| `LLM_MOCK_SCRIPTED_RESPONSES` | inline JSON or `@/path/file.json` | Scripted match/response rules |
| `LLM_MOCK_RECORDINGS_FILE` | JSON file path | Record/replay backing store |

- **scripted** — deterministic hand-authored responses keyed by prompt
  substring; unmatched prompts fail loudly.
- **record** — captures request/response/usage into `LLMMockRecording`
  rows via the CC internal endpoint `/internal/llm-mock/recordings`
  (mTLS service certs; AR never touches the DB). Payloads carry prompt +
  response + usage only — never API keys or identity tokens (rejected
  server-side).
- **replay** — deterministic replay keyed by `recording_key` (SHA-256 of
  kind + model + serialized messages); unmatched calls fail loudly.

The CC semantic-bridge endpoint is served by the same mock layer in mock
modes, so model-backed script steps run zero-LLM in tests. Prompt-assertion
helpers (`assert_prompt_contains`, `assert_prompt_structure`) support
deterministic test assertions against recorded request payloads.

## Compliance

Segregated services (sandbox and mock layer are in-process AR components;
recordings persist through a CC internal endpoint); scripts run only in AR;
only CC connects to PostgreSQL; scripts receive no credentials; scripts'
only egress is the injected MCP client.
