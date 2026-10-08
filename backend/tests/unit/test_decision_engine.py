"""Unit tests for the System One decision engine (pure logic, no DB).

Covers:
- confidence gate boundaries (exact act/confirm thresholds → act/confirm/escalate)
- noul abs(2n-1) effective-confidence derivation
- state preset mapping (input + agent_data sources, missing-key errors)
- answer normalization (typed values, probabilities, confidence, legend,
  required-answer enforcement)
"""
from __future__ import annotations

import pytest

from app.db.models.decision_tools import DecisionQuestionType, DecisionToolQuestion
from app.db.models.results import DecisionOutcome
from app.services.system_one.decision_engine import (
    DecisionExecutionEngine,
    compute_confidence_gate,
    derive_effective_confidence,
)
from app.services.system_one.decision_tool_service import DecisionToolValidationError

# ── Confidence gate boundaries ────────────────────────────────────────────


class TestConfidenceGate:
    @pytest.mark.parametrize(
        "confidence,act,confirm,expected",
        [
            (0.9, 0.9, 0.7, DecisionOutcome.act),  # exactly at act threshold
            (0.95, 0.9, 0.7, DecisionOutcome.act),
            (1.0, 0.9, 0.7, DecisionOutcome.act),
            (0.89, 0.9, 0.7, DecisionOutcome.confirm),  # just below act
            (0.7, 0.9, 0.7, DecisionOutcome.confirm),  # exactly at confirm
            (0.71, 0.9, 0.7, DecisionOutcome.confirm),
            (0.69, 0.9, 0.7, DecisionOutcome.escalate),  # just below confirm
            (0.0, 0.9, 0.7, DecisionOutcome.escalate),
            # identical thresholds: >= threshold always acts
            (0.8, 0.8, 0.8, DecisionOutcome.act),
            (0.79, 0.8, 0.8, DecisionOutcome.escalate),
        ],
    )
    def test_gate_boundaries(self, confidence, act, confirm, expected):
        assert compute_confidence_gate(confidence, act, confirm) is expected


# ── Noul effective-confidence derivation ──────────────────────────────────


class TestNoulDerivation:
    @pytest.mark.parametrize(
        "noul,expected",
        [
            (0.0, 1.0),  # extreme → maximal confidence
            (1.0, 1.0),
            (0.5, 0.0),  # midpoint → maximal uncertainty
            (0.75, 0.5),
            (0.25, 0.5),
        ],
    )
    def test_noul_abs_2n_minus_1(self, noul, expected):
        assert derive_effective_confidence({"noul": noul}) == pytest.approx(expected)

    def test_explicit_confidence_wins(self):
        assert derive_effective_confidence({"confidence": 0.42}) == pytest.approx(0.42)

    def test_noul_with_confidence_uses_confidence(self):
        assert derive_effective_confidence(
            {"noul": 1.0, "confidence": 0.3}
        ) == pytest.approx(0.3)

    def test_empty_answer_defaults_to_zero(self):
        assert derive_effective_confidence({}) == 0.0


# ── State preset mapping ──────────────────────────────────────────────────


class TestStatePreset:
    def test_no_preset_returns_input_copy(self):
        inp = {"a": 1}
        state = DecisionExecutionEngine.build_state(None, inp)
        assert state == {"a": 1}
        state["a"] = 2
        assert inp["a"] == 1  # copy, not the same dict

    def test_empty_preset_returns_input_copy(self):
        assert DecisionExecutionEngine.build_state({}, {"a": 1}) == {"a": 1}

    def test_input_source_mapping(self):
        preset = {"risk": {"source": "input", "key": "risk_level"}}
        assert DecisionExecutionEngine.build_state(preset, {"risk_level": "high"}) == {
            "risk": "high"
        }

    def test_agent_data_source_mapping(self):
        preset = {"history": {"source": "agent_data", "key": "customer_history"}}
        state = DecisionExecutionEngine.build_state(
            preset, {"agent_data": {"customer_history": [1, 2, 3]}}
        )
        assert state == {"history": [1, 2, 3]}

    def test_mixed_sources(self):
        preset = {
            "risk": {"source": "input", "key": "risk_level"},
            "history": {"source": "agent_data", "key": "customer_history"},
        }
        state = DecisionExecutionEngine.build_state(
            preset,
            {"risk_level": "low", "agent_data": {"customer_history": "clean"}},
        )
        assert state == {"risk": "low", "history": "clean"}

    def test_missing_input_key_raises(self):
        preset = {"risk": {"source": "input", "key": "risk_level"}}
        with pytest.raises(DecisionToolValidationError) as exc:
            DecisionExecutionEngine.build_state(preset, {"other": 1})
        assert "risk_level" in str(exc.value)

    def test_missing_agent_data_key_raises(self):
        preset = {"history": {"source": "agent_data", "key": "customer_history"}}
        with pytest.raises(DecisionToolValidationError):
            DecisionExecutionEngine.build_state(preset, {"agent_data": {}})

    def test_agent_data_absent_entirely_raises(self):
        preset = {"history": {"source": "agent_data", "key": "customer_history"}}
        with pytest.raises(DecisionToolValidationError):
            DecisionExecutionEngine.build_state(preset, {})

    def test_multiple_errors_collected(self):
        preset = {
            "a": {"source": "input", "key": "missing_in"},
            "b": {"source": "agent_data", "key": "missing_ad"},
        }
        with pytest.raises(DecisionToolValidationError) as exc:
            DecisionExecutionEngine.build_state(preset, {})
        assert "missing_in" in str(exc.value)
        assert "missing_ad" in str(exc.value)


# ── Answer normalization ──────────────────────────────────────────────────


def _question(key: str, qtype: DecisionQuestionType, required: bool = True):
    return DecisionToolQuestion(
        ordering=0, question_key=key, question_type=qtype, is_required=required
    )


class TestNormalizeAnswers:
    def test_choice_answer_typed(self):
        raw = {
            "answers": {
                "approve": {
                    "type": "choice",
                    "choice": "yes",
                    "probabilities": {"yes": 0.9, "no": 0.1},
                    "confidence": 0.92,
                }
            }
        }
        answers = DecisionExecutionEngine.normalize_answers(
            raw, [_question("approve", DecisionQuestionType.choice)]
        )
        a = answers["approve"]
        assert a["value"] == "yes"
        assert a["choice"] == "yes"
        assert a["probabilities"] == {"yes": 0.9, "no": 0.1}
        assert a["confidence"] == pytest.approx(0.92)
        assert a["effective_confidence"] == pytest.approx(0.92)

    def test_score_answer_with_legend(self):
        raw = {
            "answers": {
                "quality": {
                    "type": "score",
                    "score": 4,
                    "legend": {"1": "poor", "5": "excellent"},
                    "confidence": 0.8,
                }
            }
        }
        answers = DecisionExecutionEngine.normalize_answers(
            raw, [_question("quality", DecisionQuestionType.score)]
        )
        a = answers["quality"]
        assert a["value"] == 4
        assert a["score"] == 4
        assert a["legend"] == {"1": "poor", "5": "excellent"}

    def test_noul_answer_derives_effective_confidence(self):
        raw = {"answers": {"binary_check": {"type": "noul", "noul": 0.9}}}
        answers = DecisionExecutionEngine.normalize_answers(
            raw, [_question("binary_check", DecisionQuestionType.noul)]
        )
        a = answers["binary_check"]
        assert a["noul"] == pytest.approx(0.9)
        assert "confidence" not in a  # provider supplies none for noul
        assert a["effective_confidence"] == pytest.approx(0.8)

    def test_value_fallback_across_type_keys(self):
        # Provider returned the value under a different type key — still picked up.
        raw = {"answers": {"q": {"type": "choice", "score": 3}}}
        answers = DecisionExecutionEngine.normalize_answers(
            raw, [_question("q", DecisionQuestionType.choice)]
        )
        assert answers["q"]["value"] == 3

    def test_missing_required_answer_raises(self):
        raw = {"answers": {}}
        with pytest.raises(Exception, match="approve"):
            DecisionExecutionEngine.normalize_answers(
                raw, [_question("approve", DecisionQuestionType.choice)]
            )

    def test_missing_optional_answer_skipped(self):
        raw = {"answers": {}}
        answers = DecisionExecutionEngine.normalize_answers(
            raw, [_question("opt", DecisionQuestionType.choice, required=False)]
        )
        assert answers == {}

    def test_answers_stable_per_question_key(self):
        raw = {
            "answers": {
                "q2": {"type": "noul", "noul": 1.0},
                "q1": {"type": "noul", "noul": 0.0},
            }
        }
        questions = [
            _question("q1", DecisionQuestionType.noul),
            _question("q2", DecisionQuestionType.noul),
        ]
        answers = DecisionExecutionEngine.normalize_answers(raw, questions)
        # mapped back by question key, regardless of provider response order
        assert answers["q1"]["noul"] == 0.0
        assert answers["q2"]["noul"] == 1.0
