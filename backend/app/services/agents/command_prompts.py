"""Command prompts — stored missions for command-driven special agent executions.

The "Optimize & Verify" flow is a DEDICATED, GATED optimization execution (it
is no longer a side effect of a normal run). This module holds:

- the canonical ``optimize-and-verify`` command mission text (single source of
  truth, seeded into the ``command_prompts`` table), and
- helpers to seed / resolve a command prompt and to interpolate the target
  ``agent_type_id`` into its mission.

The mission is the *user prompt* of a side execution: the agent runs its
ordinary deep-agent loop (its own model + the new optimization system tools),
but the prompt it is given is the command's mission, NOT the agent type's own
system instruction.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from sqlalchemy import select

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    """Read a non-negative int env override (unset/invalid → default)."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return max(int(raw), 0)
    except ValueError:
        return default

#: Stable slug for the "Optimize & Verify" command.
OPTIMIZE_AND_VERIFY_SLUG = "optimize-and-verify"

#: Marker set in the side-execution AgentJob ``input_data`` so the executor
#: (and status surface) can recognise a command-driven special execution.
COMMAND_MARKER_KEY = "__command"
COMMAND_AGENT_TYPE_KEY = "__command_agent_type_id"

#: The tools the optimize-and-verify command makes available to the agent.
#: These are the new system tools (registered in SystemToolRegistry + CC
#: handlers); they are all standard system tools so they flow through the
#: existing tool-routing / LangChain-tool machinery unchanged.
OPTIMIZE_AND_VERIFY_TOOLS = [
    "get_implementation_plan",
    "get_optimized_implementation_plan",
    "generate_optimized_plan",
    "generate_script",
    "execute_script",
    "list_scripts",
    "get_scripts",
    "get_script",
    "get_execution_log",
]

#: Bounded verify budget — the agent may retry a failing script at most this
#: many times before it must record ``needs_feedback``.
MAX_SCRIPT_ATTEMPTS = 3

#: Iteration limit for command-driven special executions (``__command``
#: marker). Command runs legitimately iterate on script authoring (execute →
#: fix source → execute again), which a task agent's default limit of 10
#: truncates mid-iteration. Command runs get a raised, dedicated limit.
COMMAND_MAX_ITERATIONS = 40

#: Generous token budget for command-driven special executions. Authoring +
#: verifying a whole composition is token-heavy; a role-level guardrail
#: token_budget tuned for ordinary task runs exhausts mid-authoring and fails
#: the command run with a bare "token_budget" error. Command runs get AT
#: LEAST this budget (a larger explicit policy budget wins). Override with
#: the COMMAND_TOKEN_BUDGET environment variable.
COMMAND_TOKEN_BUDGET = _env_int("COMMAND_TOKEN_BUDGET", 2_000_000)


OPTIMIZE_AND_VERIFY_COMMAND = """You are optimizing an AI agent's workflow in a DEDICATED optimization run.

Your mission: make sure the agent has a verified, optimized implementation
plan (sandboxed Python script segments plus LLM bridge steps where semantic
judgment is required) by assessing what already exists, authoring/repairing
only what is needed, and verifying that every script has CORRECT SYNTAX and
invokes the agent's tools CORRECTLY.

This is NOT a normal business run: there is no user task to accomplish here.
Your only deliverable is the optimized plan — or a bounded `needs_feedback`
outcome that explains why you could not reach high confidence.

The target agent type id is: {agent_type_id}

## Verification goal (read this before authoring)

A script is VERIFIED when:
1. its Python source has correct syntax and passes the sandbox check, and
2. every `tools.call(name, arguments)` uses an exact granted tool name with a
   valid argument shape, and that call finds a recorded response in the
   reference transcript (no validation, replay or transport error).

`execute_script` NEVER calls live tools and NEVER changes data. It verifies by
REPLAYING the recorded reference execution: the exact reference `input` becomes
the script `context`, and every `tools.call(name, arguments)` is answered from
the recorded tool responses of that execution (`tool_calls` returned by
`get_execution_log`). Nothing is fetched live and nothing is written.

A script does NOT need to reproduce the reference execution's tool OUTPUT
verbatim — verification is against the recorded sample, not live data. A
differing (or empty) computed value is ACCEPTABLE: do NOT treat it as a
failure, and NEVER re-attempt a script merely to force an output match. Only
syntax errors, sandbox violations, wrong/unknown tool names, malformed
arguments, MISSING recorded tool responses, and genuine replay errors require a
fix.

## Step 0 — Understand the current state FIRST (mandatory, before authoring)

The agent can read its OWN data. You MUST call these self-reflection tools
in this order BEFORE authoring any script:

1. `get_scripts` — the agent's script definitions (versions, python_source,
   sandbox validation status, lifecycle).
2. `get_execution_log` — lists the agent's recent NORMAL executions (newest
   first) and returns the TEXT LOG of the latest successful (completed) one,
   plus that run's actual `input`, the agent's typed `input_schema`, and the
   reference `tool_calls` (each recorded tool name with its arguments and the
   recorded response). This optimization run (and other optimization
   side-runs) is EXCLUDED, so the log you get is a real reference execution —
   not your own in-flight run. Use that log (or pass `session_id` for a
   specific run); do not page through unbounded history. When you verify with
   `execute_script`, pass the returned `input` object EXACTLY as its `input`
   argument: use the agent's real field names and values (e.g. `travel_date`,
   not `date`). Never invent, rename, or substitute input keys — a script that
   guesses keys verifies against the wrong context and fails at serving time.
3. `get_optimized_implementation_plan` — the current optimized plan (if any).
4. `get_implementation_plan` — the base (high-level) implementation plan
   steps; the only source of truth for WHAT the workflow must do.

## Step 1 — Skip re-authoring when healthy and unchanged (efficiency matters)

If you have read `get_scripts`, `get_execution_log`, and
`get_optimized_implementation_plan` and the logs show recent successful
executions and nothing broken, a fresh `ready` optimized plan exists, its
scripts compile and their sources still match the base plan's intent —
DO NOT re-author anything. State clearly that you skipped re-authoring
because the existing optimization is current/healthy and unchanged, and
finish. (Re-)author ONLY when there is a real problem: no ready plan, failing
scripts, repeated execution errors, or a changed base plan.

## Step 2 — Author and verify by REPLAYING the reference run (no drafts)

Author each sandboxed Python script. Each script defines
`def run(context, tools)` and returns a JSON-able dict whose `result` key is
the final user-facing value in the required output format. Your script runs
on the agent's behalf: `tools.call(name, arguments)` invokes MCP tools with
the agent's identity (no auth, no credentials, no envelope handling — results
are already unwrapped payloads), and `context` holds the task input and prior
outputs. The script contains ONLY business logic — no infra, no auth, no
envelope handling. The sandbox pre-binds `json`, `math`, `statistics`; there
is NO `import`, NO file/network/database/subprocess access, and MCP tool
calls are made ONLY through `tools.call(name, arguments)`. Never include
credentials or secret-shaped strings.

## Sandbox contract — EXACT (do not probe or introspect it)

**The tools inside your script are the SAME tools already in your toolset.**
Same names, same argument schemas, same behavior — the descriptions and
schemas you already have apply exactly. The only difference is HOW you call
them: inside the script you use `tools.call(name, arguments)` instead of
direct tool calls, and the result is the same unwrapped payload you would
receive from a direct call. There is nothing new to learn — reuse what you
know about each tool.

**The `context` object** (dict) contains:
- the task input fields (e.g. `context['project_id']` when the task carries
  a project id)
- each prior step's output, keyed by step name
Read what you need from it; it is plain data (dicts, lists, strings).

The environment is EXACTLY as described here. Do NOT write probe/diagnostic
scripts that dump types or reprs — that wastes iterations.

`run` is invoked as `run(context, tools)`:
- `context` (dict): the task input (e.g. `context['project_id']`) plus prior
  outputs.
- `tools` (object): facade with `.call(name, arguments) -> payload`.
  `tools.call` returns the UNWRAPPED tool payload directly (a list, dict, or
  string — never a content envelope).

Example — the minimal, correct shape (adapt to the task; keep it SMALL):

    def run(context, tools):
        projects = tools.call('supabase____list_projects', {})
        for p in projects:
            if p['id'] == context['project_id']:
                name = p['name']
        report = "# Report\\n\\n- Name: " + str(name)
        return {'result': report}

Rules: iterate over the returned payload directly; use string concatenation
or f-string-free building (plain `+` with `str(...)`); return
`{'result': <final user-facing value>}`.

Author the script and pass its FULL source to `execute_script` via the
`python_source` argument to test it — do not save drafts first, and do NOT
re-execute old saved script versions with empty input. Iterate: on a real
syntax/sandbox/tool-invocation failure, modify the source and execute again.
No defensive layers, no name-aliasing lists, no defensive error
handling — call the exact tool names given, assume tool results are already
unwrapped payloads. Only after a successful execution, save it via
`generate_script` (persist the working source).

TOOL NAMES ARE EXACT (mandatory): every `tools.call(name, ...)` must use the
tool name EXACTLY as granted to this agent — the server slug and tool name
are joined by a FOUR-underscore separator `____` (e.g.
`supabase____list_projects`), never two underscores. A wrong/unknown tool
name is a VALIDATION ERROR: `execute_script` / `generate_script` return
`status: "validation_error"` with `invalid_tool_names` (what you wrote) and
`valid_tool_names` (the exact names you may call) — fix the source to use a
name from `valid_tool_names` verbatim and iterate.

Verification happens through REPLAY `execute_script` calls — live tools are
never invoked and no data is ever changed:

- Call `execute_script` with the FULL python_source and the reference `input`
  object returned by `get_execution_log` (the exact keys and values — never
  guessed or renamed). If it compiles, its tool calls match the recorded
  transcript, and it runs end to end, the script is VERIFIED.
- `execute_script` REPLAYS ONLY the recorded tool responses from the selected
  execution's `tool_calls`. It NEVER calls a live MCP tool and NEVER changes
  data, so a verification run is always safe to repeat.
- A successful replay whose computed result differs from (or is empty
  compared to) the reference execution is STILL VERIFIED. Do NOT re-attempt it
  to force an identical result.
- If your composition needs a tool call that is NOT in the reference
  transcript, `execute_script` returns `status: "needs_user_input"` with
  blocker `reference_transcript_incomplete`. STOP immediately: do NOT retry
  and do NOT invent the call. Record `needs_feedback` naming exactly what the
  user must do (e.g. "run the agent once with a real search so the reference
  contains `mcp-demo____searchFlights`").
- If there is no reference tool data at all, `execute_script` returns
  `status: "needs_user_input"` with blocker `no_reference_tool_data`. STOP and
  ask the user to run the agent successfully first — do not loop.
- On a syntax/sandbox/tool-invocation error, fix the source in your context
  and execute again — bounded by the per-script attempt budget. A
  `needs_user_input` result is NOT such an error: it must end the run.

## Step 3 — Persist, or stop with `needs_feedback` (no dead loop)

When you have HIGH CONFIDENCE that the composition is correct and verified,
call `generate_optimized_plan` with the agent_type_id, the ordered steps, the
`fully_scripted` mark, the output mode/template, and status `ready`.

When you CANNOT reach high confidence — a script still fails after the
bounded attempts, the base plan is unclear, or a required tool is unavailable
— you MUST STOP and call `generate_optimized_plan` with status
`needs_feedback`, no steps, and the `error` argument set to a concise failure
reason (the last execute_script/compile error and which step failed). That
`error` is MANDATORY and will be shown to the user. Stopping early with
`needs_feedback` is a valid, expected outcome — never keep retrying to avoid it.

**Asking the user is the correct stop.** When verification cannot proceed
(`status: "needs_user_input"`), persist `needs_feedback` with a specific,
actionable `error`: what is missing, which tool/scenario is needed, and what
the user should do. The Optimized Plan tab shows this as "Optimization needs
your input". Do not keep retrying to avoid asking.

**Once you call `generate_optimized_plan` with a terminal status (`ready` or
`needs_feedback`), the optimization is COMPLETE.** Do NOT call
`get_optimized_implementation_plan` (or any other tool) again — re-reading the
plan cannot change it. Finish with the final answer below. A plan's `error`
field is a DESCRIPTIVE status, not a tool failure: never retry a tool call
because a returned plan carries an `error`.

## Rules (mandatory)

- MINIMIZE STEPS: chain consecutive deterministic work into ONE script; split
  into separate scripts ONLY where an LLM bridge (semantic judgment) is
  required between segments.
- VERIFY EVERY SCRIPT by replaying it with `execute_script` (correct syntax +
  correct tool invocation against the recorded reference transcript) — a
  script you have not verified is not verified. `execute_script` NEVER calls
  live tools and NEVER changes data.
- MANDATORY PRE-AUTHORING READ: you MUST read `get_scripts`, `get_execution_log`,
  `get_optimized_implementation_plan`, and `get_implementation_plan` before
  authoring or repairing any script.
- Bounded 3 attempts per script. On final failure, do NOT persist a ready
  plan: call `generate_optimized_plan` with status `needs_feedback`, no
  steps, and the `error` argument set to a concise failure reason (the last
  execute_script/compile error and which step failed) — this reason is
  MANDATORY and will be shown to the user.
- Use `list_scripts` / `get_script` to reuse or repair previously authored
  scripts for this agent type.
- Use the latest SUCCESSFUL normal execution returned by `get_execution_log`
  as the reference; do not fetch an unbounded history of execution logs.

## Final answer (mandatory)

This is an optimization run, not a business run. Your FINAL message must be a
short status report for the operator:

- on success (`ready`): state that the optimized plan was authored/verified
  (and, if applicable, that nothing needed re-authoring), plus anything the
  operator should know about the verification.
- on `needs_feedback`: state the failure reason clearly and that the plan
  awaits operator feedback.

Optimization bookkeeping belongs in the plan record through your tools
(`generate_script`, `execute_script`, `generate_optimized_plan`) — keep the
final message concise and operator-facing."""


async def seed_command_prompts(db: Any) -> None:
    """Idempotently seed the built-in command prompts (called at startup)."""
    from app.db.models.command_prompt import CommandPrompt

    defaults = [
        {
            "slug": OPTIMIZE_AND_VERIFY_SLUG,
            "name": "Optimize & Verify",
            "prompt_text": OPTIMIZE_AND_VERIFY_COMMAND,
        },
    ]
    for entry in defaults:
        result = await db.execute(
            select(CommandPrompt).where(CommandPrompt.slug == entry["slug"])
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            db.add(CommandPrompt(**entry))
            logger.info("Seeded command prompt '%s'", entry["slug"])
        else:
            existing.name = entry["name"]
            existing.prompt_text = entry["prompt_text"]
            existing.is_active = True
            logger.info("Refreshed command prompt '%s'", entry["slug"])
    await db.flush()


async def get_command_prompt(db: Any, slug: str) -> "Any | None":
    """Return the stored command prompt for *slug* (or the built-in fallback).

    Falls back to the in-code constant when the row is absent (e.g. a fresh
    database before seeding), so command execution never depends on a seed
    having run.
    """
    from app.db.models.command_prompt import CommandPrompt

    result = await db.execute(
        select(CommandPrompt).where(CommandPrompt.slug == slug)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        return row
    if slug == OPTIMIZE_AND_VERIFY_SLUG:
        return _builtin_command_prompt()
    return None


def _builtin_command_prompt() -> Any:
    """Return a lightweight in-memory stand-in for the built-in command."""
    from types import SimpleNamespace

    return SimpleNamespace(
        slug=OPTIMIZE_AND_VERIFY_SLUG,
        name="Optimize & Verify",
        prompt_text=OPTIMIZE_AND_VERIFY_COMMAND,
        is_active=True,
    )


def build_command_mission(
    prompt_text: str, *, agent_type_id: uuid.UUID | str | None
) -> str:
    """Interpolate the target agent_type_id into the command mission text."""
    return str(prompt_text).replace("{agent_type_id}", str(agent_type_id or ""))


def command_tool_names(slug: str) -> list[str]:
    """Return the toolset for a command (currently only optimize-and-verify)."""
    if slug == OPTIMIZE_AND_VERIFY_SLUG:
        return list(OPTIMIZE_AND_VERIFY_TOOLS)
    return []
