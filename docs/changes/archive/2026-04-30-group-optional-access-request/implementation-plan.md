# Implementation Plan — Group-Optional Access Request

## Overview

This change makes `group_id` optional on the `AccessRequest` model so that users who cannot see any groups can still submit a request. Administrators then assign the appropriate group during the approval step. The change touches the database model, the Alembic migration, backend schemas and service logic, and the frontend request/review dialogs.

## Task Checklist

### Phase 1 — Database Schema
- [x] 1.1 — Make `group_id` nullable in the `AccessRequest` SQLAlchemy model
- [x] 1.2 — Remove the unique constraint that includes `group_id` (NULL-safe uniqueness logic moves to the service layer)
- [x] 1.3 — Generate and verify the Alembic migration

### Phase 2 — Backend
- [x] 2.1 — Update `AccessRequestBatchCreate` schema: make `group_ids` an optional list (default empty)
- [x] 2.2 — Update `AccessRequestRead` schema: make `group_id` optional (`uuid.UUID | None`)
- [x] 2.3 — Update `ApproveRequestBody` schema: add optional `group_id` field
- [x] 2.4 — Update `AccessRequestService.submit_batch_request`: handle empty `group_ids` by creating one group-less request
- [x] 2.5 — Update `AccessRequestService.approve_request`: accept `group_id`, set it on the request, validate it is provided when the request has none
- [x] 2.6 — Update `_enrich_request` helper: guard against `group_id` being `None`
- [x] 2.7 — Update `approve_request` API endpoint: pass `group_id` from request body to the service

### Phase 3 — Frontend
- [x] 3.1 — Update `AccessRequest` TypeScript interface: make `group_id` optional (`string | undefined`)
- [x] 3.2 — Update `submitAccessRequest` API function: accept an optional `groupIds` parameter (empty array allowed)
- [x] 3.3 — Update `approveAccessRequest` API function: accept optional `groupId` parameter and include it in the request body
- [x] 3.4 — Update `useSubmitAccessRequest` hook: allow calling with no group IDs
- [x] 3.5 — Update `useApproveAccessRequest` hook: pass `groupId` through the mutation payload
- [x] 3.6 — Update `MyRequestsTab`: hide group selection when no groups are available; show the informational alert from the prototype; remove the groups-required validation when no groups exist
- [x] 3.7 — Update `PendingRequestsTab`: show "Unassigned" when `group_id` is absent; add a mandatory group-selection dropdown to the approve dialog
- [x] 3.8 — Add i18n translation keys for all new UI strings

### Phase 4 — Testing
- [x] 4.1 — Backend unit tests: `AccessRequestService` — group-less submission, duplicate prevention, approve with group assignment, approve fails when group required but missing
- [x] 4.2 — Backend API tests: `POST /user-access-requests` with empty group_ids, `PATCH /{id}/approve` with group assignment
- [x] 4.3 — Frontend unit tests: updated `MyRequestsTab` (no-groups variant), updated `PendingRequestsTab` (group assignment in approve dialog)
- [x] 4.4 — E2E test: full group-optional access request flow (user submits without group → admin assigns group and approves)

---

## Phase 1 — Database Schema

### Task 1.1 — Make `group_id` nullable in the `AccessRequest` SQLAlchemy model

In `backend/app/db/models/access_request.py`, change the `group_id` column declaration from `nullable=False` to `nullable=True` and update its Python type from `uuid.UUID` to `uuid.UUID | None`. Update the `group` relationship to reflect the optional foreign key.

**Done when**: The `AccessRequest` model has `group_id: Mapped[uuid.UUID | None]` with `nullable=True`, and the file passes the project linter without errors.

### Task 1.2 — Remove the unique constraint that includes `group_id`

The existing `UniqueConstraint("user_id", "group_id", "status", name="uq_user_group_status_pending")` cannot enforce uniqueness across NULL `group_id` values in PostgreSQL (two NULLs are never equal). Remove this constraint from `__table_args__`. Duplicate-request prevention for group-less requests will be enforced in `AccessRequestService.submit_batch_request` (see Task 2.4).

**Done when**: `__table_args__` no longer contains `uq_user_group_status_pending`, and the service layer enforces the duplicate check in code.

### Task 1.3 — Generate and verify the Alembic migration

Run `alembic revision --autogenerate -m "make_access_request_group_id_optional"` from the `backend/` directory. Review the generated migration file to confirm it contains: (1) `ALTER COLUMN group_id DROP NOT NULL`, and (2) `DROP CONSTRAINT uq_user_group_status_pending`. Run `alembic upgrade head` against a local dev database and confirm it applies cleanly.

**Done when**: The migration file exists under `backend/alembic/versions/`, `alembic upgrade head` succeeds with no errors, and `alembic downgrade -1` reverses it cleanly.

---

## Phase 2 — Backend

### Task 2.1 — Update `AccessRequestBatchCreate` schema: make `group_ids` optional

In `backend/app/schemas/access_requests.py`, change `group_ids` from `List[uuid.UUID] = Field(..., min_length=1)` to `List[uuid.UUID] = Field(default_factory=list)`. An empty list signals a group-less request.

**Done when**: `AccessRequestBatchCreate(justification="test")` parses without error, and the field accepts both empty and non-empty lists.

### Task 2.2 — Update `AccessRequestRead` schema: make `group_id` optional

In `backend/app/schemas/access_requests.py`, change `group_id: uuid.UUID` to `group_id: uuid.UUID | None`. The `group_name` enriched field is already optional, so no change is needed there.

**Done when**: `AccessRequestRead` serialises correctly when `group_id` is `None` (confirmed by a unit test or a quick REPL check).

### Task 2.3 — Update `ApproveRequestBody` schema: add optional `group_id` field

In `backend/app/schemas/access_requests.py`, add `group_id: uuid.UUID | None = None` to `ApproveRequestBody`. This allows the approve endpoint to receive a group assignment alongside the approval reason.

**Done when**: `ApproveRequestBody(group_id="<uuid>", approval_reason="ok")` parses without error, and `ApproveRequestBody()` also parses (both fields optional).

### Task 2.4 — Update `AccessRequestService.submit_batch_request`: handle empty `group_ids`

In `backend/app/services/permissions/access_request_service.py`, update `submit_batch_request` to handle `group_ids` being an empty list. When empty, create a single `AccessRequest` with `group_id=None`. Add a duplicate-check for this case: query for any existing pending request for the same user where `group_id IS NULL`; raise `HTTPException 409` if one already exists.

**Done when**: Calling the service with `group_ids=[]` creates one request with `group_id=None`, and a second call with the same user raises 409.

### Task 2.5 — Update `AccessRequestService.approve_request`: accept and assign `group_id`

In `backend/app/services/permissions/access_request_service.py`, add a `group_id: uuid.UUID | None = None` parameter to `approve_request`. Before creating the `UserGroup` membership, if `request.group_id is None`, require that `group_id` is provided (raise `HTTPException 400` with a clear message if not). Set `request.group_id = group_id` before creating the membership.

**Done when**: Approving a group-less request without providing `group_id` returns 400; approving with a valid `group_id` sets the group on the request and creates the `UserGroup` membership.

### Task 2.6 — Update `_enrich_request` helper: guard against `group_id` being `None`

In `backend/app/api/v1/user_access_requests.py`, wrap the `await db.get(Group, req.group_id)` call with a `if req.group_id is not None` guard so it skips the group lookup and leaves `group_name` as `None` when the request has no group assigned.

**Done when**: `_enrich_request` returns an `AccessRequestRead` with `group_id=None` and `group_name=None` without raising an error.

### Task 2.7 — Update `approve_request` API endpoint: pass `group_id` to the service

In `backend/app/api/v1/user_access_requests.py`, update the `approve_request` endpoint to pass `body.group_id` to `svc.approve_request(...)`.

**Done when**: A `PATCH /user-access-requests/{id}/approve` request with `{"group_id": "<uuid>"}` routes the group ID to the service correctly.

---

## Phase 3 — Frontend

### Task 3.1 — Update `AccessRequest` TypeScript interface: make `group_id` optional

In `frontend/src/types/permissions.ts`, change `group_id: string` to `group_id?: string` on the `AccessRequest` interface. All existing usages that read `group_id` must be updated to handle the `undefined` case (typically by falling back to a display string like "—" or an "Unassigned" chip).

**Done when**: TypeScript compilation reports no errors after the type change, and all consuming components handle the optional field.

### Task 3.2 — Update `submitAccessRequest` API function: accept optional `groupIds`

In `frontend/src/api/permissionsApi.ts`, change `submitAccessRequest(groupIds: string[], ...)` to `submitAccessRequest(groupIds: string[] = [], ...)`. The body sent to the API remains `{ group_ids: groupIds, justification }` — an empty array is now valid.

**Done when**: Calling `submitAccessRequest([], "reason")` sends `{ group_ids: [], justification: "reason" }` to the backend without a TypeScript error.

### Task 3.3 — Update `approveAccessRequest` API function: accept optional `groupId`

In `frontend/src/api/permissionsApi.ts`, add an optional `groupId?: string` parameter to `approveAccessRequest`. Include it in the PATCH request body as `group_id: groupId` when provided.

**Done when**: Calling `approveAccessRequest(id, undefined, "reason")` omits `group_id` from the body, and calling with a valid UUID includes it.

### Task 3.4 — Update `useSubmitAccessRequest` hook: allow no group IDs

In `frontend/src/hooks/usePermissions.ts`, change the `mutationFn` signature for `useSubmitAccessRequest` from `{ groupIds: string[]; ... }` to `{ groupIds?: string[]; ... }`, passing an empty array when omitted.

**Done when**: The hook can be called with `mutateAsync({ justification: "reason" })` (no `groupIds`) without a TypeScript error.

### Task 3.5 — Update `useApproveAccessRequest` hook: pass `groupId`

In `frontend/src/hooks/usePermissions.ts`, update `useApproveAccessRequest`'s `mutationFn` to accept `{ requestId, groupId?, reason? }` and pass `groupId` to `api.approveAccessRequest(...)`.

**Done when**: The hook passes `groupId` through to the API call and TypeScript reports no errors.

### Task 3.6 — Update `MyRequestsTab`: adaptive form for users with no groups

In `frontend/src/pages/permissions/AccessRequestsPage.tsx`, update `MyRequestsTab`:

1. Derive `hasNoGroups: boolean` from `useGroups()` — true when the groups list is empty or undefined.
2. When `hasNoGroups` is true, replace the group-selection list with the informational alert from the prototype ("Group access is assigned by an administrator. Please describe what resources you need…") and remove the groups-required validation.
3. When `hasNoGroups` is false, keep the existing multi-group selection UI unchanged.
4. On submit, call `submitRequest.mutateAsync({ groupIds: hasNoGroups ? [] : selectedGroupIds, justification })`.
5. Wrap the async submit in a try-catch using the Dialog Error Handling Standard (`dialogError` state + `PermissionDeniedAlert`).

**Done when**: A user with an empty groups list sees the informational alert and can submit with only a justification; a user with groups still sees the group selection and must choose at least one.

### Task 3.7 — Update `PendingRequestsTab`: group display and assignment in approve dialog

In `frontend/src/pages/permissions/AccessRequestsPage.tsx`, update `PendingRequestsTab`:

1. In the table, replace `{req.group_name ?? req.group_id}` with a conditional: if `req.group_id` is absent, render an "Unassigned" MUI `Chip` (color `default`); otherwise render `req.group_name ?? req.group_id`.
2. In the approve dialog, add a `Select` dropdown for group assignment. Load groups using `useGroups()`. Make the dropdown required when `approveTarget?.group_id` is absent; optional (pre-populated) when the request already has a group.
3. Add `approveGroupId` state to hold the selected group.
4. On approve, pass `groupId: approveGroupId || undefined` to `approve.mutateAsync(...)`.
5. Validate: if the request has no group and no group is selected, show an inline error — do not call the API.
6. Wrap the approve mutation in a try-catch using the Dialog Error Handling Standard.

**Done when**: Requests with no `group_id` display "Unassigned" in the table; the approve dialog forces group selection for those requests; approval succeeds and the table refreshes.

### Task 3.8 — Add i18n translation keys for all new UI strings

Add the following keys to all translation files under `frontend/src/` (or the configured i18n source):

- `permissions.accessRequests.noGroupInfoAlert` — text for the informational alert shown when no groups are available
- `permissions.accessRequests.assignGroup` — label for the "Assign to Group" dropdown
- `permissions.accessRequests.assignGroupRequired` — validation message when group is required but not selected
- `permissions.accessRequests.unassigned` — label for the "Unassigned" chip

**Done when**: All new `t()` calls resolve to non-empty strings in at least the default locale, and no hardcoded strings exist in the updated components.

---

## Phase 4 — Testing

### Task 4.1 — Backend unit tests: `AccessRequestService`

Create `backend/tests/services/permissions/test_access_request_service.py` with unit tests covering:

- Submitting a request with `group_ids=[]` creates a batch with one request where `group_id` is `None`.
- A second group-less submission by the same user while one is pending raises `HTTPException 409`.
- Approving a group-less request without providing `group_id` raises `HTTPException 400`.
- Approving a group-less request with a valid `group_id` sets the field and creates the `UserGroup` membership.
- Approving a request that already has a `group_id` without providing one in the body still succeeds.

**Done when**: All five test cases pass under `pytest`.

### Task 4.2 — Backend API tests: updated endpoints

In `backend/tests/api/v1/`, add test cases to `test_permissions_api.py` (or a new `test_access_requests_api.py`):

- `POST /user-access-requests` with `group_ids: []` returns HTTP 201 with a single request where `group_id` is `null`.
- `PATCH /user-access-requests/{id}/approve` with `group_id` in the body returns HTTP 200 with the group assigned.
- `PATCH /user-access-requests/{id}/approve` for a group-less request without `group_id` returns HTTP 400.

**Done when**: All three test cases pass under `pytest`.

### Task 4.3 — Frontend unit tests: updated components

Update `frontend/src/__tests__/AccessRequestsPage.test.tsx`:

- Add a test verifying that `MyRequestsTab` renders the informational alert (not the group list) when `useGroups` returns an empty array.
- Add a test verifying that `MyRequestsTab` still renders the group selection when `useGroups` returns non-empty data.
- Add a test verifying that `PendingRequestsTab` renders an "Unassigned" chip for a request with no `group_id`.
- Add a test verifying that the approve dialog renders a group dropdown when `approveTarget.group_id` is absent.

**Done when**: All new and existing tests in `AccessRequestsPage.test.tsx` pass under `vitest`.

### Task 4.4 — E2E test: full group-optional access request flow

Add a test case to `e2e/tests/access-control.spec.ts` covering:

1. User with no group permissions opens the "Request Access" dialog, sees the informational alert, enters a justification, and submits — request appears in their list as "Pending".
2. Admin navigates to the pending requests table, sees the request with "Unassigned" in the group column.
3. Admin clicks "Review Request", selects a group from the dropdown, and clicks "Approve & Assign".
4. Request row updates to show the assigned group and "Approved" status.
5. User's "My Requests" list reflects the approval with the assigned group name.

**Done when**: The E2E test passes against a running dev environment with the dev Playwright config.

---

## Completion Checklist

- [x] `alembic upgrade head` runs cleanly; `alembic downgrade -1` reverses it cleanly
- [x] All backend `pytest` tests pass (unit + API)
- [x] All frontend `vitest` tests pass
- [x] E2E test for the group-optional flow passes
- [x] No TypeScript errors (`tsc --noEmit` passes)
- [x] No hardcoded UI strings — all new labels use `t()`
- [x] Dialog Error Handling Standard applied to all modified dialogs
- [x] `AccessRequest.group_id` shown as "Unassigned" chip in the admin pending table when absent
- [x] Group assignment dropdown is required in the approve dialog when the request has no group
