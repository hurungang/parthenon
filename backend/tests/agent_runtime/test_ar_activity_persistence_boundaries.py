"""Structural tests — Agent Runtime persistence boundaries for the persisted
conversation activity state (persistent-agent-activity-state, tasks 3.2/3.3).

Guards (source-level, no DB):

1. AR never touches the database directly — the ``app/agent_runtime`` tree
   contains no DB session/model imports or engine creation.
2. AR never calls the CC activity endpoints directly — activity persistence
   flows AR → CH → CC only.
3. The conversational executor's transition ordering: every
   ``waiting_for_human`` pause is followed (in source order) by either a
   ``thinking`` resume transition or a terminal ``timeout_or_failed``.
4. The in-process resume registry (``conversation_resume``) remains
   process-local — complementing, not replaced by, the persisted state.
"""
from __future__ import annotations

import pathlib
import re

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]
AR_TREE = BACKEND_ROOT / "app" / "agent_runtime"
EXECUTOR = BACKEND_ROOT / "app" / "services" / "agents" / "runtime_executor.py"

DB_ACCESS_SYMBOLS = (
    "from app.db.session",
    "from app.db.models",
    "import app.db.session",
    "import app.db.models",
    "AsyncSessionLocal",
    "create_async_engine",
    "sessionmaker(",
)

CC_ACTIVITY_ENDPOINT_SYMBOLS = (
    "/internal/data/conversations",
    "activity_store",
    "ConversationActivityStore",
)


def _python_sources(tree: pathlib.Path) -> list[pathlib.Path]:
    return sorted(tree.rglob("*.py"))


class TestARHasNoDatabaseAccess:
    """Task 3.3 — AR's data access is CH/CC-http only; never the DB."""

    def test_ar_tree_has_no_db_imports_or_engines(self) -> None:
        offenders: list[str] = []
        for path in _python_sources(AR_TREE):
            source = path.read_text()
            for symbol in DB_ACCESS_SYMBOLS:
                if symbol in source:
                    offenders.append(f"{path.relative_to(BACKEND_ROOT)}: {symbol}")
        assert not offenders, (
            "Agent Runtime must never access the database directly "
            "(only Control Center connects to the DB):\n" + "\n".join(offenders)
        )

    def test_ar_never_calls_cc_activity_endpoints(self) -> None:
        offenders: list[str] = []
        for path in _python_sources(AR_TREE):
            source = path.read_text()
            for symbol in CC_ACTIVITY_ENDPOINT_SYMBOLS:
                if symbol in source:
                    offenders.append(f"{path.relative_to(BACKEND_ROOT)}: {symbol}")
        assert not offenders, (
            "Agent Runtime must not call Control Center activity endpoints "
            "directly — activity transitions flow AR → CH → CC only:\n"
            + "\n".join(offenders)
        )

    def test_ar_data_client_egresses_via_internal_http_client(self) -> None:
        source = (AR_TREE / "data_client.py").read_text()
        assert "internal_httpx_client" in source, (
            "AR's data client must use internal_httpx_client (signed tenant "
            "headers, single egress mechanism) — never raw httpx clients"
        )

    def test_resume_registry_remains_process_local(self) -> None:
        """The conversation_resume registry stays the in-process pause/resume
        mechanism — complemented (not replaced) by the persisted state."""
        source = (AR_TREE / "conversation_resume.py").read_text()
        # No DB, no HTTP: a process-local registry only.
        for symbol in DB_ACCESS_SYMBOLS + ("httpx", "AsyncClient"):
            assert symbol not in source, (
                f"conversation_resume must stay process-local ({symbol})"
            )


class TestTransitionOrdering:
    """Task 3.2 — waiting_for_human is followed by thinking (resume) or a
    terminal timeout_or_failed."""

    def test_wait_transition_followed_by_resume_or_timeout(self) -> None:
        executor_source = EXECUTOR.read_text()
        for match in re.finditer(r'"status": "waiting_for_human"', executor_source):
            # Find the end of the emit call, then the next transition emitted.
            emit_end = executor_source.find("})", match.start())
            assert emit_end != -1
            next_transition = re.compile(r'"status": "(\w+)"').search(
                executor_source, emit_end
            )
            assert next_transition is not None, (
                "a waiting_for_human pause must be followed by a further "
                "transition"
            )
            assert next_transition.group(1) in ("thinking", "timeout_or_failed"), (
                "waiting_for_human must be followed by thinking (resume) or a "
                f"terminal timeout_or_failed — got {next_transition.group(1)}"
            )

    def test_pause_carries_pending_intervention_marker(self) -> None:
        """Task 3.1 — every waiting_for_human transition carries the
        intervention marker so CC can stamp the persisted record."""
        executor_source = EXECUTOR.read_text()
        count_marker = executor_source.count('"pending_intervention"')
        count_pause = executor_source.count('"status": "waiting_for_human"')
        assert count_pause > 0
        assert count_marker >= count_pause, (
            "every waiting_for_human emission must carry pending_intervention"
        )

    def test_no_secret_material_in_status_events(self) -> None:
        """No token/credential fields in any emitted status event."""
        executor_source = EXECUTOR.read_text()
        forbidden = ("token", "credential", "password", "api_key", "secret")
        for match in re.finditer(r'\{"status":.*?\}\)', executor_source, re.DOTALL):
            payload = match.group(0).lower()
            for symbol in forbidden:
                assert symbol not in payload, (
                    f"status event must never carry secret material ({symbol})"
                )
