"""Unit tests for decision tool save validation and state auto-match.

Covers (Task 1 — save error fix):
- drafts save cleanly: disabled + no data types passes readiness
- enabling without input/output data types is rejected with a CLEAR,
  actionable message (naming the missing pieces)
- the schema accepts omitted/empty questions (optional) and a null state
  preset

Covers (Task 2 — state preset redesign):
- ``StatePresetSource`` is input-only: an ``agent_data`` payload is
  rejected with a clear validation error (legacy rows)
- ``resolve_state_mapping`` auto-match: same-named keys match silently,
  rename mappings win, unmatched keys are reported for the UI mapper
- ``_validate_state_preset`` skips legacy agent_data rows with a warning
  instead of failing (drop-on-next-save migration path)
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.decision_tools import DecisionToolCreate
from app.services.system_one.decision_tool_service import (
    DecisionToolValidationError,
    _validate_readiness,
    resolve_state_mapping,
)
from app.services.system_one.decision_tool_service import (
    DecisionToolService as Service,
)


# ── Task 1: readiness gate ────────────────────────────────────────────────


class TestReadinessGate:
    def test_disabled_draft_without_types_saves_cleanly(self):
        # The exact payload the UI sends for a new draft: disabled, no
        # types, no questions — must NOT raise.
        _validate_readiness("my-tool", enabled=False,
                            input_data_type_id=None, output_data_type_id=None)

    def test_enabled_with_both_types_passes(self):
        _validate_readiness("my-tool", enabled=True,
                            input_data_type_id=object(), output_data_type_id=object())

    def test_enabled_without_types_rejected_with_clear_error(self):
        with pytest.raises(DecisionToolValidationError) as exc:
            _validate_readiness("my-tool", enabled=True,
                                input_data_type_id=None, output_data_type_id=None)
        msg = "; ".join(exc.value.errors)
        assert "my-tool" in msg
        assert "input data type" in msg and "output data type" in msg
        assert "disable" in msg  # actionable escape hatch

    def test_enabled_with_only_output_type_names_the_missing_input(self):
        with pytest.raises(DecisionToolValidationError) as exc:
            _validate_readiness("my-tool", enabled=True,
                                input_data_type_id=None, output_data_type_id=object())
        msg = "; ".join(exc.value.errors)
        assert "input data type is required" in msg


class TestCreateSchema:
    def _payload(self, **overrides):
        base = {
            "name": "approve-loan",
            "purpose": "Decide loans",
            "enabled": False,
            "questions": [],
            "state_preset": None,
        }
        base.update(overrides)
        return base

    def test_questions_omitted_and_empty_both_accepted(self):
        assert DecisionToolCreate(**self._payload(questions=[])).questions == []
        payload = self._payload()
        payload.pop("questions")
        assert DecisionToolCreate(**payload).questions == []

    def test_null_state_preset_accepted(self):
        assert DecisionToolCreate(**self._payload()).state_preset is None

    def test_agent_data_source_rejected_with_clear_error(self):
        with pytest.raises(ValidationError) as exc:
            DecisionToolCreate(**self._payload(
                state_preset={"history": {"source": "agent_data", "key": "h"}}))
        # the error names the offending source value
        assert "agent_data" in str(exc.value)
        assert "input" in str(exc.value)


# ── Task 2: state mapping auto-match helper ──────────────────────────────


class TestResolveStateMapping:
    def test_auto_match_silent_for_same_named_keys(self):
        result = resolve_state_mapping(
            None, ["amount", "tier"], ["amount", "tier", "other"]
        )
        assert result == {"matched": {"amount": "amount", "tier": "tier"},
                          "unmatched": []}

    def test_unmatched_keys_reported_for_ui_mapper(self):
        result = resolve_state_mapping(None, ["aaa"], ["bbb"])
        assert result == {"matched": {}, "unmatched": ["aaa"]}

    def test_explicit_rename_mapping_wins(self):
        result = resolve_state_mapping(
            {"aaa": {"source": "input", "key": "bbb"}}, ["aaa"], ["bbb"]
        )
        assert result == {"matched": {"aaa": "bbb"}, "unmatched": []}

    def test_explicit_mapping_to_unknown_field_is_unmatched(self):
        result = resolve_state_mapping(
            {"aaa": {"source": "input", "key": "nope"}}, ["aaa"], ["bbb"]
        )
        assert result == {"matched": {}, "unmatched": ["aaa"]}

    def test_preset_keys_and_placeholders_dedup_first_seen_order(self):
        result = resolve_state_mapping(
            {"risk": {"source": "input", "key": "risk"}}, ["risk", "amount"],
            ["risk", "amount"],
        )
        assert result["matched"] == {"risk": "risk", "amount": "amount"}
        assert result["unmatched"] == []

    def test_legacy_agent_data_row_treated_as_unmatched_not_crash(self):
        result = resolve_state_mapping(
            {"history": {"source": "agent_data", "key": "h"}}, [], ["amount"]
        )
        assert result == {"matched": {}, "unmatched": ["history"]}

    def test_empty_everything(self):
        assert resolve_state_mapping(None, [], []) == {"matched": {}, "unmatched": []}


# ── Task 2: legacy preset validation tolerance ───────────────────────────


class TestValidateStatePresetLegacy:
    def test_legacy_agent_data_row_skipped_with_warning(self, caplog):
        # Legacy row must NOT fail validation (it is dropped on next save).
        with caplog.at_level("WARNING"):
            Service._validate_state_preset(
                {"history": {"source": "agent_data", "key": "h"}},
                input_type=None,
            )
        assert any("agent_data" in r.message or "legacy" in r.message
                   for r in caplog.records)

    def test_input_mapping_to_unknown_field_still_rejected(self):
        class FakeType:
            name = "Loan Application"
            fields = [{"name": "amount"}]

        with pytest.raises(DecisionToolValidationError):
            Service._validate_state_preset(
                {"risk": {"source": "input", "key": "not_a_field"}},
                input_type=FakeType(),
            )
