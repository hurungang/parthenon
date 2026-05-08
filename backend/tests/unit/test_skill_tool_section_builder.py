"""Unit tests for assemble_tool_section — the function that builds the
read-only Tool Section appended to skill agent instructions when tool
bindings are present (enhance-mcp-hub-skills-sops change).

Covers:
- Empty input → empty string (no heading rendered)
- Single tool: heading presence, name code-formatting, description, schema block
- Edge cases: empty description, null schema (no null serialised), deterministic output
- Multiple tools: all present, input order preserved, heading exactly once
- Schema block: only rendered for tools that have one; valid JSON in output
"""
from __future__ import annotations

import json

from app.api.v1.skills import _ToolRecord, assemble_tool_section


# ── Empty input ────────────────────────────────────────────────────────────────


class TestAssembleToolSectionEmpty:
    def test_empty_list_returns_empty_string(self):
        assert assemble_tool_section([]) == ""

    def test_empty_result_contains_no_heading(self):
        result = assemble_tool_section([])
        assert "## Tools" not in result


# ── Single tool ────────────────────────────────────────────────────────────────


class TestAssembleToolSectionSingleTool:
    def test_heading_present(self):
        tool = _ToolRecord(name="search", description=None, input_schema=None)
        result = assemble_tool_section([tool])
        assert "## Tools" in result

    def test_tool_name_is_code_formatted(self):
        tool = _ToolRecord(name="my_tool", description=None, input_schema=None)
        result = assemble_tool_section([tool])
        assert "`my_tool`" in result

    def test_tool_name_appears_under_subheading(self):
        tool = _ToolRecord(name="exact_tool_name", description=None, input_schema=None)
        result = assemble_tool_section([tool])
        assert "### `exact_tool_name`" in result

    def test_description_included_when_provided(self):
        tool = _ToolRecord(name="search", description="Searches the web", input_schema=None)
        result = assemble_tool_section([tool])
        assert "Searches the web" in result

    def test_empty_description_does_not_cause_error(self):
        tool = _ToolRecord(name="tool_a", description="", input_schema=None)
        result = assemble_tool_section([tool])
        assert "tool_a" in result

    def test_no_schema_omits_input_schema_block(self):
        tool = _ToolRecord(name="search", description="Desc", input_schema=None)
        result = assemble_tool_section([tool])
        assert "Input Schema" not in result
        assert "```json" not in result

    def test_no_schema_does_not_produce_null_in_output(self):
        tool = _ToolRecord(name="search", description="Desc", input_schema=None)
        result = assemble_tool_section([tool])
        assert "null" not in result

    def test_schema_block_present_when_schema_provided(self):
        schema = {"type": "object", "properties": {"query": {"type": "string"}}}
        tool = _ToolRecord(name="search", description="Desc", input_schema=schema)
        result = assemble_tool_section([tool])
        assert "Input Schema" in result
        assert "```json" in result

    def test_schema_content_is_valid_json(self):
        schema = {"type": "object", "properties": {"query": {"type": "string"}}}
        tool = _ToolRecord(name="search", description="Desc", input_schema=schema)
        result = assemble_tool_section([tool])
        start = result.index("```json\n") + len("```json\n")
        end = result.index("\n```", start)
        parsed = json.loads(result[start:end])
        assert parsed == schema

    def test_schema_content_matches_original_exactly(self):
        schema = {"action": "search", "max_results": 10, "filters": ["a", "b"]}
        tool = _ToolRecord(name="tool", description=None, input_schema=schema)
        result = assemble_tool_section([tool])
        start = result.index("```json\n") + len("```json\n")
        end = result.index("\n```", start)
        assert json.loads(result[start:end]) == schema


# ── Multiple tools ─────────────────────────────────────────────────────────────


class TestAssembleToolSectionMultipleTools:
    def test_all_tools_present(self):
        tools = [
            _ToolRecord(name="tool_a", description="First", input_schema=None),
            _ToolRecord(name="tool_b", description="Second", input_schema=None),
            _ToolRecord(name="tool_c", description="Third", input_schema=None),
        ]
        result = assemble_tool_section(tools)
        assert "tool_a" in result
        assert "tool_b" in result
        assert "tool_c" in result

    def test_tools_appear_in_input_order(self):
        tools = [
            _ToolRecord(name="aaa", description=None, input_schema=None),
            _ToolRecord(name="bbb", description=None, input_schema=None),
        ]
        result = assemble_tool_section(tools)
        assert result.index("aaa") < result.index("bbb")

    def test_heading_appears_exactly_once(self):
        tools = [
            _ToolRecord(name="tool_a", description="A", input_schema=None),
            _ToolRecord(name="tool_b", description="B", input_schema=None),
        ]
        result = assemble_tool_section(tools)
        assert result.count("## Tools") == 1

    def test_schema_block_only_for_tools_with_schema(self):
        tools = [
            _ToolRecord(name="tool_a", description="A", input_schema={"type": "object"}),
            _ToolRecord(name="tool_b", description="B", input_schema=None),
        ]
        result = assemble_tool_section(tools)
        assert result.count("```json") == 1  # only tool_a has schema

    def test_output_is_deterministic(self):
        tools = [
            _ToolRecord(name="tool_a", description="Desc", input_schema={"k": "v"}),
        ]
        assert assemble_tool_section(tools) == assemble_tool_section(tools)

    def test_descriptions_for_all_tools(self):
        tools = [
            _ToolRecord(name="tool_a", description="Alpha description", input_schema=None),
            _ToolRecord(name="tool_b", description="Beta description", input_schema=None),
        ]
        result = assemble_tool_section(tools)
        assert "Alpha description" in result
        assert "Beta description" in result
