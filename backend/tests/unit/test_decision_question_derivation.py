"""Unit tests for the decision-question derivation feature.

Covers:
- AgentDataType enum values with/without per-value descriptions (schema
  validation + legacy plain-string backward compatibility)
- ``derive_questions_from_output_type`` rules: enum → choice (verbatim
  criteria_options incl. descriptions), number → score (1–5 rubric),
  string → free-form choice, boolean → noul; required flags; ordering
- manual questions override derivation; no output type → no derived
- ``build_state`` 1:1 pass-through when no preset (pinned)
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.db.models.decision_tools import DecisionQuestionType, DecisionTool
from app.db.models.agent_data_type import AgentDataType
from app.schemas.data_types import (
    DataTypeFieldCreate,
    DataTypeFieldResponse,
    enum_descriptions,
    enum_plain_values,
)
from app.schemas.decision_tools import DecisionToolCreate
from app.services.system_one.decision_tool_service import (
    DEFAULT_SCORE_RUBRIC,
    _derive_question_specs,
    derive_questions_from_output_type,
)


# ── Data type schema: enum values with/without descriptions ──────────────


class TestEnumValueDescriptions:
    def test_plain_string_values_still_valid(self):
        field = DataTypeFieldCreate(
            name="status", type="enum", enum_values=["yes", "no"]
        )
        assert enum_plain_values(field.enum_values) == ["yes", "no"]
        assert enum_descriptions(field.enum_values) == {"yes": None, "no": None}

    def test_described_object_values_valid(self):
        field = DataTypeFieldCreate(
            name="status",
            type="enum",
            enum_values=[
                {"value": "yes", "description": "approve the request"},
                {"value": "no"},
            ],
        )
        assert enum_plain_values(field.enum_values) == ["yes", "no"]
        assert enum_descriptions(field.enum_values) == {
            "yes": "approve the request",
            "no": None,
        }

    def test_mixed_shapes_valid(self):
        field = DataTypeFieldCreate(
            name="status",
            type="enum",
            enum_values=["maybe", {"value": "yes", "description": "ok"}],
        )
        assert enum_plain_values(field.enum_values) == ["maybe", "yes"]

    def test_empty_enum_value_rejected(self):
        with pytest.raises(ValidationError):
            DataTypeFieldCreate(
                name="status", type="enum", enum_values=["", {"value": "x"}]
            )

    def test_duplicate_enum_value_rejected_across_shapes(self):
        with pytest.raises(ValidationError):
            DataTypeFieldCreate(
                name="status",
                type="enum",
                enum_values=["x", {"value": "x", "description": "dup"}],
            )

    def test_response_schema_parses_legacy_json(self):
        """Legacy rows (plain strings in the JSON column) still parse."""
        resp = DataTypeFieldResponse(
            name="status",
            type="enum",
            enum_values=["yes", "no"],
        )
        assert enum_plain_values(resp.enum_values) == ["yes", "no"]

    def test_response_schema_parses_described_json(self):
        resp = DataTypeFieldResponse(
            name="status",
            type="enum",
            enum_values=[{"value": "yes", "description": "ok"}],
        )
        assert enum_descriptions(resp.enum_values) == {"yes": "ok"}


# ── Derivation rules ──────────────────────────────────────────────────────


def _output_type(fields: list[dict]) -> AgentDataType:
    return AgentDataType(
        id=__import__("uuid").uuid4(),
        name="out",
        slug="out",
        fields=fields,
    )


def _tool(output_type: AgentDataType | None, questions=None) -> DecisionTool:
    tool = DecisionTool(
        name="t",
        output_data_type=output_type,
        output_data_type_id=output_type.id if output_type else None,
    )
    if questions:
        tool.questions = list(questions)
    return tool


class TestDerivation:
    def test_all_field_types(self):
        out = _output_type(
            [
                {
                    "name": "status",
                    "type": "enum",
                    "enum_values": [
                        {"value": "approve", "description": "green light"},
                        "reject",
                    ],
                },
                {"name": "rating", "type": "number"},
                {"name": "notes", "type": "string"},
                {"name": "flagged", "type": "boolean"},
            ]
        )
        questions = derive_questions_from_output_type(None, _tool(out))
        assert [q.question_key for q in questions] == [
            "status", "rating", "notes", "flagged",
        ]

        by_key = {q.question_key: q for q in questions}
        # enum → choice with verbatim criteria_options
        status = by_key["status"]
        assert status.question_type is DecisionQuestionType.choice
        assert status.criteria_options == {
            "approve": "green light",
            "reject": "reject",  # missing description → value itself
        }
        # number → score with the default 1–5 rubric
        rating = by_key["rating"]
        assert rating.question_type is DecisionQuestionType.score
        assert rating.criteria_options == DEFAULT_SCORE_RUBRIC
        assert len(rating.criteria_options) == 5
        # string → free-form choice
        notes = by_key["notes"]
        assert notes.question_type is DecisionQuestionType.choice
        assert notes.criteria_options == {}
        # boolean → noul
        flagged = by_key["flagged"]
        assert flagged.question_type is DecisionQuestionType.noul
        assert flagged.criteria_options is None

    def test_required_flags_and_ordering(self):
        out = _output_type(
            [
                {"name": "a", "type": "string", "required": True},
                {"name": "b", "type": "string", "required": False},
            ]
        )
        questions = derive_questions_from_output_type(None, _tool(out))
        assert [q.is_required for q in questions] == [True, False]
        assert [q.ordering for q in questions] == [0, 1]

    def test_manual_questions_override(self):
        """The override rule is exercised at the engine level; here we pin
        that the derivation helper itself is only consulted when the tool
        has zero manual questions (see engine test)."""
        tool = _tool(_output_type([{"name": "a", "type": "string"}]))
        assert len(derive_questions_from_output_type(None, tool)) == 1

    def test_no_output_type_yields_no_derived_questions(self):
        assert derive_questions_from_output_type(None, _tool(None)) == []

    def test_odd_field_shapes_tolerated(self):
        assert _derive_question_specs(None) == []
        assert _derive_question_specs(["not-a-dict", {"no_name": 1}]) == []

    def test_create_payload_allows_zero_questions(self):
        payload = DecisionToolCreate(name="q-free")
        assert payload.questions == []


# ── Engine: build_state 1:1 pin (existing behavior) ──────────────────────


class TestBuildStatePinned:
    def test_no_preset_returns_input_verbatim(self):
        from app.services.system_one.decision_engine import (
            DecisionExecutionEngine,
        )

        source = {"situation": "outage", "severity": "high"}
        state = DecisionExecutionEngine.build_state(None, source)
        assert state == source
        assert state is not source  # defensive copy

    def test_legacy_agent_data_preset_row_ignored(self):
        from app.services.system_one.decision_engine import (
            DecisionExecutionEngine,
        )

        # agent_data source is retired: the legacy row is skipped with a
        # warning (input-only mapping now); execution must not fail.
        state = DecisionExecutionEngine.build_state(
            {"ctx": {"source": "agent_data", "key": "context"}},
            {"situation": "x", "agent_data": {"context": "prior run"}},
        )
        assert state == {}
