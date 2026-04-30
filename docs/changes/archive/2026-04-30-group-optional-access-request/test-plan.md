# Test Plan — Group-Optional Access Request

## 1. Test Strategy

This change touches database schema, backend service logic, REST API contracts, and two frontend components. Testing must cover all layers to ensure nothing regresses and the new optional-group flow works end-to-end.

| Layer | Framework | Location | Focus |
|-------|-----------|----------|-------|
| Unit | pytest | `backend/tests/unit/` | Service business rules, schema validation |
| Integration | pytest | `backend/tests/integration/` | Database nullable column, full API request/response cycles |
| Component | Vitest | `frontend/src/__tests__/` | `MyRequestsTab` adaptive form, `PendingRequestsTab` approve dialog |
| E2E | Playwright | `e2e/tests/` | Complete user flows from submission through admin approval |

All four layers must pass 100% before this change is considered shippable. Passing one layer is not sufficient.

---

## 2. Coverage Areas

### 2.1 Database / Schema
- `group_id` column on `AccessRequest` is nullable — INSERT and SELECT with `NULL` succeeds
- Alembic migration executes cleanly on a fresh database and on an existing database with existing rows
- The `uq_user_group_status_pending` unique constraint is removed without breaking existing data

### 2.2 Backend — Pydantic Schemas
- `AccessRequestBatchCreate` accepts an empty `group_ids` list
- `AccessRequestRead` serialises `group_id` as `null` correctly
- `ApproveRequestBody` accepts an optional `group_id` field

### 2.3 Backend — Service Logic (`AccessRequestService`)
- Submitting with empty `group_ids` creates exactly one `AccessRequest` row with `group_id = NULL`
- Submitting a second group-less request while one is already pending returns 409
- Approving a group-less request **with** a `group_id` in the body succeeds and creates the `UserGroup` membership
- Approving a group-less request **without** a `group_id` in the body returns 400
- Approving a request that already has a `group_id` stored ignores any `group_id` in the body

### 2.4 Backend — API Endpoints
- `POST /user-access-requests` — accepts empty `group_ids`, returns correct response shape
- `PATCH /user-access-requests/{id}/approve` — enforces group requirement when stored `group_id` is null
- `_enrich_request` helper does not crash when `group_id` is `None`
- Audit log entries are written for all actions (submit, approve, reject)

### 2.5 Frontend — `MyRequestsTab`
- `hasNoGroups` state derived correctly when `useGroups()` returns an empty list
- Informational alert variant renders (no group selector visible) when user has no groups
- Standard group multi-select variant renders when user has groups
- `dialogError` state follows the Dialog Error Handling Standard for API failures
- Submit button enabled without a group selection in the no-group variant
- Error cleared when dialog is closed

### 2.6 Frontend — `PendingRequestsTab`
- "Unassigned" renders in the Group column for requests with `group_id = null`
- Approve dialog shows the mandatory group-selection dropdown when `group_id` is null
- `approveGroupError` flag shows inline validation when admin clicks Approve without selecting a group
- `approveGroupId` state resets to `""` each time the approve dialog opens
- Parent requests table refreshes automatically (no page reload) after approve/reject actions
- `dialogError` displayed via `PermissionDeniedAlert` on API failure

---

## 3. Critical Scenarios

### Scenario: User without group permissions submits an access request
**WHEN** a user whose `useGroups()` result is empty opens the Request Access dialog  
**THEN** the group selection field is not displayed  
**AND** an informational alert explains that an administrator will assign a group  
**AND** the user can enter a justification and submit  
**AND** the request is created in the database with `group_id = NULL`

---

### Scenario: User with group permissions submits an access request (no regression)
**WHEN** a user with visible groups opens the Request Access dialog  
**THEN** the group multi-select field is displayed as before  
**AND** the user must select at least one group to submit  
**AND** the request is created with the selected `group_id`

---

### Scenario: User attempts to submit a second group-less request while one is pending
**WHEN** a user already has a pending group-less access request  
**AND** that user submits another access request with no groups selected  
**THEN** the backend returns 409 Conflict  
**AND** the dialog displays the error message to the user via `PermissionDeniedAlert`  
**AND** the duplicate request is not created in the database

---

### Scenario: Administrator views pending requests including group-less ones
**WHEN** an administrator opens the Pending Requests tab  
**THEN** requests without a group display "Unassigned" in the Group column  
**AND** requests with a group display the group name as before

---

### Scenario: Administrator approves a group-less request by assigning a group
**WHEN** an administrator opens the approve dialog for a group-less request  
**THEN** a mandatory group-selection dropdown is displayed  
**AND** clicking Approve without selecting a group shows an inline validation error  
**AND** selecting a group and clicking Approve succeeds  
**AND** the request status changes to Approved  
**AND** the user is added to the selected group  
**AND** the pending requests table refreshes automatically without a page reload

---

### Scenario: Administrator approves a group-less request without providing a group
**WHEN** the approve dialog is open for a group-less request  
**AND** the administrator clicks Approve without selecting a group  
**THEN** the frontend shows inline validation and does not call the API  
**IF** the API is called with no group_id for a group-less request  
**THEN** the backend returns 400 Bad Request  
**AND** the error is displayed in the dialog via `PermissionDeniedAlert`

---

### Scenario: Administrator approves a request that already has a group assigned
**WHEN** the approve dialog is open for a request that already has a `group_id` stored  
**THEN** no group-selection dropdown is shown (existing behaviour preserved)  
**AND** approval proceeds with the stored group  
**AND** any `group_id` submitted in the approval body is ignored by the backend

---

### Scenario: API failure during group-less submission
**WHEN** the backend returns a 4xx or 5xx error during access request submission  
**THEN** the `dialogError` state is set  
**AND** a `PermissionDeniedAlert` is displayed at the top of `DialogContent`  
**AND** the dialog remains open  
**AND** closing the dialog clears the error

---

### Scenario: API failure during admin approval
**WHEN** the backend returns a 4xx or 5xx error during request approval  
**THEN** the `dialogError` state is set  
**AND** a `PermissionDeniedAlert` is displayed in the approve dialog  
**AND** the pending requests table is not modified

---

### Scenario: `_enrich_request` helper with null group_id
**WHEN** a request with `group_id = NULL` is enriched before serialisation  
**THEN** the helper returns without attempting a group lookup  
**AND** `group_name` in the response is `null` (not an error)

---

## 4. Edge Cases & Risks

### 4.1 Duplicate Constraint Removal
**Risk**: The database unique constraint `uq_user_group_status_pending` is dropped. Without the service-layer duplicate check this could allow multiple pending group-less requests from the same user.  
**Focus**: Verify the explicit service query (`SELECT 1 … WHERE group_id IS NULL AND status = 'pending'`) prevents duplicates even under rapid concurrent submissions.

### 4.2 Null Propagation Through Enrichment
**Risk**: The `_enrich_request` helper previously assumed `group_id` was always present. A `None` value that reaches a group lookup call will throw an unhandled exception.  
**Focus**: Test the enrichment path with `group_id = None` explicitly.

### 4.3 Parent Table Refresh After Admin Actions
**Risk**: React Query invalidation must fire after approve/reject to update the pending table without a page reload. Missing or incorrect query key invalidation is a common regression.  
**Focus**: Verify the `accessRequestsPending` query key is invalidated on every success path (approve and reject).

### 4.4 Admin Tries to Approve Without Selecting a Group (Frontend Bypass)
**Risk**: If the frontend validation is bypassed (e.g., via direct API call), the backend must still enforce the requirement.  
**Focus**: Backend integration test that POSTs approval with no `group_id` for a group-less request and asserts 400.

### 4.5 `approveGroupId` State Not Reset Between Requests
**Risk**: If the approve dialog carries `approveGroupId` from a previous approval, an administrator could accidentally approve a request for the wrong group.  
**Focus**: E2E test that opens the approve dialog for two consecutive requests and confirms the dropdown starts empty each time.

### 4.6 Mixed Pending List (with and without groups)
**Risk**: The admin table must render correctly when the list contains a mix of group-assigned and group-less requests.  
**Focus**: Integration/E2E scenario seeding both types and verifying correct column rendering.

### 4.7 Alembic Migration on Existing Data
**Risk**: Existing `AccessRequest` rows all have non-null `group_id`. The migration must apply without data loss or constraint violations.  
**Focus**: Run migration against a seeded test database with existing records and confirm all rows survive.

### 4.8 Permissions Change While Request Is Pending
**Risk**: A user submits a group-less request, then is granted group visibility. Their existing pending request remains group-less; the administrator must still assign a group on approval.  
**Focus**: Service test that approves a group-less request after the user's permissions have been updated.

---

## 5. Acceptance Criteria Checklist

Mapped directly to PRD acceptance criteria:

- [x] **Users without group permissions can submit access requests without selecting a group** — verified by E2E and component tests for the `hasNoGroups = true` path in `MyRequestsTab`
- [x] **The access request form allows submission with no group selected** — verified by component tests confirming the submit button is enabled and form is valid with no group chosen
- [x] **Administrators can view and filter access requests that have no group assigned** — verified by E2E tests showing "Unassigned" in the pending table
- [x] **Administrators can assign a group to the request during the approval process** — verified by E2E and integration tests for the approve dialog group-selection dropdown
- [x] **After approval, the user is added to the assigned group and notified** — verified by integration tests confirming `UserGroup` membership is created and audit log entry is written
- [x] **Error messages are clear if required information is missing** — verified by component and E2E tests for `approveGroupError` inline validation and `PermissionDeniedAlert` display
- [x] **The parent access request table refreshes automatically after admin actions (approve/assign group)** — verified by E2E tests confirming table updates without page reload
- [x] **System logs all actions for audit purposes** — verified by integration tests checking audit log entries for submit, approve, and reject actions

---

## 6. Test File References

### Backend
| File | What it covers |
|------|----------------|
| `backend/tests/services/permissions/test_access_request_service.py` | Service business rules: group-less submission, duplicate prevention, approval with/without group, null group bypass |
| `backend/tests/api/v1/test_access_requests_api.py` | `POST /user-access-requests` and `PATCH /{id}/approve` full request/response cycles, 409 and 400 error cases; Pydantic schema validation covered implicitly through API responses |

### Frontend
| File | What it covers |
|------|----------------|
| `frontend/src/__tests__/AccessRequestsPage.test.tsx` | `hasNoGroups` rendering logic, informational alert variant, submit without group, "Unassigned" rendering, group-selection dropdown in approve dialog, `approveGroupError` validation, `approveGroupId` reset |
| `frontend/src/__tests__/permissionsApi.test.ts` | Verifies `submitAccessRequest` and `approveAccessRequest` are exported with the correct function signatures |

### E2E
| File | What it covers |
|------|----------------|
| `e2e/tests/access-control.spec.ts` | Full CRUD flows: group-less submission, admin approval with group assignment, parent table auto-refresh, duplicate prevention, mixed pending list rendering |
