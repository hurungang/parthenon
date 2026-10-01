"""Unit tests for the immutable tenant context (Phase 2.1 / 9.1).

Covers ``app.core.tenant_context``:

- ``TenantContext`` frozen/immutable contract (mutation raises)
- ``TENANT_UNSET`` sentinel semantics: falsy, ``is_set`` False, loud
  attribute failures, singleton identity
- set/get/require accessors incl. exactly-once binding rejection
- request-scoped context variable set/reset
- OTEL span attribution: tenant attributes when resolved, platform
  sentinel when tenancy on without context, NOTHING when tenancy off
"""
from __future__ import annotations

import dataclasses
import uuid
from unittest.mock import MagicMock

import pytest

from app.core.tenant_context import (
    SPAN_TENANCY_ATTR,
    SPAN_TENANT_ID_ATTR,
    SPAN_TENANT_SLUG_ATTR,
    TENANT_UNSET,
    TenantContext,
    TenantContextUnset,
    get_current_tenant_context,
    get_tenant_context,
    require_tenant_context,
    reset_current_tenant_context,
    set_current_tenant_context,
    set_tenant_context,
    set_tenant_span_attributes,
)


def _ctx(**overrides) -> TenantContext:
    defaults = dict(
        tenant_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        slug="globex",
        name="Globex",
    )
    defaults.update(overrides)
    return TenantContext(**defaults)


class _FakeState:
    pass


class _FakeRequest:
    def __init__(self):
        self.state = _FakeState()


class TestImmutableContext:
    def test_is_set_true(self):
        assert _ctx().is_set is True

    def test_mutation_raises_frozen_error(self):
        ctx = _ctx()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.slug = "mutated"  # type: ignore[misc]

    def test_tenant_id_mutation_raises(self):
        ctx = _ctx()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.tenant_id = uuid.uuid4()  # type: ignore[misc]

    def test_system_tenant_flag_default_false(self):
        assert _ctx().is_system_tenant is False
        assert _ctx(is_system_tenant=True).is_system_tenant is True


class TestUnsetSentinel:
    def test_singleton_identity(self):
        assert TENANT_UNSET is TenantContextUnset()
        assert TenantContextUnset() is TENANT_UNSET

    def test_is_set_false(self):
        assert TENANT_UNSET.is_set is False

    def test_falsy(self):
        assert not TENANT_UNSET
        assert bool(TENANT_UNSET) is False

    def test_field_access_is_loud(self):
        with pytest.raises(AttributeError):
            _ = TENANT_UNSET.tenant_id
        with pytest.raises(AttributeError):
            _ = TENANT_UNSET.slug
        with pytest.raises(AttributeError):
            _ = TENANT_UNSET.name

    def test_repr_is_sentinel(self):
        assert repr(TENANT_UNSET) == "TENANT_UNSET"


class TestAccessors:
    def test_get_returns_unset_when_nothing_bound(self):
        request = _FakeRequest()
        assert get_tenant_context(request) is TENANT_UNSET

    def test_set_then_get_round_trip(self):
        request = _FakeRequest()
        ctx = _ctx()
        set_tenant_context(request, ctx)
        assert get_tenant_context(request) is ctx

    def test_double_set_rejected(self):
        """The context is established exactly once per request."""
        request = _FakeRequest()
        set_tenant_context(request, _ctx())
        with pytest.raises(RuntimeError, match="exactly once"):
            set_tenant_context(request, _ctx(slug="other"))

    def test_require_returns_context_when_set(self):
        request = _FakeRequest()
        ctx = _ctx()
        set_tenant_context(request, ctx)
        assert require_tenant_context(request) is ctx

    def test_require_raises_when_unset(self):
        request = _FakeRequest()
        with pytest.raises(RuntimeError, match="requires an active tenant"):
            require_tenant_context(request)


class TestRequestScopedContextVar:
    def test_set_and_reset(self):
        ctx = _ctx()
        token = set_current_tenant_context(ctx)
        try:
            assert get_current_tenant_context() is ctx
        finally:
            reset_current_tenant_context(token)
        assert get_current_tenant_context() is None

    def test_default_is_none(self):
        assert get_current_tenant_context() is None


class _RecordingSpan:
    def __init__(self, recording: bool = True):
        self.attributes: dict = {}
        self._recording = recording

    def is_recording(self) -> bool:
        return self._recording

    def set_attribute(self, key, value):
        self.attributes[key] = value


class TestSpanAttribution:
    def _with_span(self, span):
        from unittest.mock import patch

        import opentelemetry.trace as trace

        return patch.object(trace, "get_current_span", return_value=span)

    def test_tenant_context_sets_tenant_attributes(self):
        span = _RecordingSpan()
        ctx = _ctx()
        with self._with_span(span):
            set_tenant_span_attributes(ctx, tenancy_active=True)
        assert span.attributes[SPAN_TENANT_ID_ATTR] == str(ctx.tenant_id)
        assert span.attributes[SPAN_TENANT_SLUG_ATTR] == "globex"
        assert span.attributes[SPAN_TENANCY_ATTR] == "tenant"

    def test_tenancy_on_without_context_sets_platform_sentinel(self):
        span = _RecordingSpan()
        with self._with_span(span):
            set_tenant_span_attributes(None, tenancy_active=True)
        assert span.attributes[SPAN_TENANCY_ATTR] == "platform"
        assert SPAN_TENANT_ID_ATTR not in span.attributes

    def test_tenancy_off_sets_nothing(self):
        """Byte-for-byte telemetry unchanged when the switch is off."""
        span = _RecordingSpan()
        with self._with_span(span):
            set_tenant_span_attributes(None, tenancy_active=False)
        assert span.attributes == {}

    def test_non_recording_span_is_noop(self):
        span = _RecordingSpan(recording=False)
        with self._with_span(span):
            set_tenant_span_attributes(_ctx(), tenancy_active=True)
        assert span.attributes == {}
