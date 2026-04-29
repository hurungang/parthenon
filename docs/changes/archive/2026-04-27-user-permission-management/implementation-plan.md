## Implementation Plan: user-permission-management

---

## Task Checklist

- [x] 1.1 — Create tag SQLAlchemy models
- [x] 1.2 — Create policy SQLAlchemy models
- [x] 1.3 — Create user and group SQLAlchemy models
- [x] 1.4 — Create AccessRequestBatch SQLAlchemy model
- [x] 1.5 — Generate and apply Alembic migration
- [x] 2.1 — Implement Tag Registry service
- [x] 2.2 — Implement User Cache Service
- [x] 2.3 — Implement Group Claim Mapper service
- [x] 2.4 — Implement Permission Engine service
- [x] 2.5 — Implement Access Request Service and Notification Hook
- [x] 2.6 — Implement wildcard resource ID matching in Permission Engine
- [x] 3.1 — Create Pydantic schemas for permissions
- [x] 3.2 — Implement Tag Registry API router
- [x] 3.3 — Implement Roles and Policy API router
- [x] 3.4 — Implement Groups API router
- [x] 3.5 — Implement Platform Users API router
- [x] 3.6 — Implement Access Requests API router
- [x] 4.1 — Integrate User Cache and Group Claim Mapper into auth middleware
- [x] 4.2 — Integrate Permission Engine dependency into resource APIs
- [x] 5.1 — Define frontend TypeScript types for permissions
- [x] 5.2 — Implement permissions API client
- [x] 5.3 — Implement permissions Zustand store
- [x] 5.4 — Add i18n keys for permission management module
- [x] 5.5 — Add routing for permission management module
- [x] 6.1 — Implement Tags page
- [x] 6.2 — Implement Roles page
- [x] 6.3 — Implement Groups page
- [x] 6.4 — Implement Users page
- [x] 6.5 — Implement Access Requests page
- [x] 6.6 — Implement useTagValueOptions hook and tag-value dropdowns
- [x] 6.7 — Complete ManageAccessModal component
- [x] 7.1 — Unit tests for Permission Engine
- [x] 7.2 — Unit tests for Group Claim Mapper and User Cache Service
- [x] 7.3 — API tests for Tags and Roles endpoints
- [x] 7.4 — API tests for Groups, Users, and Access Requests endpoints
- [x] 7.5 — Frontend unit tests for permissions store and API client
- [x] 7.6 — Frontend component tests for permission pages
- [x] 7.7 — E2E Playwright tests for all permission management user journeys
- [x] 9.1 — Add role_type column to Role model + generate migration
- [x] 9.2 — Create Bootstrap Service with system admin role seeding
- [x] 9.3 — Replace require_admin dependency with require_permission pattern
- [x] 9.4 — Update all user permission API routers to use permission checks
- [x] 9.5 — Update frontend to display system role indicator and disable edit/delete for system roles
- [x] 10.1 — Create backend resource type manifest
- [x] 10.2 — Create frontend resource type mirror
- [x] 10.3 — Refactor RolesPage to single-dialog policy management pattern
- [x] 10.4 — Update permission error responses to include required_permission field
- [x] 10.5 — Update PermissionEngine to validate against manifest
- [x] 10.6 — Update all permission routers to use manifest constants
- [x] 10.7 — Update frontend error handling to display permission requirements

---

### Phase 1: Data Foundation

- [ ] **Task: Create tag SQLAlchemy models** — Create `backend/app/db/models/tag_definition.py` (TagDefinition) and `backend/app/db/models/tag_value.py` (TagValue) with all columns from the data model. Register both in `backend/app/db/models/__init__.py`. — _Done when: both model files exist with correct columns and relationships; `__init__.py` imports them._

- [ ] **Task: Create policy SQLAlchemy models** — Create model files for `Role`, `PolicyStatement`, `PolicyAction`, `PolicyResource`, and `PolicyTagCondition` in `backend/app/db/models/`. Each file contains the SQLAlchemy declarative class with columns matching the data model; register all in `__init__.py`. — _Done when: five model files exist with correct columns and foreign key relationships; `__init__.py` imports all five._

- [ ] **Task: Create user and group SQLAlchemy models** — Create model files for `PlatformUser`, `UserRole`, `Group`, `GroupRole`, `UserGroup`, and `AccessRequest` in `backend/app/db/models/`. Register all in `__init__.py`. Include the `idp_claim_value` column on `Group` and `status` enum on `AccessRequest`. — _Done when: six model files exist with correct columns; junction tables have appropriate composite primary keys or unique constraints; `__init__.py` imports all six._

- [ ] **Task: Create AccessRequestBatch SQLAlchemy model** — Create `backend/app/db/models/access_request_batch.py` (`AccessRequestBatch` entity with `user_id`, `justification`, `submitted_at`). Update `AccessRequest` model to add `batch_id` FK and `reviewer_reason` nullable column. Register in `__init__.py`. — _Done when: model file exists; `AccessRequest` has the new columns; Alembic autogenerate detects the changes._

- [ ] **Task: Generate and apply Alembic migration** — Run `alembic revision --autogenerate -m "user_permission_management"` from the backend directory, review the generated migration file for correctness (all 13 new tables present, no unintended drops), and apply it with `alembic upgrade head`. — _Done when: a new migration file exists in `backend/alembic/versions/`, `alembic upgrade head` completes without errors, and all 13 tables are present in the development database._

---

### Phase 2: Backend Services

- [ ] **Task: Implement Tag Registry service** — Create `backend/app/services/permissions/tag_registry.py` with a `TagRegistry` class. Implement async methods: `list_definitions`, `create_definition`, `update_definition`, `delete_definition`, and `validate_tag_value` (checks a key/value pair against allowed values). — _Done when: all five methods are implemented with SQLAlchemy async session; `validate_tag_value` raises a structured error for invalid values; no business logic in the API layer._

- [ ] **Task: Implement User Cache Service** — Create `backend/app/services/permissions/user_cache_service.py` with a `UserCacheService` class. Implement `upsert_user(sub, email, display_name)` that inserts a new `PlatformUser` record on first login or updates `last_seen_at` on subsequent logins. Implement `get_user_by_sub(sub)` for lookup. — _Done when: `upsert_user` is idempotent (safe to call on every request); `first_seen_at` is only set on creation; unit test verifies both create and update paths._

- [ ] **Task: Implement Group Claim Mapper service** — Create `backend/app/services/permissions/group_claim_mapper.py` with a `GroupClaimMapper` class. Implement `map_claims(user_id, jwt_claims)` that reads the JWT group claim list, queries `Group` records whose `idp_claim_value` matches any claim, and inserts missing `UserGroup` membership records. Must be idempotent. — _Done when: existing memberships are not duplicated; new memberships are created for each matching claim; method returns the list of newly assigned group IDs._

- [ ] **Task: Implement Permission Engine service** — Create `backend/app/services/permissions/permission_engine.py` with a `PermissionEngine` class. Implement `authorize(user_id, module, action, resource_id, resource_tags)` that loads the user's effective roles (direct + via groups), queries policy statements for those roles, evaluates each statement's module/action/resource/tag conditions, and returns an `AuthorizationResult` (allow/deny + reason). — _Done when: deny is returned if no matching allow policy exists; tag conditions all must match; a unit test covers allow, deny-by-module, and deny-by-tag cases._

- [ ] **Task: Implement Access Request Service and Notification Hook** — Create `backend/app/services/permissions/access_request_service.py` with `AccessRequestService`: methods `submit_batch_request(user_id, group_ids, justification)` (creates one `AccessRequestBatch` and one `AccessRequest` per group_id), `approve_request(request_id, reviewer_id, reviewer_reason=None)`, `reject_request(request_id, reviewer_id, reviewer_reason)` (reviewer_reason required), and `list_requests(group_id, status)`. Create `backend/app/services/permissions/notification_hook.py` with `NotificationHook.notify_owner_new_request(group_id, requester_id)` and `notify_requester_decision(request_id)` using the existing notification service. Call the hook from Access Request Service on submit and on status change. — _Done when: `submit_batch_request` creates an `AccessRequestBatch` record and one `AccessRequest` per group, triggers owner notification per group; `approve_request` sets status to approved, creates a `UserGroup` record, stores optional reviewer_reason, and notifies the requester; `reject_request` sets status to rejected, stores required reviewer_reason, and notifies the requester._

- [ ] **Task: Implement wildcard resource ID matching in Permission Engine** — Add a private `_match_resource_id(pattern, resource_id)` method to `PermissionEngine` that evaluates wildcard patterns (e.g., `"support_*"` matches `"support_001"`). Update the `authorize()` method to use this matcher when evaluating `PolicyResource` records. — _Done when: unit test confirms `"support_*"` matches `"support_001"` and `"support_team"`, does not match `"monitoring_001"`; existing allow/deny logic is unchanged for exact ID matches._

---

### Phase 3: Backend API

- [ ] **Task: Create Pydantic schemas for permissions** — Create `backend/app/schemas/tags.py`, `backend/app/schemas/roles.py`, `backend/app/schemas/groups.py`, `backend/app/schemas/platform_users.py`, and `backend/app/schemas/access_requests.py`. Each file contains strongly-typed Pydantic v2 `Create`, `Update`, and `Read` models for its domain. Include Python `Enum` classes for `PolicyEffect` (`allow`/`deny`), `AccessRequestStatus` (`pending`/`approved`/`rejected`), and `TagScope` (`global`/`resource_type`). — _Done when: all five schema files exist with no `Any` types; enums are defined; Pydantic validation annotations are correct for required vs optional fields._

- [ ] **Task: Implement Tag Registry API router** — Create `backend/app/api/v1/tags.py`. Implement: `GET /tags/definitions` (list all, filterable by scope/resource_type), `POST /tags/definitions` (create, admin only), `PATCH /tags/definitions/{id}` (update allowed values or description, admin only), `DELETE /tags/definitions/{id}` (admin only). Register the router in `backend/app/api/v1/__init__.py` with prefix `/tags`. — _Done when: all four endpoints return correct HTTP status codes; non-admin requests to write operations return 403; router is registered and reachable._

- [ ] **Task: Implement Roles and Policy API router** — Create `backend/app/api/v1/roles.py`. Implement: `GET /roles`, `POST /roles` (admin only), `GET /roles/{id}`, `PATCH /roles/{id}` (admin only), `DELETE /roles/{id}` (admin only, blocked if role has active assignments without confirmation flag), `GET /roles/{id}/policies`, `POST /roles/{id}/policies` (admin only), `DELETE /roles/{id}/policies/{policy_id}` (admin only). Register with prefix `/roles`. — _Done when: delete of role with active assignments returns 409 without the `force=true` query parameter; all CRUD endpoints return correct shapes per Pydantic schemas._

- [ ] **Task: Implement Groups API router** — Create `backend/app/api/v1/groups.py`. Implement: `GET /groups` (all users), `POST /groups` (admin only), `GET /groups/{id}`, `PATCH /groups/{id}` (admin or group owner), `DELETE /groups/{id}` (admin only), `GET /groups/{id}/members`, `POST /groups/{id}/members` (admin only — direct add), `DELETE /groups/{id}/members/{user_id}` (admin only), `GET /groups/{id}/roles`, `POST /groups/{id}/roles` (admin only), `DELETE /groups/{id}/roles/{role_id}` (admin only). Register with prefix `/groups`. — _Done when: group owner can PATCH their own group but receives 403 on admin-only endpoints; all endpoints return correct shapes._

- [ ] **Task: Implement Platform Users API router** — Create `backend/app/api/v1/platform_users.py`. Implement: `GET /platform-users` (admin only — paginated list with role/group counts), `GET /platform-users/{id}` (admin only — detail with roles and group memberships), `POST /platform-users/{id}/roles` (admin only — assign direct role), `DELETE /platform-users/{id}/roles/{role_id}` (admin only), `POST /platform-users/{id}/groups` (admin only — direct group add), `DELETE /platform-users/{id}/groups/{group_id}` (admin only). Register with prefix `/platform-users`. — _Done when: all endpoints are admin-gated; paginated list endpoint accepts `page` and `page_size` query parameters; response shapes match Pydantic schemas._

- [ ] **Task: Implement Access Requests API router** — Create `backend/app/api/v1/access_requests.py`. Implement: `POST /access-requests` (authenticated users — submit batch payload with `group_ids` list and `justification`; returns batch ID and per-group request list), `GET /access-requests/my` (authenticated — list own batches with per-group statuses), `GET /access-requests/pending` (group owners — list pending requests for their groups), `PATCH /access-requests/{id}/approve` (group owner or admin — accepts optional `approval_reason` in body stored as reviewer_reason), `PATCH /access-requests/{id}/reject` (group owner or admin — requires non-empty `rejection_reason` in body stored as reviewer_reason; returns 422 if missing). Register with prefix `/access-requests`. — _Done when: a user cannot approve/reject requests for groups they do not own unless admin; submitting a duplicate pending request returns 409; approve stores optional reviewer_reason; reject returns 422 when rejection_reason is absent; all status transitions call the Notification Hook._

---

### Phase 4: Auth Middleware Integration

- [ ] **Task: Integrate User Cache and Group Claim Mapper into auth middleware** — Modify `backend/app/middleware/auth.py` to call `UserCacheService.upsert_user()` and `GroupClaimMapper.map_claims()` after each successful JWT validation. Both calls must be async and must not block the request on failure (catch and log exceptions rather than returning 500). — _Done when: a new user's `PlatformUser` record is created on first authenticated request; group memberships matching JWT claims are created on first login; middleware integration test confirms both side effects._

- [ ] **Task: Integrate Permission Engine dependency into resource APIs** — Create a `get_permission_engine` FastAPI dependency in `backend/app/services/permissions/permission_engine.py`. Apply it as an example integration to one existing resource API endpoint (e.g., `DELETE /agents/{id}`) to validate the pattern: pass module, action, resource_id, and resource_tags; return 403 on deny. Document the integration pattern for use across other endpoints. — _Done when: the example endpoint returns 403 when the Permission Engine denies the action; the FastAPI dependency is importable and documented with a docstring describing how to apply it._

---

### Phase 5: Frontend Core

- [ ] **Task: Define frontend TypeScript types for permissions** — Create `frontend/src/types/permissions.ts` with strongly-typed interfaces and enums for all permission domain objects: `TagDefinition`, `TagValue`, `Role`, `PolicyStatement`, `PolicyAction`, `PolicyResource`, `PolicyTagCondition`, `PlatformUser`, `Group`, `AccessRequest`, and enums `PolicyEffect`, `AccessRequestStatus`, `TagScope`. — _Done when: no `any` types; all interfaces match the Pydantic Read schemas; enums are `const enum` or TypeScript string enums._

- [ ] **Task: Implement permissions API client** — Create `frontend/src/api/permissionsApi.ts` with typed async functions for all permission endpoints (tags, roles, groups, platform-users, access-requests). All functions use `apiClient` from `frontend/src/api/apiClient.ts` and `API_CONFIG.BASE_URL`. Return types are the TypeScript interfaces from `permissions.ts`. — _Done when: every backend endpoint has a corresponding typed function; no hardcoded base URLs; TypeScript compiler reports no errors in this file._

- [ ] **Task: Implement permissions Zustand store** — Create `frontend/src/stores/permissionsStore.ts` using Zustand. The store holds state for: tags list, roles list, groups list, platform users list, access requests list, and per-entity loading/error flags. Implement actions that call `permissionsApi` functions and update state. — _Done when: store compiles without TypeScript errors; loading flags are set before and cleared after each API call; error state captures API errors._

- [ ] **Task: Add i18n keys for permission management module** — Add all permission management UI text keys to `frontend/src/i18n/locales/en.json` under a `permissions` namespace: page titles, table column headers, form labels, button labels, status labels, error messages, and confirmation dialog text for all five pages. — _Done when: at least 40 keys are added under the `permissions` namespace; no English string is hardcoded in any permission-related component; key names follow existing naming conventions in `en.json`._

- [ ] **Task: Add routing for permission management module** — Add routes for the permission management module in the frontend router. Create the `frontend/src/pages/permissions/` directory and add a `PermissionsPage.tsx` layout component with tab navigation for the five sub-pages. Register routes in the app router configuration so that `/permissions`, `/permissions/tags`, `/permissions/roles`, `/permissions/groups`, `/permissions/users`, and `/permissions/access-requests` resolve correctly. Gate all routes with admin role check. — _Done when: navigating to `/permissions` renders the layout; tab navigation changes the active sub-page; non-admin users are redirected to the dashboard._

---

### Phase 6: Frontend Pages

- [ ] **Task: Implement Tags page** — Create `frontend/src/pages/permissions/TagsPage.tsx`. Render a searchable table of tag definitions (key, scope, resource type, allowed values count, created date). Include a toolbar with "Add Tag" button (opens a dialog for key, scope, resource type, and allowed-values multi-input). Allow editing and deleting rows. All text through `t()`. — _Done when: tag list loads from `permissionsStore`; add/edit/delete operations call the store actions and reflect in the table without full page reload; no hardcoded strings._

- [ ] **Task: Implement Roles page** — Create `frontend/src/pages/permissions/RolesPage.tsx`. Render a table of roles (name, description, policy count, user/group assignment count). Row expand or drawer shows policy statements with module, actions, resource scope, and tag conditions. Include create, edit, and delete role dialogs. Delete shows confirmation when the role has active assignments. All text through `t()`. — _Done when: role list and expanded policy detail render correctly; delete of an assigned role prompts confirmation; all CRUD operations update store state._

- [ ] **Task: Implement Groups page** — Create `frontend/src/pages/permissions/GroupsPage.tsx`. Render a table of groups (name, owner, member count, role count, IdP claim value). Row actions: view members, edit group, delete group. Edit dialog includes name, description, owner picker, role assignment, and IdP claim value input. Admins see all actions; group owners see only edit for their own group. All text through `t()`. — _Done when: group list renders; admin and group-owner permission checks gate action buttons correctly; member list and role list render in a detail drawer._

- [ ] **Task: Implement Users page** — Create `frontend/src/pages/permissions/UsersPage.tsx`. Render a paginated table of platform users (display name, email, direct role count, group count, last seen). Row click opens a detail panel showing assigned roles (with remove option) and group memberships (with remove option). Toolbar button "Add Role" / "Add to Group" opens respective assignment dialogs. All text through `t()`. — _Done when: paginated list loads correctly; role and group assignment dialogs call the correct API actions; removals update the detail panel immediately._

- [ ] **Task: Implement Access Requests page** — Create `frontend/src/pages/permissions/AccessRequestsPage.tsx`. Admins and group owners see a table of pending requests (requester name, group name, requested date). Each row has Approve and Reject actions (reject opens a reason dialog). Regular users see a "My Requests" tab showing their own requests with status badges. Include a "Request Access" button that shows available groups and submits a join request. All text through `t()`. — _Done when: admin/owner view shows pending requests from `permissionsStore`; approve/reject call the correct API actions and update the list; user view shows own request statuses; no hardcoded strings._

- [ ] **Task: Implement useTagValueOptions hook and tag-value dropdowns** — Create `frontend/src/hooks/useTagValueOptions.ts`: given a tag key, returns the array of allowed values from the tag definition store. Wire this hook into the Role policy builder tag condition rows so the value field is a select populated from allowed values. — _Done when: selecting a tag key in the policy builder updates the value dropdown; selecting no key shows a disabled placeholder._

- [ ] **Task: Complete ManageAccessModal component** — Create `frontend/src/components/permissions/ManageAccessModal.tsx`: tabbed modal for a given user showing Direct Roles tab (list + assign/remove) and Group Memberships tab (list + assign/remove). Wire to the Manage Access button in the Users page. — _Done when: both tabs render correct data; assign and remove actions call the appropriate platform-users API endpoints and refresh the displayed lists._

---

### Phase 7: Testing

- [ ] **Task: Unit tests for Permission Engine** — Write unit tests in `backend/tests/unit/` for `PermissionEngine.authorize()`. Cover: allow when matching policy exists, deny when no policy matches, deny when module does not match, deny when action not in policy actions, deny when required tag condition is not met, allow when all tag conditions are satisfied. Use mocked database session. — _Done when: all six test cases pass; no database calls hit a real DB; test file is named `test_permission_engine.py`._

- [ ] **Task: Unit tests for Group Claim Mapper and User Cache Service** — Write unit tests in `backend/tests/unit/` for `GroupClaimMapper.map_claims()` and `UserCacheService.upsert_user()`. For mapper: covers new membership creation, idempotency on existing membership, and no-op when no claims match. For cache: covers create on first call and last_seen_at update on subsequent calls. — _Done when: all test cases pass with mocked DB sessions; test files are `test_group_claim_mapper.py` and `test_user_cache_service.py`._

- [ ] **Task: API tests for Tags and Roles endpoints** — Write API integration tests in `backend/tests/api/` for the Tags and Roles routers using the existing test client and auth fixtures. Cover CRUD happy paths and auth/permission failures (non-admin gets 403 on write operations). — _Done when: all happy-path and 403 test cases pass; test files are `test_tags_api.py` and `test_roles_api.py`._

- [ ] **Task: API tests for Groups, Users, and Access Requests endpoints** — Write API integration tests in `backend/tests/api/` for Groups, Platform Users, and Access Requests routers. For access requests: cover submit, approve, reject, duplicate-submit returning 409, and owner-only approval guard. — _Done when: all test cases pass; test files are `test_groups_api.py`, `test_platform_users_api.py`, and `test_access_requests_api.py`._

- [ ] **Task: Frontend unit tests for permissions store and API client** — Write tests in `frontend/src/__tests__/` for `permissionsStore` and `permissionsApi`. Store tests verify loading flags and error state transitions. API client tests verify correct endpoint paths and typed return values (using msw or vi.fn mocks). — _Done when: all tests pass via `vitest`; coverage includes at least one action per entity type (tags, roles, groups, users, access requests); test files are `permissionsStore.test.ts` and `permissionsApi.test.ts`._

- [ ] **Task: Frontend component tests for permission pages** — Write component render tests in `frontend/src/__tests__/` for each of the five permission pages using React Testing Library. Verify: table renders with mocked store data, loading state shows a spinner, and key action buttons are present. — _Done when: all five page components render without errors in the test environment; at least one interaction test per page (e.g., clicking "Add Tag" opens the dialog); test files are named `TagsPage.test.tsx`, `RolesPage.test.tsx`, `GroupsPage.test.tsx`, `UsersPage.test.tsx`, and `AccessRequestsPage.test.tsx`._

- [ ] **Task: E2E Playwright tests for all permission management user journeys** — Create `e2e/tests/permissions.spec.ts`. Implement full user-journey E2E tests using `page.route()` to mock all API calls. Cover: tag creation (add-button value entry), role creation with wildcard resource ID and tag condition value dropdown, group creation with IdP claim binding, access request submit (multi-group + justification), access request approve (with optional note) and reject (with required reason), Manage Access modal (assign and remove direct roles and group memberships), and non-admin redirect from `/permissions`. Each scenario must include real UI interactions (clicks, form fills, navigation) and specific assertions on outcomes. — _Done when: all scenarios pass via `npx playwright test e2e/tests/permissions.spec.ts`; all API calls are mocked with `page.route()`; no live backend required; spec file is `e2e/tests/permissions.spec.ts`._

---

### Phase 8: API Namespace Refactoring

- [x] **Task: Rename backend Tag router file and update prefix to `/user-tags`** — Rename `backend/app/api/v1/tags.py` to `backend/app/api/v1/user_tags.py`. Update the router prefix from `/tags` to `/user-tags` inside the file. Update the import and `include_router` call in `backend/app/api/v1/__init__.py` to reference `user_tags` with prefix `/user-tags`. — _Done when: `GET /api/v1/user-tags/definitions` returns tag definitions; `GET /api/v1/tags/definitions` returns 404; no remaining references to the old `/tags` prefix in the router or `__init__.py`._

- [x] **Task: Rename backend Roles router file and update prefix to `/user-roles`** — Rename `backend/app/api/v1/roles.py` to `backend/app/api/v1/user_roles.py`. Update the router prefix from `/roles` to `/user-roles` inside the file. Update `backend/app/api/v1/__init__.py` accordingly. — _Done when: `GET /api/v1/user-roles` returns roles; `GET /api/v1/roles` returns 404._

- [x] **Task: Rename backend Groups router file and update prefix to `/user-groups`** — Rename `backend/app/api/v1/groups.py` to `backend/app/api/v1/user_groups.py`. Update the router prefix from `/groups` to `/user-groups` inside the file. Update `backend/app/api/v1/__init__.py` accordingly. — _Done when: `GET /api/v1/user-groups` returns groups; `GET /api/v1/groups` returns 404._

- [x] **Task: Rename backend Access Requests router file and update prefix to `/user-access-requests`** — Rename `backend/app/api/v1/access_requests.py` to `backend/app/api/v1/user_access_requests.py`. Update the router prefix from `/access-requests` to `/user-access-requests` inside the file. Update `backend/app/api/v1/__init__.py` accordingly. — _Done when: `POST /api/v1/user-access-requests` accepts a batch submission; `POST /api/v1/access-requests` returns 404._

- [x] **Task: Update frontend API client endpoint paths in `permissionsApi.ts`** — Edit `frontend/src/api/permissionsApi.ts` to change all endpoint base paths: `/tags` → `/user-tags`, `/roles` → `/user-roles`, `/groups` → `/user-groups`, `/access-requests` → `/user-access-requests`. The `/platform-users` path is unchanged. — _Done when: TypeScript compiler reports no errors; all API functions target the correct `/user-*` paths; no references to the old unprefixed paths remain._

- [x] **Task: Update frontend route from `/permissions` to `/user-permissions`** — In the app router configuration and in `frontend/src/pages/permissions/PermissionsPage.tsx`, rename the route base from `/permissions` to `/user-permissions`. Update all sub-route paths: `/user-permissions/tags`, `/user-permissions/roles`, `/user-permissions/groups`, `/user-permissions/users`, `/user-permissions/access-requests`. Update any sidebar or navigation links that reference `/permissions`. — _Done when: navigating to `/user-permissions` renders the layout; all five sub-routes resolve correctly; `/permissions` is no longer registered; non-admin users are redirected from `/user-permissions`._

- [x] **Task: Update backend API tests to use `/user-*` endpoint paths** — Edit `backend/tests/api/test_tags_api.py`, `test_roles_api.py`, `test_groups_api.py`, and `test_access_requests_api.py` to use `/user-tags`, `/user-roles`, `/user-groups`, and `/user-access-requests` paths respectively. `test_platform_users_api.py` paths are unchanged. — _Done when: all backend API tests pass; no test file references the old `/tags`, `/roles`, `/groups`, or `/access-requests` prefixes._

- [x] **Task: Update frontend unit tests to use `/user-*` paths and `/user-permissions` route** — Edit `frontend/src/__tests__/permissionsApi.test.ts` to update all mocked endpoint paths to the new `/user-*` equivalents. Edit all five page component test files to update any route assertions from `/permissions` to `/user-permissions`. — _Done when: all frontend unit and component tests pass via `vitest`; no test references old paths._

- [x] **Task: Update E2E Playwright tests to use `/user-permissions` route and `/user-*` mock paths** — Edit `e2e/tests/permissions.spec.ts` to update all `page.goto('/permissions...')` calls to `/user-permissions...` and all `page.route('/api/v1/tags...')`, `page.route('/api/v1/roles...')`, `page.route('/api/v1/groups...')`, and `page.route('/api/v1/access-requests...')` mocks to their `/user-*` equivalents. — _Done when: all E2E scenarios pass via `npx playwright test e2e/tests/permissions.spec.ts`; no `page.goto` or `page.route` call uses an old unprefixed path._

---

### Phase 9: Permission-Based Access Control Refinement

- [ ] **Task 9.1: Add role_type column to Role model + generate migration** — Add a `role_type` string column (nullable, default `None`) to the `Role` SQLAlchemy model in `backend/app/db/models/role.py`. Run `alembic revision --autogenerate -m "add_role_type_to_role"` and apply with `alembic upgrade head`. — _Done when: `Role` model has a `role_type` column; migration file is present in `backend/alembic/versions/`; `alembic upgrade head` succeeds; existing roles are unaffected (column is nullable)._

- [ ] **Task 9.2: Create Bootstrap Service with system admin role seeding** — Create `backend/app/services/permissions/bootstrap_service.py` with a `BootstrapService` class. Implement `seed_system_admin_role(db)` that checks for an existing `Role` with `role_type = "system"` and name `"system_admin"`; if absent, creates it with a full-access policy statement. Register it as a FastAPI startup event handler in `backend/app/main.py`. — _Done when: starting the app with an empty database creates the `system_admin` role; restarting does not create a duplicate; the role's `role_type` is `"system"`._

- [ ] **Task 9.3: Replace require_admin dependency with require_permission pattern** — Create a `require_permission(module, action)` FastAPI dependency factory in `backend/app/api/deps.py`. The dependency resolves the calling user's identity from the JWT, calls `PermissionEngine.authorize()`, and raises `403` on deny. Replace any hardcoded admin role checks in `backend/app/api/deps.py` (e.g., `require_admin`) with `require_permission` calls using the appropriate module and action. — _Done when: `require_permission("admin", "write")` returns 403 for a user without a matching policy; a user assigned a role with a matching policy is granted access; existing `require_admin` usages are removed._

- [ ] **Task 9.4: Update all user permission API routers to use permission checks** — Update all five user permission routers (`user_tags.py`, `user_roles.py`, `user_groups.py`, `platform_users.py`, `user_access_requests.py`) to replace any hardcoded admin role assertions with `Depends(require_permission(...))`. Use module name `"user_permissions"` and action `"write"` for mutating operations, `"read"` for list/get operations restricted to admins. — _Done when: all admin-gated endpoints in the five routers use `require_permission`; no router contains a direct role name string comparison; API behaviour is unchanged for users holding the system_admin role._

- [ ] **Task 9.5: Update frontend to display system role indicator and disable edit/delete for system roles** — In `frontend/src/pages/permissions/RolesPage.tsx`, add a visual indicator (e.g., a chip or badge) for roles where `role_type === "system"`. Disable the edit and delete action buttons for system roles. Update `frontend/src/types/permissions.ts` to add the optional `role_type` field to the `Role` interface. Add the corresponding i18n key `permissions.roles.systemRoleBadge` to `frontend/src/i18n/locales/en.json`. — _Done when: the `system_admin` role displays the system indicator in the Roles table; the edit and delete buttons are disabled for that row; all text goes through `t()`; TypeScript compiles without errors._

---

### Phase 10: Refinement — UI and Manifest Enhancement

- [ ] **Task 10.1: Create backend resource type manifest** — Create `backend/app/core/resource_types.py` containing a `ResourceTypeManifest` dict (or typed dataclass) that maps every platform resource type identifier to its allowed action set. Include at minimum: `agent`, `mcp_server`, `conversation`, `group`, `user`, `tag`, `role`, `access_request`. Each entry lists allowed actions (e.g., `read`, `write`, `delete`, `execute`). Export named string constants for each resource type identifier so routers can import them instead of using raw strings. — _Done when: the file exists with all resource types and action sets defined; all string constants are exported; no raw resource type strings remain in the file itself._

- [ ] **Task 10.2: Create frontend resource type mirror** — Create `frontend/src/constants/resourceTypes.ts` as a TypeScript `const` object that mirrors the backend `ResourceTypeManifest`. Each key is a resource type identifier and each value is a readonly array of allowed action strings. This file is consumed by the `RolePolicyDialog` to populate resource type and action dropdowns without hardcoding strings in the component. — _Done when: the file exists and compiles without TypeScript errors; all resource types from the backend manifest are present; the object is typed with a specific interface (no `any`); the file is imported by `RolesPage.tsx` or `RolePolicyDialog`._

- [ ] **Task 10.3: Refactor RolesPage to single-dialog policy management pattern** — Refactor `frontend/src/pages/permissions/RolesPage.tsx` to match the prototype at `docs/changes/user-permission-management/prototype/index.html`. Replace any existing multi-step or side-drawer policy editing flows with a single comprehensive `RolePolicyDialog` component (defined in the same file or as a co-located component). The dialog opens when a role row is selected and shows the full list of policy statements with inline add and delete controls. The `permissionsStore` Roles slice must expose a `setSelectedRole` action and a `selectedRole` field to drive dialog open/close state. Resource type and action inputs inside the dialog must use `RESOURCE_TYPES` from `frontend/src/constants/resourceTypes.ts`. All text through `t()`. — _Done when: clicking a role row opens the single dialog showing all policy statements; add and remove policy actions update the store and reflect immediately in the dialog without closing it; system roles have all controls disabled; TypeScript compiles without errors._

- [ ] **Task 10.4: Update permission error responses to include required_permission field** — Create `backend/app/schemas/errors.py` with `RequiredPermission` (fields: `resource_type: str`, `action: str`, `resource_id: str | None`) and `PermissionDeniedDetail` (fields: `detail: str`, `required_permission: RequiredPermission`) Pydantic models. Update the `require_permission` dependency in `backend/app/api/deps.py` to construct and pass a `PermissionDeniedDetail` instance as the `detail` argument when raising `HTTPException(status_code=403)`. — _Done when: a denied request returns a 403 body containing `{"detail": "...", "required_permission": {"resource_type": "...", "action": "...", "resource_id": null}}`; a unit test confirms the response shape; existing 403 responses from other error paths are unaffected._

- [ ] **Task 10.5: Update PermissionEngine to validate against manifest** — In `backend/app/services/permissions/permission_engine.py`, import `ResourceTypeManifest` from `backend/app/core/resource_types.py`. At the start of `PermissionEngine.authorize()`, check that the `resource_type` argument is a key in the manifest and that the `action` argument is in the allowed actions for that type. Raise a structured `ValueError` (or return a deny result with a descriptive reason) when either check fails, rather than proceeding silently with unknown values. — _Done when: calling `authorize()` with an unknown resource type or unsupported action returns a deny result with a reason string indicating the invalid input; unit tests cover both invalid-resource-type and invalid-action cases._

- [ ] **Task 10.6: Update all permission routers to use manifest constants** — In all five user permission routers (`backend/app/api/v1/user_tags.py`, `user_roles.py`, `user_groups.py`, `platform_users.py`, `user_access_requests.py`), replace any raw resource type string literals passed to `require_permission(...)` with the named constants imported from `backend/app/core/resource_types.py`. — _Done when: no raw resource type string literal appears in any of the five router files; all constants resolve to the same values as the replaced strings; all existing API tests continue to pass._

- [ ] **Task 10.7: Update frontend error handling to display permission requirements** — In the frontend API client (`frontend/src/api/permissionsApi.ts`) or a shared error handler, detect 403 responses that contain a `required_permission` field and extract its `resource_type`, `action`, and `resource_id`. Pass this information to the UI layer (via a toast or inline error) as a user-readable message constructed from an i18n key (e.g., `permissions.errors.missingPermission`). Add the required i18n key to `frontend/src/i18n/locales/en.json`. — _Done when: a mocked 403 response with a `required_permission` body causes the UI to display a specific message rather than a generic error; the message string is sourced from `t()`; TypeScript compiles without errors._
