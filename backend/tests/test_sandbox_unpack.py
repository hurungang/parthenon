"""Regression: _unpack_sequence_ guard for direct `a, b = item` unpacking."""
import textwrap

import pytest

from app.agent_runtime.scripts.sandbox import (
    SandboxCompileError,
    compile_sandbox,
    run_sandboxed_python,
)


def test_direct_tuple_unpacking_allowed():
    """Authored scripts use `a, b = item` — the sandbox must provide the
    _unpack_sequence_ guard (was a SandboxViolationError: name not defined)."""
    source = textwrap.dedent("""
        def run(context, tools):
            pair = (context['a'], context['b'])
            x, y = pair
            return {'result': x + y}
    """)
    compile_sandbox(source)
    result = run_sandboxed_python(source, input_context={"a": 2, "b": 3})
    assert result == {"result": 5}


def test_unpack_length_mismatch_raises():
    source = textwrap.dedent("""
        def run(context, tools):
            x, y = (1, 2, 3)
            return {'result': x}
    """)
    compile_sandbox(source)
    with pytest.raises(Exception):
        run_sandboxed_python(source, input_context={})
