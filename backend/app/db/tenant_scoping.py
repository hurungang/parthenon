"""Row-level tenant scoping at the Control Center database gateway.

This module is the SINGLE choke point for tenant isolation: sessions
obtained through the ``get_db`` dependency have every ORM query
automatically constrained to the request's tenant when multi-tenancy is
on, and are completely unconstrained when it is off (or for background
workers that never carry a tenant context).

Mechanism (SQLAlchemy's documented multi-tenant pattern):

``apply_tenant_scope(session, tenant_id)`` records the scope on
``session.info``; a single class-level ``do_orm_execute`` listener (the
hook fires for ORM executions including lazy loads) inspects that flag
and rewrites statements:

- **SELECT** — ``with_loader_criteria`` is added per tenant-scoped entity
  in the statement, so rows of other tenants can never be returned.
- **ORM DELETE / UPDATE** — an additional ``tenant_id`` where-criterion is
  appended, so rows of other tenants can never be modified or deleted.

Sessions that never went through ``apply_tenant_scope`` (background
jobs, startup tasks, platform-admin requests without a tenant context)
carry no flag and are untouched — byte-for-byte single-tenant behaviour.

**Identity-plane exemption (FIX-20260929-221449):** individual statements
may opt out of the scope rewrite via
:func:`execute_unscoped` (execution option ``{"tenant_scope": "exempt"}``)
— reserved for platform-level IDENTITY resolution (PlatformUser-by-sub,
JIT provisioning), which must see the user record regardless of the
request's tenant membership.  Data-plane reads/writes keep the full scope.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.sql.selectable import Select
from sqlalchemy.sql.dml import Delete, Update

logger = logging.getLogger(__name__)

#: session.info key carrying the scoped tenant id.
_SCOPE_KEY = "parthenon_tenant_scope"

#: session.info key collecting cross-tenant scope misses (audit candidates).
_SCOPE_MISSES_KEY = "parthenon_scope_misses"

#: session.info key carrying request attribution (method/path/ip) for audits.
_REQUEST_INFO_KEY = "parthenon_scope_request_info"

#: column name every direct-scoped entity shares.
_TENANT_COLUMN = "tenant_id"

# ── Identity-plane exemption (FIX-20260929-221449) ───────────────────────────
#
# Resolving WHO a request is from (PlatformUser by cryptographic ``sub``,
# JIT provisioning of the PlatformUser/Identity rows) is PLATFORM-level:
# the scoping choke point's PlatformUser membership-join strategy is
# correct for the data plane (user lists show only co-members) but wrong
# for the identity plane — a user without a membership in the resolved
# tenant was INVISIBLE to their own authentication (403 "user must
# re-authenticate" → frontend bounce loop).  Identity-plane statements
# opt out explicitly per execution:
#
#     from app.db.tenant_scoping import execute_unscoped
#     user = (await execute_unscoped(
#         db, select(PlatformUser).where(PlatformUser.sub == sub)
#     )).scalar_one_or_none()
#
# The raw execution-option form (``db.execute(stmt,
# execution_options={"tenant_scope": "exempt"})``) is honoured by the
# choke point too; ``execute_unscoped`` is the canonical helper because it
# also suppresses cross-tenant MISS AUDITING for the statement (a missing
# user at first login is a normal JIT signal, not a cross-tenant probe).
# The exemption is per STATEMENT — everything else on the scoped session
# stays fully tenant-constrained (data-plane user listing keeps the
# membership-join strategy).

#: execution option key marking a statement as tenant-scope exempt.
TENANT_SCOPE_OPTION_KEY = "tenant_scope"

#: execution option value that exempts a single statement from the scope.
TENANT_SCOPE_EXEMPT = "exempt"


def _is_scope_exempt_statement(stmt: Any) -> bool:
    """True when *stmt* carries the identity-plane exemption option."""
    options = getattr(stmt, "_execution_options", None) or {}
    try:
        return options.get(TENANT_SCOPE_OPTION_KEY) == TENANT_SCOPE_EXEMPT
    except Exception:
        return False


def execute_unscoped(db: AsyncSession, stmt: Any, *args: Any, **kwargs: Any) -> Any:
    """Execute *stmt* EXEMPT from the session's tenant scope (identity plane).

    The canonical opt-out for platform-level identity lookups —
    PlatformUser-by-sub resolution, JIT provisioning upserts — which must
    see the user record regardless of any active membership in the
    request's resolved tenant (FIX-20260929-221449).  Returns the
    ``db.execute(...)`` awaitable; ``await`` the call as usual::

        row = (await execute_unscoped(
            db, select(PlatformUser).where(PlatformUser.sub == sub)
        )).scalar_one_or_none()

    Scope of the exemption (single statement only):

    - no ``with_loader_criteria`` / DML criteria are applied to THIS
      statement by the ``do_orm_execute`` choke point;
    - no cross-tenant scope-miss auditing is recorded for THIS statement's
      result (a not-found identity at first login is a JIT signal, not a
      cross-tenant probe);
    - INSERT stamping is NOT affected (tenant-scoped INSERTs on a scoped
      session still inherit the session's tenant).

    Use ONLY for identity resolution — data-plane reads/writes (user
    listings, member administration) MUST keep the session's tenant scope.

    Caveat: full-entity rows loaded through the exempt statement enter the
    session's identity map, so a later ``session.get(Entity, id)`` for the
    SAME identity short-circuits to the cached object without re-applying
    the scope (with_loader_criteria only guards query time).  Identity-plane
    call sites consume the loaded object directly; do not mix an exempt
    load with data-plane ``get()`` on the same session.
    """
    if _is_scope_exempt_statement(stmt):
        return db.execute(stmt, *args, **kwargs)
    return db.execute(
        stmt.execution_options(**{TENANT_SCOPE_OPTION_KEY: TENANT_SCOPE_EXEMPT}),
        *args,
        **kwargs,
    )

# class -> is tenant-scoped (has a tenant_id column)
_scoped_cache: dict[type, bool] = {}
# table name -> mapped class (for ORM DELETE/UPDATE criteria)
_table_class_cache: dict[str, type] = {}


def _is_tenant_scoped(cls: type) -> bool:
    """True when the mapped class carries a direct tenant_id column."""
    cached = _scoped_cache.get(cls)
    if cached is not None:
        return cached
    try:
        from app.db.session import Base

        scoped = issubclass(cls, Base) and _TENANT_COLUMN in getattr(
            cls, "__table__", None
        ).columns.keys()  # type: ignore[union-attr]
    except Exception:
        scoped = False
    _scoped_cache[cls] = scoped
    return scoped


def _class_for_table(table_name: str) -> type | None:
    """Best-effort mapped class lookup by table name (cached)."""
    if table_name in _table_class_cache:
        return _table_class_cache[table_name]
    try:
        from app.db.session import Base

        for mapper in Base.registry.mappers:
            cls = mapper.class_
            if mapper.local_table is not None and mapper.local_table.name == table_name:
                _table_class_cache[table_name] = cls
                return cls
    except Exception:
        pass
    return None


def _has_automatic_scope_strategy(cls: type) -> bool:
    """True for tenant-agnostic entities whose isolation strategy is
    applied AUTOMATICALLY by this choke point on every statement.

    Currently exactly one: ``PlatformUser`` — the documented
    "membership-join" strategy (see ``TENANT_AGNOSTIC_REGISTRY`` in
    ``backend/tests/test_tenant_isolation_sweep.py``).  PlatformUser has
    no ``tenant_id`` column, so in a tenant context its rows are
    constrained through an ACTIVE ``TenantUserMembership`` in the scoped
    tenant instead.
    """
    if cls.__name__ != "PlatformUser":
        return False
    try:
        from app.db.models.platform_user import PlatformUser

        return cls is PlatformUser
    except Exception:
        return False


# ── Criteria closure factories (FIX-20260928-121317 Finding #1) ──────────────
#
# CRITICAL: SQLAlchemy's lambda-SQL cache (used by ``with_loader_criteria``)
# keys compiled criteria on the lambda's *code object* and re-extracts
# scalar **closure** variables as bind parameters on every invocation.  A
# default-arg binding (``lambda cls, _tid=tenant_id: ...``) is INVISIBLE to
# that machinery: the criteria compiled for the FIRST tenant seen by the
# process was replayed for every later tenant — scope A followed by scope B
# returned A's rows (46/47 sweep tests failed on this).  Building the
# lambda inside a factory makes the tenant id a true closure variable, so
# each scoped execution re-binds the current value and the cache recompiles
# only when needed.


def _tenant_criteria_factory(tenant_id: uuid.UUID):
    """Closure factory: direct ``tenant_id`` criteria for scoped entities."""

    def _criteria(cls):
        return cls.tenant_id == tenant_id

    return _criteria


def _platform_user_criteria_factory(tenant_id: uuid.UUID):
    """Closure factory: PlatformUser 'membership-join' criteria.

    Same predicate as :func:`filter_platform_users_to_tenant` — a user
    row is visible only with an ACTIVE membership in the scoped tenant.
    """

    def _criteria(cls):
        from app.db.models.tenant_membership import (
            TenantUserMembership,
            TenantUserMembershipStatus,
        )

        return cls.id.in_(
            select(TenantUserMembership.user_id).where(
                TenantUserMembership.tenant_id == tenant_id,
                TenantUserMembership.status == TenantUserMembershipStatus.active,
            )
        )

    return _criteria


def apply_tenant_scope(
    session: AsyncSession | Session,
    tenant_id: uuid.UUID,
    request: Any = None,
) -> None:
    """Constrain every ORM query on this session to *tenant_id*.

    Called from the ``get_db`` dependency when a resolved tenant context
    exists (multi-tenancy on).  Sessions without a scope behave exactly
    as before.

    Also installs cross-tenant miss detection: a primary-key or
    single-row lookup that returns no row for a tenant-scoped entity is
    recorded (synchronously) as a scope miss, and flushed as a
    security-relevant ``TenantAuditEvent`` at request completion by
    :func:`flush_scope_miss_audits` — so cross-tenant probes are both
    not-found (isolation) and audited (visibility).
    """
    sync_session: Session = getattr(session, "sync_session", session)  # type: ignore[assignment]
    sync_session.info[_SCOPE_KEY] = uuid.UUID(str(tenant_id))
    sync_session.info.setdefault(_SCOPE_MISSES_KEY, [])
    if request is not None:
        client = getattr(request, "client", None)
        sync_session.info[_REQUEST_INFO_KEY] = {
            "method": getattr(request, "method", None),
            "path": getattr(getattr(request, "url", None), "path", None),
            "ip": getattr(client, "host", None),
        }
    _install_miss_detection(session, sync_session)
    logger.debug("Tenant scope applied to session: tenant=%s", tenant_id)


def scope_for_session(session: AsyncSession | Session) -> uuid.UUID | None:
    """Return the session's scoped tenant id, or None when unscoped.

    The scope value is written exclusively by :func:`apply_tenant_scope`
    (always a parsed ``uuid.UUID``); anything else in ``session.info``
    under the scope key (e.g. a foreign/test-double object) is treated
    as no scope rather than raising — request-path callers use this to
    branch between tenant-scoped and legacy behaviour.
    """
    sync_session: Session = getattr(session, "sync_session", session)  # type: ignore[assignment]
    value = sync_session.info.get(_SCOPE_KEY)
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None
    return parsed


def filter_platform_users_to_tenant(stmt: Select, tenant_id: uuid.UUID) -> Select:
    """Constrain a PlatformUser statement to ACTIVE members of *tenant_id*.

    Endpoint-level implementation of the documented PlatformUser
    "membership-join" strategy: the entity deliberately carries no
    ``tenant_id``, so tenant-context user queries must filter through an
    ACTIVE ``TenantUserMembership`` of the requesting tenant.  The
    ``do_orm_execute`` choke point applies the same predicate
    automatically on scoped sessions (:func:`_platform_user_criteria_factory`);
    this helper makes the contract explicit at the query level
    (defence-in-depth) and guards statements whose semantics should hold
    regardless of how the session was scoped.  Pass ``tenant_id=None``
    paths untouched — single-tenant mode / platform-admin surfaces keep
    full access.
    """
    from app.db.models.platform_user import PlatformUser
    from app.db.models.tenant_membership import (
        TenantUserMembership,
        TenantUserMembershipStatus,
    )

    return stmt.where(
        PlatformUser.id.in_(
            select(TenantUserMembership.user_id).where(
                TenantUserMembership.tenant_id == tenant_id,
                TenantUserMembership.status == TenantUserMembershipStatus.active,
            )
        )
    )


def _scoped_entities_of_statement(stmt: Select) -> list[type]:
    """ALL criteria-bearing entity classes referenced by a SELECT.

    Covers result entities (``column_descriptions``) AND join targets
    (FROM clause traversal).  Two kinds of entities get automatic
    criteria:

    - tenant-scoped entities (direct ``tenant_id`` column) — join/child
      tables inherit scope through their scoped parents, so a statement
      joining a scoped parent must carry that parent's criteria even
      when the parent is not selected; and
    - tenant-agnostic entities with an automatic strategy
      (:func:`_has_automatic_scope_strategy` — ``PlatformUser``).
    """
    entities: list[type] = []
    seen: set[type] = set()

    def _add(entity: Any) -> None:
        if entity is not None and entity not in seen:
            seen.add(entity)
            if _is_tenant_scoped(entity) or _has_automatic_scope_strategy(entity):
                entities.append(entity)

    try:
        descriptions = stmt.column_descriptions
    except Exception:
        descriptions = None
    for desc in descriptions or []:
        entity = desc.get("entity") if isinstance(desc, dict) else None
        _add(entity)

    for clause in _from_clauses_of(stmt):
        for table in _iter_tables(clause):
            cls = _class_for_table(table.name)
            if cls is not None:
                _add(cls)
    return entities


def _from_clauses_of(stmt: Select) -> list[Any]:
    """The final FROM elements of a SELECT (best-effort)."""
    try:
        return list(stmt.get_final_froms())
    except Exception:
        return []


def _iter_tables(clause: Any):
    """Yield every table in a FROM element, recursing through joins."""
    from sqlalchemy.sql.selectable import Join, TableClause

    if isinstance(clause, Join):
        yield from _iter_tables(clause.left)
        yield from _iter_tables(clause.right)
    elif isinstance(clause, TableClause):
        yield clause


def _scope_options_for_select(stmt: Select, tenant_id: uuid.UUID) -> list[Any]:
    """with_loader_criteria options for each criteria-bearing entity.

    The options are built FRESH on every ORM execution (this helper runs
    inside the ``do_orm_execute`` event) — the option object itself is
    never cached at process level.  Only SQLAlchemy's per-lambda
    compiled-criteria cache persists across executions, and the closure
    factories above make it re-bind the current tenant id correctly for
    every scoped execution (FIX-20260928-121317 Finding #1).
    """
    options: list[Any] = []
    for entity in _scoped_entities_of_statement(stmt):
        if _has_automatic_scope_strategy(entity):
            criteria = _platform_user_criteria_factory(tenant_id)
        else:
            criteria = _tenant_criteria_factory(tenant_id)
        options.append(
            with_loader_criteria(entity, criteria, include_aliases=True)
        )
    return options


def _scope_dml_statement(stmt: Delete | Update, tenant_id: uuid.UUID) -> Delete | Update:
    """Append a tenant where-criterion to an ORM DELETE/UPDATE."""
    table = getattr(stmt, "table", None)
    if table is None:
        return stmt
    cls = _class_for_table(table.name)
    if cls is not None and _is_tenant_scoped(cls):
        return stmt.where(table.c[_TENANT_COLUMN] == tenant_id)  # type: ignore[return-value]
    return stmt


def _tenant_scope_do_orm_execute(orm_exec_state: Any) -> None:
    """Session event: rewrite statements to the session's tenant scope."""
    tenant_id = orm_exec_state.session.info.get(_SCOPE_KEY)
    if tenant_id is None:
        return  # unscoped session — no tenant logic executes
    # Identity-plane exemption (FIX-20260929-221449): a statement marked
    # ``{"tenant_scope": "exempt"}`` (via execute_unscoped or the raw
    # execution option) is executed byte-for-byte unscoped — the choke
    # point never rewrites it.
    execution_options = getattr(orm_exec_state, "execution_options", None) or {}
    if execution_options.get(TENANT_SCOPE_OPTION_KEY) == TENANT_SCOPE_EXEMPT:
        return
    stmt = orm_exec_state.statement
    if isinstance(stmt, Select):
        options = _scope_options_for_select(stmt, tenant_id)
        if options:
            orm_exec_state.statement = stmt.options(*options)
    elif isinstance(stmt, (Delete, Update)):
        orm_exec_state.statement = _scope_dml_statement(stmt, tenant_id)


def register_tenant_scope_listener() -> None:
    """Register the class-level ORM listeners (idempotent).

    Invoked once from ``get_db`` (first scoped session); the listeners are
    no-ops for sessions that never received ``apply_tenant_scope``.
    """
    if getattr(register_tenant_scope_listener, "_registered", False):
        return
    event.listen(Session, "do_orm_execute", _tenant_scope_do_orm_execute)
    event.listen(Session, "before_flush", _tenant_stamp_before_flush)
    register_tenant_scope_listener._registered = True  # type: ignore[attr-defined]
    logger.info("Tenant scope listeners registered on ORM Session")


def _tenant_stamp_before_flush(
    session: Session, flush_context: Any, instances: Any
) -> None:
    """Stamp new tenant-scoped rows with the session's tenant.

    Rows created on a scoped session always belong to the request's
    tenant — INSERTs cannot leak into (or out of) another tenant.  Rows
    created on unscoped sessions (background jobs) must set tenant_id
    explicitly; a null tenant stays null exactly as before multi-tenancy.
    """
    tenant_id = session.info.get(_SCOPE_KEY)
    if tenant_id is None:
        return
    for obj in session.new:
        cls = type(obj)
        if _is_tenant_scoped(cls) and getattr(obj, _TENANT_COLUMN, None) is None:
            setattr(obj, _TENANT_COLUMN, tenant_id)


# ── Cross-tenant miss detection & audit ──────────────────────────────────────


def _record_scope_miss(sync_session: Session, entity: type, target: str) -> None:
    """Synchronously record a cross-tenant scope miss (audit candidate)."""
    misses: list[dict[str, Any]] = sync_session.info.setdefault(_SCOPE_MISSES_KEY, [])
    if len(misses) < 50:  # bound the list — probe floods must not balloon memory
        misses.append(
            {
                "entity": entity.__name__,
                "target": str(target)[:200],
            }
        )


def _install_miss_detection(session: Any, sync_session: Session) -> None:
    """Wrap ``get``/``execute`` once per session to detect scoped lookups
    that return no row (cross-tenant probes)."""
    flags = sync_session.info.setdefault(_REQUEST_INFO_KEY, {})
    if flags.get("_miss_detection_installed"):
        return
    flags["_miss_detection_installed"] = True

    original_get = session.get

    async def scoped_get(entity: type, ident: Any, *args: Any, **kwargs: Any) -> Any:
        row = await original_get(entity, ident, *args, **kwargs)
        if row is None and (
            _is_tenant_scoped(entity) or _has_automatic_scope_strategy(entity)
        ):
            _record_scope_miss(sync_session, entity, f"{entity.__name__}:{ident}")
        return row

    session.get = scoped_get  # type: ignore[method-assign]

    original_execute = session.execute

    import inspect as _inspect

    if _inspect.iscoroutinefunction(original_execute):

        async def scoped_execute(statement: Any, *args: Any, **kwargs: Any) -> Any:
            result = await original_execute(statement, *args, **kwargs)
            if _is_scope_exempt_statement(statement):
                # Identity-plane statement (FIX-20260929-221449): a
                # not-found identity is a normal JIT signal, never a
                # cross-tenant probe — no scope-miss auditing.
                return result
            return _maybe_proxy_result(
                result, statement, sync_session
            )

    else:

        def scoped_execute(statement: Any, *args: Any, **kwargs: Any) -> Any:
            result = original_execute(statement, *args, **kwargs)
            if _is_scope_exempt_statement(statement):
                return result
            return _maybe_proxy_result(result, statement, sync_session)

    session.execute = scoped_execute  # type: ignore[method-assign]


def _maybe_proxy_result(result: Any, statement: Any, sync_session: Session) -> Any:
    """Wrap buffered results of scoped single-row lookups for miss auditing."""
    if isinstance(statement, Select):
        scoped_entities = _scoped_entities_of(statement)
        if scoped_entities:
            return _MissAuditingResult(result, sync_session, scoped_entities, statement)
    return result


def _scoped_entities_of(stmt: Select) -> list[type]:
    """Scoped entity classes selected by this statement (deduplicated)."""
    return _scoped_entities_of_statement(stmt)


class _MissAuditingResult:
    """Transparent proxy around a query Result that records single-row
    lookups returning no row (cross-tenant probes).  All other access is
    delegated untouched."""

    def __init__(
        self,
        result: Any,
        sync_session: Session,
        entities: list[type],
        statement: Any,
    ) -> None:
        self._result = result
        self._session = sync_session
        self._entities = entities
        self._statement_repr = str(statement)[:200]

    def scalar_one_or_none(self) -> Any:
        row = self._result.scalar_one_or_none()
        if row is None:
            for entity in self._entities:
                _record_scope_miss(
                    self._session, entity, f"select:{self._statement_repr}"
                )
        return row

    def __getattr__(self, name: str) -> Any:
        return getattr(self._result, name)


async def flush_scope_miss_audits(session: AsyncSession | Session) -> None:
    """Persist pending scope-miss audits as security-relevant events.

    Called from ``get_db`` after the request completes (before commit) so
    every cross-tenant probe observed during the request is recorded as a
    ``cross_tenant_access_denied`` TenantAuditEvent attributed to the
    requesting tenant.
    """
    sync_session: Session = getattr(session, "sync_session", session)  # type: ignore[assignment]
    tenant_id = sync_session.info.get(_SCOPE_KEY)
    misses: list[dict[str, Any]] | None = sync_session.info.get(_SCOPE_MISSES_KEY)
    if tenant_id is None or not misses:
        return

    from app.db.models.tenant_audit_event import (
        TenantAuditActorType,
        TenantAuditEvent,
        TenantAuditEventType,
    )

    request_info: dict[str, Any] = sync_session.info.get(_REQUEST_INFO_KEY, {})
    target = (
        f"{request_info.get('method')} {request_info.get('path')}"
        if request_info.get("method")
        else "unknown request"
    )
    for miss in misses:
        sync_session.add(
            TenantAuditEvent(
                tenant_id=tenant_id,
                event_type=TenantAuditEventType.cross_tenant_access_denied,
                actor_type=TenantAuditActorType.tenant_user,
                actor_ip=request_info.get("ip"),
                target_resource=target,
                detail={
                    "probed_entity": miss["entity"],
                    "probed_target": miss["target"],
                },
                is_security_relevant=True,
            )
        )
    if misses:
        logger.warning(
            "Recorded %d cross-tenant scope miss audit event(s) for tenant=%s",
            len(misses),
            tenant_id,
        )
    sync_session.info[_SCOPE_MISSES_KEY] = []
