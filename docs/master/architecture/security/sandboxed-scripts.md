# Sandboxed Scripts — Security

Model-authored scripts execute in a fail-closed sandbox inside Agent
Runtime. See [Sandboxed Scripting](../modules/sandboxed-scripting.md) for
the execution model.

## Invariants

- **No I/O of any kind** — filesystem, network, subprocess, and database
  access all fail closed; the only egress is the injected session-bound
  tool client (MCP-only).
- **Baseline-only** — restricted compile; runtime globals seeded wholesale
  from RestrictedPython's audited safe baseline (plus pre-bound safe
  modules) with only documented guards layered on top; no `import`
  statement, no dynamic-evaluation constructs.
- **Resource caps** — per-version CPU, memory, and wall-time limits with
  safe termination; a breach kills the execution safely, records the
  event, and falls back to the LLM path (a run never fails solely because
  a script failed).
- **No credentials reach scripts** — scripts bind to the agent session
  under the agent's dual identities; tokens are injected per call by
  Communication Hub and never handed to script code. A **secret-shape
  guard** at validation rejects credential-shaped strings in script
  source before anything runs.

## Sandbox Choice Rationale

An in-process hardened interpreter (RestrictedPython) was chosen over a
separate WASM-style runtime: no serialization boundary on every tool call
or model-backed step, direct integration with session binding, injected
client, caps, and observability, and no second supply chain — sufficient
given MCP-only egress and no untrusted-user scripting (out of scope).
