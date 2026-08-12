# Implementation Plan: Add Group Claim Mapper to Keycloak Provisioning

## Phase 1: Keycloak Admin Client Enhancement

- [x] **Task 1: Add `_get_client_uuid` helper** — Logic inlined in `create_group_membership_mapper`. Fetches Keycloak internal client UUID by clientId via GET /clients?clientId=.... _Done: resolution logic works for existing and new clients._
- [x] **Task 2: Add `create_group_membership_mapper` method** — Idempotent method in `KeycloakAdminClient` at `keycloak_admin_client.py:322`. Checks existing mappers first, creates if missing, skips if present. _Done: 4 unit tests pass, method is idempotent._
- [x] **Task 3: Add unit tests for `create_group_membership_mapper`** — 4 tests in `test_keycloak_admin_client.py`: idempotent skip, creation, client-not-found error, creation-failure error. _Done: all tests pass._

## Phase 2: Bootstrap Integration

- [x] **Task 4: Integrate into provisioning flow** — `IdentityBootstrapService.provision_bundled_keycloak` now calls `create_group_membership_mapper` after creating the `{client_id}-ui` client. Wrapped in try-except for fire-and-log behavior. _Done: provisioning includes mapper creation._
- [x] **Task 5: Apply to running system** — Added group_membership mapper to the running `parthenon-api-ui` Keycloak client via admin API. _Done: mapper active on running instance._

## Phase 3: Verification

- [x] **Task 6: Run unit tests** — All 10 keycloak admin client tests pass (6 existing + 4 new). All 737 unit tests pass (excluding 11 pre-existing failures unrelated to this change). _Done._
- [x] **Task 7: Verify mapper in Keycloak** — Confirmed mapper exists on running `parthenon-api-ui` client alongside `mcp_role`. _Done._
