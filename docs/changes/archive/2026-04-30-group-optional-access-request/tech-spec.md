# Technical Specification — Group-Optional Access Request

## Technical Overview

`group_id` on `AccessRequest` is currently a non-nullable foreign key, which prevents submission when a user has no group visibility. This change makes the column nullable at the database layer, propagates optionality through the backend schema and service, and updates the frontend request dialog and admin review dialog accordingly. No new endpoints are introduced; only existing ones are extended.

---

## Component Breakdown

| Component | Responsibility |
|-----------|---------------|
| `AccessRequest` model | Declares `group_id` as nullable; removal of the `uq_user_group_status_pending` unique constraint |
| Alembic migration | Applies `ALTER COLUMN group_id DROP NOT NULL` and drops the removed unique constraint |
| `AccessRequestBatchCreate` schema | Allows an empty `group_ids` list as a valid submission payload |
| `AccessRequestRead` schema | Serialises `group_id` as nullable; downstream consumers must handle `null` |
| `ApproveRequestBody` schema | Carries an optional `group_id` so an administrator can assign a group at approval time |
| `AccessRequestService` | Enforces business rules: duplicate-check for group-less requests; requires `group_id` at approval when none is stored on the request |
| `_enrich_request` helper | Guards against `group_id` being `None` before fetching the related `Group` record |
| `approve_request` endpoint | Forwards the `group_id` from the request body to the service |
| `AccessRequest` TypeScript type | Makes `group_id` optional so the frontend handles absent values without type errors |
| `submitAccessRequest` API function | Accepts an empty `groupIds` array and sends it verbatim to the backend |
| `approveAccessRequest` API function | Includes an optional `group_id` in the PATCH body |
| `useSubmitAccessRequest` hook | Allows callers to omit `groupIds` entirely |
| `useApproveAccessRequest` hook | Threads `groupId` through to the API function |
| `MyRequestsTab` component | Adapts the request form: hides group selection and shows an informational alert when the user can see no groups |
| `PendingRequestsTab` component | Renders "Unassigned" for requests without a group; adds a mandatory group-selection dropdown to the approve dialog |

---

## API Changes

### `POST /user-access-requests`
- **Before**: `group_ids` was required and must have at least one element.
- **After**: `group_ids` is optional (defaults to `[]`). An empty list creates a single `AccessRequest` with `group_id = null`.
- **New 409 condition**: A pending group-less request already exists for this user (enforced in service layer, not by database constraint).

### `PATCH /user-access-requests/{request_id}/approve`
- **Before**: Body accepted only `approval_reason` (optional string).
- **After**: Body also accepts `group_id` (optional UUID). When the stored `AccessRequest.group_id` is `null`, `group_id` in the body is **required**; the endpoint returns 400 if absent. When `group_id` is already set, the field is ignored.

---

## State Management

### `MyRequestsTab`

New derived boolean `hasNoGroups` — computed from `useGroups()` data being empty or undefined. Controls which variant of the request form is rendered:

- `hasNoGroups = true` → informational alert variant (no group selection, justification only)
- `hasNoGroups = false` → existing multi-select group variant

New state `dialogError` (`unknown | null`) — follows the Dialog Error Handling Standard: set on API failure, cleared on dialog open/close, displayed via `PermissionDeniedAlert` at the top of `DialogContent`.

### `PendingRequestsTab`

New state `approveGroupId` (`string`) — holds the group selected by the administrator in the approve dialog. Reset to `""` when the dialog opens.

New state `approveGroupError` (`boolean`) — set to `true` when the admin tries to approve a group-less request without selecting a group.

Existing `dialogError` state (Dialog Error Handling Standard) — applied to the approve mutation.

---

## Data Access Patterns

### Submission path
The frontend calls `submitAccessRequest(groupIds, justification)` → `POST /user-access-requests`. When `groupIds` is empty the backend service creates one `AccessRequest` row with `group_id = null`. No change to the React Query invalidation pattern.

### Admin approval path
The frontend calls `approveAccessRequest(requestId, groupId?, reason?)` → `PATCH /user-access-requests/{id}/approve`. The backend service sets `request.group_id` from the body before creating the `UserGroup` membership. React Query invalidates `accessRequestsPending` on success (existing behaviour).

### Group lookup
`useGroups()` (already imported in `MyRequestsTab`) provides the list for both the existing multi-select and the new admin assign dropdown in `PendingRequestsTab`. No new API calls are needed.

### Duplicate prevention for group-less requests
The removed database unique constraint is replaced by an explicit service-layer query: `SELECT 1 FROM access_requests WHERE user_id = :uid AND group_id IS NULL AND status = 'pending'`. This keeps the duplicate-prevention logic explicit and database-vendor-agnostic.

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `AccessRequest` | model | SQLAlchemy model for access request records | `backend/app/db/models/access_request.py` |
| `AccessRequestStatus` | enum | Pending / approved / rejected status values | `backend/app/db/models/access_request.py` |
| `AccessRequestBatchCreate` | schema | Pydantic v2 schema for submitting a request batch | `backend/app/schemas/access_requests.py` |
| `AccessRequestRead` | schema | Pydantic v2 schema for reading a single request | `backend/app/schemas/access_requests.py` |
| `ApproveRequestBody` | schema | Pydantic v2 schema for the approve PATCH payload | `backend/app/schemas/access_requests.py` |
| `AccessRequestService` | service | Business logic for the full access request lifecycle | `backend/app/services/permissions/access_request_service.py` |
| `submit_batch_request` | method | Creates a batch and one request per group (or one group-less request) | `backend/app/services/permissions/access_request_service.py` |
| `approve_request` | method | Approves a request, optionally assigning a group, and creates UserGroup membership | `backend/app/services/permissions/access_request_service.py` |
| `_enrich_request` | helper | Populates `group_name` and `requester_display_name` on `AccessRequestRead` | `backend/app/api/v1/user_access_requests.py` |
| `submit_access_request` | endpoint | `POST /user-access-requests` — creates a request batch | `backend/app/api/v1/user_access_requests.py` |
| `approve_request` | endpoint | `PATCH /user-access-requests/{id}/approve` — approves a request | `backend/app/api/v1/user_access_requests.py` |
| `AccessRequest` | interface | TypeScript interface for a single access request record | `frontend/src/types/permissions.ts` |
| `AccessRequestBatch` | interface | TypeScript interface for a batch containing multiple requests | `frontend/src/types/permissions.ts` |
| `submitAccessRequest` | function | API call — `POST /user-access-requests` | `frontend/src/api/permissionsApi.ts` |
| `approveAccessRequest` | function | API call — `PATCH /user-access-requests/{id}/approve` | `frontend/src/api/permissionsApi.ts` |
| `useSubmitAccessRequest` | hook | React Query mutation for submitting an access request | `frontend/src/hooks/usePermissions.ts` |
| `useApproveAccessRequest` | hook | React Query mutation for approving an access request | `frontend/src/hooks/usePermissions.ts` |
| `AccessRequestsPage` | component | Top-level page containing the user and admin tabs | `frontend/src/pages/permissions/AccessRequestsPage.tsx` |
| `MyRequestsTab` | component | User-facing request form (adaptive) and request history list | `frontend/src/pages/permissions/AccessRequestsPage.tsx` |
| `PendingRequestsTab` | component | Admin review table with approve/reject dialogs | `frontend/src/pages/permissions/AccessRequestsPage.tsx` |
| `en.json` | i18n | Default locale translation file; contains new keys under `permissions.accessRequests` | `frontend/src/i18n/locales/en.json` |
