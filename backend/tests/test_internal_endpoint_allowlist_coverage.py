"""Regression guard: internal endpoints CALLED must be allowlisted CC-side.

Bug class this file guards against
----------------------------------
New AR→CC (or CH→CC) internal endpoints are implemented and called from the
client code, but the CC-side mTLS allowlists in ``backend/app/api/deps.py``
(``_AR_ALLOWLIST`` / ``_CH_ALLOWLIST``) are never updated. At runtime every
call is rejected with ``403 endpoint_not_allowlisted``. This has shipped
multiple times (scripts verifications/promote/repairs, serving-version,
optimized-plan, and now ``scripts/invocable``, ``llm-mock/recordings`` and the
CH execution-log endpoint).

Strategy
--------
1. PRIMARY — source scan: statically extract the (method, path) pairs the
   AR and CH clients issue against ``/api/v1/internal/...`` and assert each
   is present in the corresponding allowlist (imported, not text-parsed).
2. SECONDARY — route cross-check: enumerate the routes actually registered
   on the CC internal routers that make up the known AR/CH integration
   surface (scripts router, llm-mock router, SystemToolRegistry CC endpoint
   map) and assert each is allowlisted. This catches drift in the other
   direction (routers renamed/moved so allowlist entries point nowhere).

Caller-side extraction limits (documented, by design)
-----------------------------------------------------
* The scan is regex-based over a curated list of caller files. New *files*
  must be registered in ``_AR_CALLER_SPECS`` / ``_CH_CALLER_SPECS`` (or a
  new spec added); the test cannot discover unknown client modules.
* Paths are extracted from ``self._get/_post/_patch(...)``-style helpers,
  ``self._request("METHOD", ...)`` calls, and literal ``/api/v1/internal/...``
  occurrences inside f-strings. Dynamically assembled paths (e.g. built from
  variables at runtime, or the generic system-tool registry map) are covered
  by the SECONDARY route cross-check instead.
* Path parameters (``{var}`` f-string interpolations) are canonicalized to
  ``{}`` on both the extracted and the allowlist side, so segment naming
  does not cause false failures.
* ``GET /api/v1/internal/certificates/revoked/{serial}`` is intentionally
  unauthenticated (no ``require_service_certificate`` dependency) and
  ``POST /api/v1/internal/bootstrap`` happens before any caller identity
  exists — both are excluded from the allowlist requirement.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.api import deps
from app.services.agents.system_tool_registry import SystemToolRegistry

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Canonical form used for comparison: collapse named path params to "{}".
_PARAM_RE = re.compile(r"\{[^}/]+\}")


def _canon(path: str) -> str:
    return _PARAM_RE.sub("{}", path)


# Endpoints exempt from the allowlist (no require_service_certificate dep,
# or called before a service identity exists — see module docstring).
_ALLOWLIST_EXEMPT: set[tuple[str, str]] = {
    ("GET", "/api/v1/internal/certificates/revoked/{}"),
    ("POST", "/api/v1/internal/bootstrap"),
}


# ── Caller-side source scan ────────────────────────────────────────────────


@dataclass
class CallerSpec:
    """How to extract internal (method, path) pairs from one caller file."""

    rel_path: str
    base: str  # prefix prepended to extracted relative paths
    # helper-name → HTTP method (e.g. "_get" → GET); paths start with "/"
    helper_pattern: re.Pattern[str]
    helper_methods: dict[str, str]
    # extra literal full-path matches ("/api/v1/internal/...") to include
    literal_paths: bool = False
    extra: list[tuple[str, str]] = field(default_factory=list)


_HELPER_RE = re.compile(
    r"self\._(?P<helper>get|post|patch|put|delete|internal_post)\(\s*f?\"(?P<path>/[^\"]*)\""
)
_REQUEST_RE = re.compile(
    r"self\._request\(\s*\"(?P<method>GET|POST|PATCH|PUT|DELETE)\",\s*f?\"(?P<path>/[^\"]*)\""
)
_LITERAL_RE = re.compile(r"/api/v1/internal/[A-Za-z0-9_/\-.{}]*")
_CLIENT_VERB_RE = re.compile(r"client\.(?P<verb>get|post|patch|put|delete)\(")


def _extract_from_helpers(source: str, spec: CallerSpec) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for m in _HELPER_RE.finditer(source):
        helper = m.group("helper")
        method = spec.helper_methods.get(helper)
        if method is None:
            continue
        pairs.add((method, spec.base + m.group("path")))
    return pairs


def _extract_from_literals(source: str) -> set[tuple[str, str]]:
    """Extract literal /api/v1/internal/... paths, inferring the HTTP method
    from the nearest following ``client.<verb>(`` call (default POST — every
    currently-scanned literal call site is a POST)."""
    pairs: set[tuple[str, str]] = set()
    for m in _LITERAL_RE.finditer(source):
        window = source[m.end() : m.end() + 600]
        verb_m = _CLIENT_VERB_RE.search(window)
        verb = verb_m.group("verb") if verb_m else "post"
        pairs.add((verb.upper(), m.group(0)))
    return pairs


def _extract_mock_calls(source: str) -> set[tuple[str, str]]:
    """Extract llm-mock calls from cc_client.py: ``self._mock_url("...")``
    with the method inferred from the ``client.<verb>(url`` in the same
    function block."""
    pairs: set[tuple[str, str]] = set()
    blocks = re.split(r"\n\s+async def ", source)
    for block in blocks:
        for m in re.finditer(r"self\._mock_url\(\s*\"(?P<path>/[^\"]*)\"\s*\)", block):
            verb_m = _CLIENT_VERB_RE.search(block)
            verb = verb_m.group("verb") if verb_m else "post"
            pairs.add((verb.upper(), "/api/v1/internal/llm-mock" + m.group("path")))
    return pairs


def _ar_caller_pairs() -> set[tuple[str, str]]:
    cc_client = (BACKEND_ROOT / "app/agent_runtime/scripts/cc_client.py").read_text()
    data_client = (BACKEND_ROOT / "app/agent_runtime/data_client.py").read_text()

    pairs: set[tuple[str, str]] = set()
    # scripts registry client: base /api/v1/internal/scripts
    for m in _REQUEST_RE.finditer(cc_client):
        pairs.add((m.group("method"), "/api/v1/internal/scripts" + m.group("path")))
    pairs |= _extract_mock_calls(cc_client)
    # data client: _get/_post/_patch → /api/v1/internal/data, _internal_post → /api/v1/internal
    pairs |= _extract_from_helpers(
        data_client,
        CallerSpec(
            rel_path="app/agent_runtime/data_client.py",
            base="/api/v1/internal/data",
            helper_pattern=_HELPER_RE,
            helper_methods={"get": "GET", "post": "POST", "patch": "PATCH"},
        ),
    )
    for m in _HELPER_RE.finditer(data_client):
        if m.group("helper") == "internal_post":
            pairs.add(("POST", "/api/v1/internal" + m.group("path")))
    return pairs


def _ch_caller_pairs() -> set[tuple[str, str]]:
    files = [
        "app/communication_hub/data_client.py",
        "app/communication_hub/middleware/authorization.py",
        "app/communication_hub/middleware/api_key_auth.py",
        "app/communication_hub/mcp/tool_registry_bridge.py",
        "app/communication_hub/api/mcp_tools.py",
        "app/communication_hub/api/internal/tool_routing.py",
    ]
    pairs: set[tuple[str, str]] = set()
    for rel in files:
        source = (BACKEND_ROOT / rel).read_text()
        pairs |= _extract_from_helpers(
            source,
            CallerSpec(
                rel_path=rel,
                base="/api/v1",
                helper_pattern=_HELPER_RE,
                helper_methods={"get": "GET", "post": "POST", "patch": "PATCH"},
            ),
        )
        pairs |= _extract_from_literals(source)
    return pairs


def _missing(called: set[tuple[str, str]], allowlist: set[tuple[str, str]]) -> list[tuple[str, str]]:
    allowlisted = {(_canon(m), _canon(p)) for m, p in allowlist}
    missing = [
        (m, p)
        for m, p in called
        if (m, _canon(p)) not in allowlisted and (m, _canon(p)) not in _ALLOWLIST_EXEMPT
    ]
    return sorted(missing)


# ── Tests ──────────────────────────────────────────────────────────────────


def test_ar_called_internal_endpoints_are_allowlisted():
    """Every /api/v1/internal/... pair issued by Agent Runtime client code
    must appear in _AR_ALLOWLIST (CC-side mTLS policy) or be documented as
    exempt."""
    called = _ar_caller_pairs()
    assert called, "source scan found no AR internal calls — scanner broken?"
    missing = _missing(called, deps._AR_ALLOWLIST)
    assert not missing, (
        "Agent Runtime calls internal CC endpoints that are NOT in "
        "app/api/deps.py::_AR_ALLOWLIST (runtime → 403 endpoint_not_allowlisted). "
        f"Add these (method, path) pairs: {missing}"
    )


def test_ch_called_internal_endpoints_are_allowlisted():
    """Every /api/v1/internal/... pair issued by Communication Hub client code
    must appear in _CH_ALLOWLIST (CC-side mTLS policy) or be documented as
    exempt."""
    called = _ch_caller_pairs()
    assert called, "source scan found no CH internal calls — scanner broken?"
    missing = _missing(called, deps._CH_ALLOWLIST)
    assert not missing, (
        "Communication Hub calls internal CC endpoints that are NOT in "
        "app/api/deps.py::_CH_ALLOWLIST (runtime → 403 endpoint_not_allowlisted). "
        f"Add these (method, path) pairs: {missing}"
    )


def _router_routes(router, prefix: str) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for route in router.routes:
        for method in getattr(route, "methods", ()) or ():
            if method in {"HEAD", "OPTIONS"}:
                continue
            routes.add((method, prefix + route.path))
    return routes


def test_scripts_router_routes_are_ar_allowlisted():
    """Every route on the CC internal scripts router is part of the known
    AR↔CC script-framework surface and must be allowlisted for AR
    (catches allowlist drift when routes move/rename)."""
    from app.api.v1.internal.llm_mocking import InternalLLMMockRouter
    from app.api.v1.internal.scripts import InternalScriptsRouter

    expected = _router_routes(InternalScriptsRouter, "/api/v1")
    expected |= _router_routes(InternalLLMMockRouter, "/api/v1")
    assert expected, "no routes found on internal scripts/llm-mock routers"
    allowlisted = {(_canon(m), _canon(p)) for m, p in deps._AR_ALLOWLIST}
    missing = sorted(
        (m, p) for m, p in expected if (m, _canon(p)) not in allowlisted
    )
    assert not missing, (
        "CC internal script/llm-mock routes exist but are NOT AR-allowlisted "
        f"(AR calls these at runtime): {missing} — fix _AR_ALLOWLIST in app/api/deps.py"
    )


def test_system_tool_registry_endpoints_are_ch_allowlisted():
    """Every CC endpoint registered in SystemToolRegistry (routed by CH tool
    routing) must be in _CH_ALLOWLIST."""
    endpoints = {
        path for path in SystemToolRegistry.get_cc_endpoint_map("").values()
    }
    assert endpoints, "SystemToolRegistry endpoint map is empty"
    allowlisted = {(_canon(m), _canon(p)) for m, p in deps._CH_ALLOWLIST}
    missing = sorted(
        ("POST", p) for p in endpoints if ("POST", _canon(p)) not in allowlisted
    )
    assert not missing, (
        "SystemToolRegistry CC endpoints NOT in _CH_ALLOWLIST "
        f"(CH routes these at runtime): {missing} — fix _CH_ALLOWLIST in app/api/deps.py"
    )
