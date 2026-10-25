"""Software 3.0 script framework components (Agent Runtime).

Compiler, runner, verification engine, fallback controller, repair loop and
the declarative step-graph schema. There are no execution modes: dispatch is
script-first with unconditional LLM fallback. All registry access goes through
Control Center internal APIs; all tool calls go through Communication Hub.
"""
from app.agent_runtime.scripts.compiler import CompilationError, ScriptCompiler
from app.agent_runtime.scripts.schemas import StepGraph
from app.agent_runtime.scripts.cc_client import (
    ScriptRegistryClient,
    ScriptRegistryClientError,
)
from app.agent_runtime.scripts.fallback import FallbackController
from app.agent_runtime.scripts.repair import MAX_REPAIR_ATTEMPTS, RepairLoop
from app.agent_runtime.scripts.runner import (
    ExecutionError,
    OutputValidationFailure,
    SchemaMismatch,
    ScriptExecutionError,
    ScriptRunner,
)

__all__ = [
    "CompilationError",
    "ScriptCompiler",
    "StepGraph",
    "ScriptRegistryClient",
    "ScriptRegistryClientError",
    "FallbackController",
    "MAX_REPAIR_ATTEMPTS",
    "RepairLoop",
    "ExecutionError",
    "OutputValidationFailure",
    "SchemaMismatch",
    "ScriptExecutionError",
    "ScriptRunner",
]
