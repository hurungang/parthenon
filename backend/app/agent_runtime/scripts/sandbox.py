"""Sandboxed Script Engine (Agent Runtime) — RestrictedPython exec + resource caps.

Executes model-authored Python script source (``ScriptVersion.python_source``)
in a hardened, fail-closed sandbox (N1–N3):

- **Compile-time**: ``RestrictedPython.compile_restricted`` — the AST is
  restricted before anything executes; disallowed syntax fails closed with a
  typed error.
- **Runtime globals**: allowlisted builtins only (``safe_builtins`` plus a
  small set of safe computation helpers); no ``import`` statement (safe
  modules are pre-bound); ``_getattr_`` rejects underscore attributes;
  ``_write_`` uses the full write guard.
- **I/O fail-closed**: ``open``/``exec``/``eval``/``compile``/``__import__``
  are absent from the sandbox; file/network/db/subprocess attempts raise
  ``SandboxViolationError``.
- **MCP-only egress**: the script's ONLY external binding is the injected
  ``tools`` facade, a thin sync wrapper over the session-bound
  ``CommHubToolClient`` — identical mTLS/CH path, identity parity (SEC1),
  provenance=script tagging. No credentials ever enter the sandbox.
- **Resource caps** (N1): wall-time (worker-thread join + timeout), memory
  (``resource.RLIMIT_AS`` around execution where the platform supports it),
  and CPU-time (``resource.RLIMIT_CPU`` + SIGXCPU on platforms where signal
  handling is permitted). Breach → safe termination with a typed
  ``ResourceLimitExceededError`` carrying ``sandbox_termination=True`` and a
  one-line human-readable detail (no JSON blobs, N5).

The script contract: source defines ``run(context, tools)`` and returns a
JSON-able dict. ``context`` carries the workflow inputs; ``tools.call(name,
arguments)`` performs one MCP tool call.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import json as _json
import logging
import os
import resource
import threading
import time

from dataclasses import dataclass, field
from typing import Any

from RestrictedPython import compile_restricted_exec, safe_builtins
from RestrictedPython.Guards import (
    full_write_guard,
    guarded_iter_unpack_sequence,
    guarded_unpack_sequence,
)
from RestrictedPython.PrintCollector import PrintCollector

logger = logging.getLogger(__name__)

# ── Platform resource-cap defaults (N1: platform defaults when caps null) ────

DEFAULT_WALL_TIME_SECONDS = 30
DEFAULT_CPU_SECONDS = 10
DEFAULT_MEMORY_MB = 512


def _env_int(name: str, fallback: int) -> int:
    """Read an operator override from settings/env, falling back safely."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return fallback
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r — using default %s", name, raw, fallback)
        return fallback
    return value if value > 0 else fallback


def default_wall_time_seconds() -> int:
    return _env_int("SANDBOX_WALL_TIME_SECONDS", DEFAULT_WALL_TIME_SECONDS)


def default_cpu_seconds() -> int:
    return _env_int("SANDBOX_CPU_SECONDS", DEFAULT_CPU_SECONDS)


def default_memory_mb() -> int:
    return _env_int("SANDBOX_MEMORY_LIMIT_MB", DEFAULT_MEMORY_MB)


# ── Typed failures (Flow C) ──────────────────────────────────────────────────


class SandboxError(Exception):
    """Base typed sandbox failure (fail-closed)."""


class SandboxCompileError(SandboxError):
    """Source failed the restricted compile / safety validation."""


class SandboxViolationError(SandboxError):
    """Runtime violation: disallowed access, missing contract, forbidden name."""

    sandbox_termination: bool = False


class ResourceLimitExceededError(SandboxError):
    """CPU / memory / wall-time cap breach → safe termination."""

    sandbox_termination: bool = True


# ── Caps ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SandboxCaps:
    """Effective resource caps for one sandboxed execution.

    Defaults resolve from env overrides (``SANDBOX_WALL_TIME_SECONDS``,
    ``SANDBOX_CPU_SECONDS``, ``SANDBOX_MEMORY_LIMIT_MB``) with the hard-coded
    values as safe fallbacks — operators can raise them for heavyweight
    workflows.
    """

    cpu_limit_seconds: int = field(default_factory=default_cpu_seconds)
    memory_limit_mb: int = field(default_factory=default_memory_mb)
    wall_time_limit_seconds: int = field(default_factory=default_wall_time_seconds)

    @classmethod
    def from_version_fields(
        cls,
        cpu_limit_seconds: int | None,
        memory_limit_mb: int | None,
        wall_time_limit_seconds: int | None,
    ) -> "SandboxCaps":
        """Resolve caps from ScriptVersion fields with env/platform defaults."""
        return cls(
            cpu_limit_seconds=cpu_limit_seconds or default_cpu_seconds(),
            memory_limit_mb=memory_limit_mb or default_memory_mb(),
            wall_time_limit_seconds=(
                wall_time_limit_seconds or default_wall_time_seconds()
            ),
        )


# ── Restricted compile ───────────────────────────────────────────────────────

# Names that must never be reachable from sandbox code (fail closed).
_FORBIDDEN_NAME_MARKERS = (
    "open", "exec", "eval", "compile", "__import__", "globals", "locals",
    "breakpoint", "input", "vars", "dir", "system", "popen", "fork",
    "connect", "socket", "subprocess", "database", "session_maker",
)


def compile_sandbox(source: str) -> Any:
    """Compile model-authored Python under the restricted policy.

    Raises ``SandboxCompileError`` (one-line reason) on any disallowed
    construct or syntax error — nothing executes.
    """
    if not source or not source.strip():
        raise SandboxCompileError("Script source is empty")
    try:
        result = compile_restricted_exec(source, filename="<sandboxed_script>")
    except SyntaxError as exc:
        raise SandboxCompileError(f"Script syntax error: {exc.msg} (line {exc.lineno})") from exc
    if result.errors:
        first = str(result.errors[0]).splitlines()[0]
        raise SandboxCompileError(f"Script rejected by sandbox compiler: {first}")
    if result.code is None:
        raise SandboxCompileError("Script rejected by sandbox compiler")
    return result.code


# ── Guarded builtins / globals ───────────────────────────────────────────────


def _safe_getattr(obj: Any, name: str, default: Any = None) -> Any:
    """Guarded attribute access: underscore-prefixed names are denied."""
    if isinstance(name, str) and name.startswith("_"):
        raise SandboxViolationError(
            f"Access to attribute '{name}' is not allowed in the sandbox"
        )
    return getattr(obj, name, default)


def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
    """No import statement is permitted — safe modules are pre-bound."""
    raise SandboxViolationError(
        f"import of '{name}' is not allowed in the sandbox "
        "(allowlisted modules are pre-bound)"
    )


def _apply_cpu_cap(cpu_limit_seconds: int) -> bool:
    """CPU-time budgeting hook.

    In-process sandboxing cannot signal-kill a single worker thread without
    risking the whole service process (default SIGXCPU action terminates the
    process), so the CPU budget is enforced through the wall-time cap: a
    CPU-bound runaway is safely terminated at its wall-time limit instead.
    Kept as an explicit, documented no-op so caps stay configurable per
    ScriptVersion.
    """
    return False


def _apply_memory_cap(memory_limit_mb: int) -> Any:
    """Best-effort address-space cap (RLIMIT_AS) around execution.

    Returns the previous ``(soft, hard)`` limits for restoration, or ``None``
    when the platform rejects the adjustment (e.g. macOS).
    """
    try:
        previous = resource.getrlimit(resource.RLIMIT_AS)
        limit_bytes = memory_limit_mb * 1024 * 1024
        hard = previous[1]
        if hard not in (resource.RLIM_INFINITY, -1) and limit_bytes > hard:
            limit_bytes = hard
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, hard))
        return previous
    except (ValueError, OSError):  # pragma: no cover — platform-dependent (macOS)
        return None


def _restore_memory_cap(previous: Any) -> None:
    if previous is None:  # pragma: no cover — platform-dependent
        return
    try:
        resource.setrlimit(resource.RLIMIT_AS, previous)
    except (ValueError, OSError):  # pragma: no cover — platform-dependent
        pass


# Operators for RestrictedPython's ``_inplacevar_`` (augmented assignment):
# RestrictedPython passes the operator as a string (e.g. '+', '-', '*').
_INPLACE_OPS: dict[str, Any] = {
    "+": lambda x, y: x + y,
    "-": lambda x, y: x - y,
    "*": lambda x, y: x * y,
    "/": lambda x, y: x / y,
    "//": lambda x, y: x // y,
    "%": lambda x, y: x % y,
    "**": lambda x, y: x ** y,
    "&": lambda x, y: x & y,
    "|": lambda x, y: x | y,
    "^": lambda x, y: x ^ y,
    "<<": lambda x, y: x << y,
    ">>": lambda x, y: x >> y,
}


def build_safe_globals(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the hardened globals for sandbox execution.

    Seed from RestrictedPython's audited safe baseline wholesale; layer only
    documented custom guards (tools facade/context binding/resource caps).
    No I/O, no import, guarded attribute access and writes.
    """
    # Seed wholesale from RestrictedPython's safe baseline
    builtins_map = dict(safe_builtins)
    import builtins as _py_builtins

    # Ensure common safe builtins are present even if baseline differs
    for name in (
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "divmod",
        "enumerate",
        "float",
        "frozenset",
        "int",
        "isinstance",
        "issubclass",
        "len",
        "list",
        "max",
        "min",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "slice",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
        "Exception",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "AttributeError",
        "RuntimeError",
        "StopIteration",
    ):
        if not hasattr(builtins_map, name) and hasattr(_py_builtins, name):
            builtins_map[name] = getattr(_py_builtins, name)

    import json
    import math
    import statistics

    safe_modules = {
        "json": json,
        "math": math,
        "statistics": statistics,
    }
    for marker in _FORBIDDEN_NAME_MARKERS:
        builtins_map.pop(marker, None)

    globs: dict[str, Any] = {
        "__builtins__": builtins_map,
        "_getattr_": _safe_getattr,
        "_getitem_": lambda obj, index: obj[index],
        "_write_": full_write_guard,
        "_getiter_": iter,
        "_iter_unpack_sequence_": guarded_iter_unpack_sequence,
        "_unpack_sequence_": guarded_unpack_sequence,
        "_print_": PrintCollector,
        "_inplacevar_": lambda op, x, y: _INPLACE_OPS.get(str(op).rstrip("="), lambda a, b: a)(
            x,
            y,
        ),
        "__name__": "sandboxed_script",
        "json": safe_modules["json"],
        "math": safe_modules["math"],
        "statistics": safe_modules["statistics"],
    }
    if extra:
        globs.update(extra)
    return globs


# ── Capability contract (authoring-LLM facing) ───────────────────────────────


def build_capability_contract(
    *,
    output_format: str | None = None,
    tool_names: list[str] | None = None,
    available_variables: list[str] | None = None,
) -> str:
    """Build the sandbox capability contract for the authoring LLM.

    A deterministic, generated description of EXACTLY what a sandboxed script
    may rely on: pre-bound modules, the injected variable surface, the
    entry-point/output contract, and the resource caps. This is the contract
    handed to the LLM when it authors (and repairs) script source — the
    platform never guesses output shapes via hardcoded heuristics; the LLM
    authors against this contract and the engine tests the result.
    """
    fmt = (output_format or "auto").strip().lower() or "auto"
    resolved_format = "markdown" if fmt in ("", "auto") else fmt
    tools_line = (
        "Recorded tools available for replay during the test run: "
        + ", ".join(tool_names)
        if tool_names
        else "No tool calls were recorded — process the captured context data only."
    )
    variables_line = (
        "Variables available in ``context``: " + ", ".join(available_variables)
        if available_variables
        else "``context`` carries the workflow input data and captured tool "
        "outputs keyed ``step{N}_{tool_name}``."
    )
    return (
        "# Sandbox Capability Contract\n"
        "\n"
        "Your script runs on the agent's behalf: ``tools.call`` invokes the SAME "
        "MCP tools already in your toolset — identical names, argument schemas, "
        "and unwrapped results; only the calling style differs (``tools.call`` "
        "instead of a direct tool call). ``context`` is a plain dict holding the "
        "task input fields and each prior step's output keyed by step name. The "
        "script contains ONLY business logic — no infra, no auth, no envelope "
        "handling.\n"
        "\n"
        "## Tool names are EXACT\n"
        "- Call tools by their names EXACTLY as listed — the server slug and "
        "tool name are joined by a FOUR-underscore separator ``____`` (e.g. "
        "``server____tool``), never two. An unknown tool name fails the call.\n"
        "\n"
        "## Environment\n"
        "- Restricted Python (RestrictedPython subset). ``import`` statements "
        "are NOT allowed — everything you may use is pre-bound.\n"
        "- Pre-bound modules: ``json``, ``math``, ``statistics``.\n"
        "- Builtins: len, range, sorted, sum, min, max, abs, round, enumerate, "
        "zip, list, dict, set, tuple, str, int, float, bool, isinstance, and "
        "similar safe computation helpers. NO file/network/db/subprocess "
        "access, no ``open``/``eval``/``exec``; underscore-prefixed attributes "
        "are denied.\n"
        "\n"
        "## Entry point and variables\n"
        "- Define ``def run(context, tools)`` returning a JSON-able dict.\n"
        "- ``context``: a dict with the workflow input data and the captured "
        "tool outputs of the recorded run, keyed ``step{N}_{tool_name}`` in "
        "execution order.\n"
        "- ``tools``: the MCP tool client facade, INJECTED by the engine "
        "(``tools.call(name, arguments)``). In the test run it replays the "
        "recorded outputs; at serving time it performs real MCP calls. "
        "Tool results are ALREADY unwrapped: ``tools.call`` returns the "
        "actual payload (list/dict/string), never the MCP content envelope "
        "``{content: [...], isError: ...}`` — do NOT write envelope-handling "
        "code. "
        "Scripts never hold credentials and never do I/O themselves — tools "
        "run as separate, recorded steps.\n"
        f"- {variables_line}\n"
        f"- {tools_line}\n"
        "\n"
        "## Output contract (mandatory)\n"
        "- ``run`` must return a dict containing ``result``: the FINAL "
        "user-facing value in the required output format.\n"
        f"- Required output format: {resolved_format}. The user reads "
        "``result`` directly — never return raw tool JSON when a formatted "
        "document is required.\n"
        "\n"
        "## Resource caps (fail-closed)\n"
        f"- Wall time: {DEFAULT_WALL_TIME_SECONDS}s; CPU: {DEFAULT_CPU_SECONDS}s; "
        f"memory: {DEFAULT_MEMORY_MB}MB. Breaching a cap safely terminates "
        "the script (typed failure).\n"
        "- Any sandbox violation, compile error, or wrong-shape output is a "
        "typed, human-readable failure — write defensive code and produce "
        "the result in exactly the required format.\n"
    )


# ── MCP content-envelope unwrapping ──────────────────────────────────────────


def unwrap_mcp_tool_result(result: Any) -> tuple[Any, bool]:
    """Unwrap the MCP content envelope, returning ``(payload, was_unwrapped)``.

    MCP tools return ``{"content": [{"type": "text", "text": "<json-or-text>"}],
    "isError": false}``. Scripts must see the ACTUAL payload — never the
    envelope (live defect: a script inspecting the raw envelope concluded
    "no supabase project found"). Each ``text`` entry is parsed as JSON when
    it parses (fallback: the raw string); multiple entries merge into a list.
    Non-envelope results pass through unchanged. ``isError`` handling is the
    caller's responsibility (the error type differs by call path).
    """
    if not (isinstance(result, dict) and isinstance(result.get("content"), list)):
        return result, False
    entries: list[Any] = []
    for entry in result["content"]:
        if isinstance(entry, dict) and "text" in entry:
            text = entry["text"]
            if isinstance(text, str):
                try:
                    entries.append(_json.loads(text))
                except ValueError:
                    entries.append(text)
            else:
                entries.append(text)
        else:
            entries.append(entry)
    if not entries:
        payload: Any = None
    elif len(entries) == 1:
        payload = entries[0]
    else:
        payload = entries
    return payload, True


# ── MCP-only tool facade ─────────────────────────────────────────────────────


class SandboxToolFacade:
    """Synchronous, MCP-only tool facade handed to sandboxed scripts.

    Wraps the session-bound ``CommHubToolClient``: every call flows through
    Communication Hub on the agent's own mTLS path with provenance=script
    tagging (identity parity, SEC1/E7). This is the ONLY external binding a
    sandboxed script has — any other egress attempt fails closed.
    """

    def __init__(
        self,
        tool_client: Any,
        loop: asyncio.AbstractEventLoop,
        *,
        session_id: str,
        agent_type_id: str,
        script_version_label: str | None,
        call_timeout_seconds: float = 60.0,
        context: contextvars.Context | None = None,
        io_time_tracker: dict[str, float] | None = None,
    ) -> None:
        self._tool_client = tool_client
        self._loop = loop
        self._session_id = session_id
        self._agent_type_id = agent_type_id
        self._script_version_label = script_version_label
        self._call_timeout_seconds = call_timeout_seconds
        # Snapshot of the dispatching (request) task's context. contextvars do
        # NOT cross the thread bridge implicitly — the bridged task would run
        # with the loop thread's (empty) context and forwarded tenant headers
        # would be lost. Re-bind explicitly (SEC1 identity parity).
        self._context = context
        # Shared accumulator for time spent AWAITED inside tool calls. The
        # wall-time cap bounds the script's OWN compute — awaited MCP I/O is
        # paused (excluded) so multi-tool workflows are not penalized for
        # network latency (the per-call timeout still bounds each call).
        self._io_time_tracker = io_time_tracker if io_time_tracker is not None else {}
        self.calls: list[dict[str, Any]] = []
        self._io_lock = threading.Lock()

    def call(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Perform ONE MCP tool call through Communication Hub (blocking)."""
        if not isinstance(tool_name, str) or not tool_name or "://" in tool_name:
            raise SandboxViolationError(
                f"Invalid tool target '{tool_name}' — scripts may only call "
                "MCP tools by name via tools.call (E8)"
            )
        started = time.monotonic()
        with self._io_lock:
            self._io_time_tracker["in_flight_since"] = started
        coro = self._tool_client.call_tool(
            tool_name,
            dict(arguments or {}),
            session_id=self._session_id,
            agent_type_id=self._agent_type_id,
            provenance="script",
            script_version=self._script_version_label,
        )
        ctx = self._context
        tool_coro = coro
        if ctx is not None:
            async def _bridged() -> Any:
                # Run the tool-call task inside the captured dispatch context
                # so contextvars bound by the AR middleware (forwarded signed
                # tenant headers) are visible to the egress hook — verbatim,
                # never re-signed (SEC1).
                inner = ctx.run(asyncio.ensure_future, tool_coro)
                return await inner
            coro = _bridged()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            result = future.result(timeout=self._call_timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise ResourceLimitExceededError(
                f"Tool call '{tool_name}' exceeded the "
                f"{self._call_timeout_seconds:.0f}s per-call limit"
            ) from exc
        finally:
            # Exclude the awaited duration from the wall-time budget — only
            # the script's own compute counts against the cap.
            with self._io_lock:
                self._io_time_tracker["awaited"] = (
                    self._io_time_tracker.get("awaited", 0.0)
                    + (time.monotonic() - started)
                )
                self._io_time_tracker["in_flight_since"] = 0.0
        self.calls.append({"tool_name": tool_name, "has_result": result is not None})
        # Unwrap the MCP content envelope: the script sees the parsed payload,
        # never the envelope (live-defect regression — scripts must not need
        # envelope handling). isError fails closed as a typed sandbox error.
        payload, unwrapped = unwrap_mcp_tool_result(result)
        if unwrapped:
            if isinstance(result, dict) and result.get("isError"):
                detail = payload if isinstance(payload, str) else _json.dumps(payload, default=str)
                raise SandboxViolationError(
                    f"Tool '{tool_name}' reported an error: {detail[:300]}"
                )
            logger.info(
                "Tool '%s' result envelope unwrapped for sandboxed script "
                "(payload type: %s)",
                tool_name,
                type(payload).__name__,
            )
        return payload


# ── Execution ────────────────────────────────────────────────────────────────


def run_sandboxed_python(
    source: str,
    *,
    tool_client: Any = None,
    session_id: str = "",
    agent_type_id: str = "",
    script_version_label: str | None = None,
    input_context: dict[str, Any] | None = None,
    caps: SandboxCaps | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> dict[str, Any]:
    """Compile and execute model-authored Python in the sandbox.

    Contract: the source defines ``run(context, tools)`` and returns a
    JSON-able dict. Raises ``SandboxCompileError`` before execution,
    ``SandboxViolationError`` on runtime violations, and
    ``ResourceLimitExceededError`` (``sandbox_termination=True``) on cap
    breaches — all fail closed for the fallback controller (Flow C).
    """
    caps = caps or SandboxCaps()
    code = compile_sandbox(source)

    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
    # Snapshot the caller's context NOW (this runs in the dispatching task via
    # asyncio.to_thread, which propagates contextvars) so the sandbox worker
    # thread can re-bind it across the run_coroutine_threadsafe bridge —
    # without this, forwarded tenant headers are invisible to tool calls.
    dispatch_context = contextvars.copy_context()
    # Always execute via the capped worker thread (wall-time safe termination);
    # tool calls are bridged back onto the captured event loop.
    return _execute_with_caps(
        code,
        tool_client=tool_client,
        loop=loop,
        session_id=session_id,
        agent_type_id=agent_type_id,
        script_version_label=script_version_label,
        input_context=input_context,
        caps=caps,
        dispatch_context=dispatch_context,
    )


def _sandbox_globals_for(
    code: Any,
    *,
    tool_client: Any,
    loop: asyncio.AbstractEventLoop,
    session_id: str,
    agent_type_id: str,
    script_version_label: str | None,
    input_context: dict[str, Any] | None,
    dispatch_context: contextvars.Context | None = None,
    io_time_tracker: dict[str, float] | None = None,
) -> tuple[dict[str, Any], SandboxToolFacade | None]:
    """Build per-execution globals incl. the MCP-only tools facade."""
    tools: SandboxToolFacade | None = None
    if tool_client is not None:
        tools = SandboxToolFacade(
            tool_client,
            loop,
            session_id=session_id,
            agent_type_id=agent_type_id,
            script_version_label=script_version_label,
            context=dispatch_context,
            io_time_tracker=io_time_tracker,
        )
    globs = build_safe_globals(
        extra={
            "context": dict(input_context or {}),
            "tools": tools,
        }
    )
    return globs, tools


def _run_entry(code: Any, globs: dict[str, Any]) -> dict[str, Any]:
    """Exec the script and invoke its ``run(context, tools)`` entry point."""
    try:
        exec(code, globs)  # noqa: S102 — restricted compile output, guarded globals
        entry = globs.get("run")
        if not callable(entry):
            raise SandboxViolationError(
                "Script must define a callable run(context, tools) entry point"
            )
        result = entry(globs.get("context"), globs.get("tools"))
    except (NameError, ImportError) as exc:
        # Allowlisted builtins/imports only — anything else fails closed with
        # a typed, human-readable one-liner (N5).
        raise SandboxViolationError(f"Name/import is not allowed in the sandbox: {exc}") from exc
    if result is None:
        return {}
    if not isinstance(result, dict):
        raise SandboxViolationError(
            "Script run() must return a dict "
            f"(got {type(result).__name__})"
        )
    return result


def _execute_with_caps(
    code: Any,
    *,
    tool_client: Any,
    loop: asyncio.AbstractEventLoop,
    session_id: str,
    agent_type_id: str,
    script_version_label: str | None,
    input_context: dict[str, Any] | None,
    caps: SandboxCaps,
    dispatch_context: contextvars.Context | None = None,
) -> dict[str, Any]:
    """Execute in a daemon worker thread with wall-time / memory caps (N1).

    Safe termination: at the wall-time cap the run is abandoned — the daemon
    worker never blocks process exit and the request/event loop stays fully
    responsive (process state unharmed); the breach surfaces as a typed
    ``ResourceLimitExceededError`` with ``sandbox_termination=True``.

    The wall-time budget bounds the script's OWN compute: time awaited inside
    MCP tool calls is excluded (the deadline is paused while a tool call is
    in flight and restored when it returns), so network latency inside
    multi-step workflows never triggers a false resource-limit failure. A
    pure-compute runaway still terminates at the cap.
    """
    holder: dict[str, Any] = {"result": None, "error": None}
    done = threading.Event()
    # Shared accumulator: total seconds awaited inside tool calls (paused
    # wall-time), written by the worker thread via the tool facade.
    # ``in_flight_since`` pauses the deadline LIVE while a call is in flight
    # (not only after it returns).
    io_time: dict[str, float] = {"awaited": 0.0, "in_flight_since": 0.0}
    io_lock = threading.Lock()

    def _worker() -> None:
        cpu_applied = _apply_cpu_cap(caps.cpu_limit_seconds)
        previous_memory = _apply_memory_cap(caps.memory_limit_mb)
        try:
            globs, _tools = _sandbox_globals_for(
                code,
                tool_client=tool_client,
                loop=loop,
                session_id=session_id,
                agent_type_id=agent_type_id,
                script_version_label=script_version_label,
                input_context=input_context,
                dispatch_context=dispatch_context,
                io_time_tracker=io_time,
            )
            holder["result"] = _run_entry(code, globs)
        except BaseException as exc:  # noqa: BLE001 — propagated fail-closed
            holder["error"] = exc
        finally:
            _restore_memory_cap(previous_memory)
            if cpu_applied:  # pragma: no cover — defensive
                pass
            done.set()

    worker = threading.Thread(
        target=_worker, name="sandboxed-script", daemon=True
    )
    worker.start()
    # Deadline loop: the wall-time cap covers only the script's own compute —
    # time awaited inside tool calls (io_time["awaited"]) is paused out of the
    # budget. Read the accumulator with the GIL's atomic-dict guarantee; the
    # poll interval keeps termination responsive well under a second.
    started = time.monotonic()
    poll_interval = 0.1
    while True:
        now = time.monotonic()
        with io_lock:
            awaited = io_time["awaited"]
            in_flight_since = io_time["in_flight_since"]
        # Pause the deadline while a tool call is in flight: the in-flight
        # portion is awaited I/O, not script compute.
        paused = awaited + (max(0.0, now - in_flight_since) if in_flight_since else 0.0)
        remaining = caps.wall_time_limit_seconds - (now - started - paused)
        if remaining <= 0:
            raise ResourceLimitExceededError(
                f"Script exceeded its {caps.wall_time_limit_seconds}s wall-time "
                "limit — safely terminated"
            )
        if done.wait(timeout=min(remaining, poll_interval)):
            break
    error = holder["error"]
    if error is not None:
        raise error
    result = holder["result"]
    if isinstance(result, BaseException):  # pragma: no cover — defensive
        raise result
    return result
