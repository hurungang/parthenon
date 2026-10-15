"""Unit tests for the System One decision engine (pure logic, no DB).

Covers:
- confidence gate boundaries (exact act/confirm thresholds → act/confirm/escalate)
- noul abs(2n-1) effective-confidence derivation
- state preset mapping (input-only sources, rename mappings, legacy
  agent_data rows ignored with a warning, missing-key errors)
- answer normalization (typed values, probabilities, confidence, legend,
  required-answer enforcement)
"""
from __future__ import annotations

import uuid

import pytest
from types import SimpleNamespace

from app.db.models.decision_tools import DecisionQuestionType, DecisionToolQuestion
from app.db.models.results import DecisionOutcome
from app.services.system_one.decision_engine import (
    DecisionExecutionEngine,
    DecisionExecutionError,
    compute_confidence_gate,
    derive_effective_confidence,
)
from app.services.system_one.decision_model_availability_service import (
    DecisionModelCatalogueError,
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

    def test_rename_mapping(self):
        # state_key → input property rename: input 'risk_level' surfaces
        # as state key 'risk'.
        preset = {"aaa": {"source": "input", "key": "bbb"}}
        assert DecisionExecutionEngine.build_state(preset, {"bbb": 42}) == {
            "aaa": 42
        }

    def test_legacy_agent_data_row_ignored_with_warning(self):
        # agent_data source is retired: the legacy row is skipped with a
        # warning instead of failing execution; input rows still resolve.
        preset = {
            "history": {"source": "agent_data", "key": "customer_history"},
            "risk": {"source": "input", "key": "risk_level"},
        }
        state = DecisionExecutionEngine.build_state(
            preset, {"risk_level": "low", "agent_data": {"customer_history": "x"}}
        )
        assert state == {"risk": "low"}

    def test_invalid_legacy_row_ignored(self):
        state = DecisionExecutionEngine.build_state(
            {"junk": {"nope": True}}, {"a": 1}
        )
        assert state == {}

    def test_missing_input_key_raises(self):
        preset = {"risk": {"source": "input", "key": "risk_level"}}
        with pytest.raises(DecisionToolValidationError) as exc:
            DecisionExecutionEngine.build_state(preset, {"other": 1})
        assert "risk_level" in str(exc.value)

    def test_multiple_errors_collected(self):
        preset = {
            "a": {"source": "input", "key": "missing_in"},
            "b": {"source": "input", "key": "missing_other"},
        }
        with pytest.raises(DecisionToolValidationError) as exc:
            DecisionExecutionEngine.build_state(preset, {})
        assert "missing_in" in str(exc.value)
        assert "missing_other" in str(exc.value)


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


# ── Multi-provider model resolution (resolve_model_selection) ────────────


def _resolved(provider, availability):
    """Minimal ResolvedDecisionModel stand-in (identity fields only)."""
    return SimpleNamespace(
        provider=provider,
        availability=availability,
        provider_id=provider.id,
        provider_type=provider.provider_type,
        provider_display_name=provider.display_name,
        model_name=availability.model_name,
        availability_id=availability.id,
    )


class _StubCatalogue:
    def __init__(self, resolved=None, error: Exception | None = None):
        self.resolved = resolved
        self.error = error
        self.calls: list[tuple] = []

    async def resolve_selection(self, db, availability_id, tenant_id):
        self.calls.append((availability_id, tenant_id))
        if self.error is not None:
            raise self.error
        return self.resolved

    async def resolve_legacy_default(self, db, provider, model_name):
        self.legacy_calls = (provider, model_name)
        return SimpleNamespace(
            id=uuid.uuid4(), model_name=model_name, is_disabled=False
        )


class _StubProviders:
    def __init__(self, provider):
        self.provider = provider

    async def get_active_provider(self, db, tenant_id, model=None):
        return self.provider, "sk-plaintext"


class _StubTool:
    """DecisionTool stand-in (the unit layer never touches the DB)."""

    def __init__(self, availability_id=None, provider_model="jev-latest"):
        from app.db.models.system_one_provider_config import SystemOneProviderType

        self.decision_model_availability_id = availability_id
        self.provider_model = provider_model
        self.tenant_id = None
        self.enabled = True
        self.name = "unit_tool"
        self.state_preset = None
        self.questions = []
        self.act_threshold = 0.9
        self.confirm_threshold = 0.7
        self.provider_type = SystemOneProviderType.typesafe


def _provider(enabled=True):
    from app.db.models.system_one_provider_config import SystemOneProviderType

    return SimpleNamespace(
        id=uuid.uuid4(),
        provider_type=SystemOneProviderType.typesafe,
        display_name="Unit Provider",
        enabled=enabled,
        default_model="jev-latest",
    )


class TestResolveModelSelection:
    def _engine(self, catalogue, providers):
        return DecisionExecutionEngine(
            provider_service=providers, catalogue_service=catalogue
        )

    async def test_fk_selection_resolved_first(self):
        """FK path wins: the tool's availability reference resolves through
        the catalogue, carrying provider + model identity."""
        provider = _provider()
        row = SimpleNamespace(model_name="jev-latest", id=uuid.uuid4())
        resolved = _resolved(provider, row)
        catalogue = _StubCatalogue(resolved=resolved)
        engine = self._engine(catalogue, _StubProviders(provider))
        tool = _StubTool(availability_id=row.id)

        got_provider, model, got_resolved = await engine.resolve_model_selection(
            None, tool, None
        )
        assert got_provider is provider
        assert model == "jev-latest"
        assert got_resolved is resolved
        # FK path used — catalogue consulted with the tool's reference
        assert catalogue.calls == [(row.id, None)]

    async def test_fk_selection_disabled_raises_actionable_error(self):
        """A disabled/unavailable selection fails with an actionable
        DecisionExecutionError (no silent vendor fallback)."""
        catalogue = _StubCatalogue(
            error=DecisionModelCatalogueError(
                "Decision model 'jev-latest' on provider 'Unit Provider' is disabled"
            )
        )
        engine = self._engine(catalogue, _StubProviders(_provider()))
        tool = _StubTool(availability_id=uuid.uuid4())

        with pytest.raises(DecisionExecutionError, match="disabled"):
            await engine.resolve_model_selection(None, tool, None)

    async def test_legacy_fallback_uses_provider_model(self):
        """Legacy tools (NULL FK) resolve via the tenant's enabled provider
        and the legacy free-text ``provider_model``."""
        provider = _provider()
        catalogue = _StubCatalogue()
        engine = self._engine(catalogue, _StubProviders(provider))
        tool = _StubTool(availability_id=None, provider_model="legacy-model")

        got_provider, model, resolved = await engine.resolve_model_selection(
            None, tool, None
        )
        assert got_provider is provider
        assert model == "legacy-model"
        assert resolved.model_name == "legacy-model"

    async def test_legacy_fallback_defaults_to_provider_default_model(self):
        """Legacy tool without provider_model falls back to the provider's
        ``default_model``."""
        provider = _provider()
        catalogue = _StubCatalogue()
        engine = self._engine(catalogue, _StubProviders(provider))
        tool = _StubTool(availability_id=None, provider_model=None)

        _, model, _ = await engine.resolve_model_selection(None, tool, None)
        assert model == "jev-latest"

    async def test_legacy_path_disabled_provider_raises(self):
        provider = _provider(enabled=False)
        catalogue = _StubCatalogue()
        engine = self._engine(catalogue, _StubProviders(provider))
        tool = _StubTool(availability_id=None)

        with pytest.raises(DecisionExecutionError, match="disabled"):
            await engine.resolve_model_selection(None, tool, None)

    async def test_legacy_path_disabled_model_raises(self):
        """A legacy model row that resolves as disabled raises — even on
        the legacy fallback path."""
        import uuid as _uuid
        from types import SimpleNamespace

        provider = _provider()
        catalogue = _StubCatalogue()
        catalogue.resolve_legacy_default = self._disabled_default
        engine = self._engine(catalogue, _StubProviders(provider))
        tool = _StubTool(availability_id=None)

        with pytest.raises(DecisionExecutionError, match="disabled"):
            await engine.resolve_model_selection(None, tool, None)

    @staticmethod
    async def _disabled_default(db, provider, model_name):
        return SimpleNamespace(
            id=uuid.uuid4(), model_name=model_name, is_disabled=True
        )


class TestUsageIdentity:
    def test_usage_identity_carries_provider_model_identity(self):
        """Usage metering carries provider/model identity (never key material)."""
        from types import SimpleNamespace

        from app.services.system_one.decision_model_availability_service import (
            DecisionModelCatalogueService,
        )

        provider = _provider()
        resolved = _resolved(
            provider, SimpleNamespace(model_name="jev-latest", id=provider.id)
        )
        identity = DecisionModelCatalogueService().usage_identity(resolved)
        assert identity["provider_id"] == str(provider.id)
        assert identity["provider_type"] == "typesafe"
        assert identity["provider_display_name"] == "Unit Provider"
        assert identity["model_name"] == "jev-latest"
        assert "usage" not in identity

    def test_usage_identity_includes_provider_reported_usage(self):
        from types import SimpleNamespace

        from app.services.system_one.decision_model_availability_service import (
            DecisionModelCatalogueService,
        )

        provider = _provider()
        resolved = _resolved(
            provider, SimpleNamespace(model_name="jev-latest", id=provider.id)
        )
        identity = DecisionModelCatalogueService.usage_identity(
            None, resolved, {"total_tokens": 432}
        )
        assert identity["usage"] == {"total_tokens": 432}
        blob = repr(identity)
        assert "sk-" not in blob  # no credential material
