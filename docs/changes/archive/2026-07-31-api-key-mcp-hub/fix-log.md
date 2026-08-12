# Fix Log: api-key-mcp-hub

This document tracks all bug fixes and issues resolved for this change.

---

## FIX-20260731-031408

**Created:** 2026-07-31T03:14:08Z
**Status:** Resolved
**Issue:** 403 Forbidden when accessing API key management endpoints with admin user who has wildcard permissions

### Observed Behavior
Platform administrator (with wildcard permissions granting access to all modules) receives HTTP 403 when accessing `GET /api/v1/api-keys` or any other API key management endpoint. The system admin's wildcard policy should automatically grant access to any new module.

### Expected Behavior
Admin user with wildcard permissions (e.g., `system_admin` role with `*` or `*::*` module policy) should be able to access API key management endpoints without any additional configuration.

### Analysis
- **Affected components:** `backend/app/core/resource_types.py` (missing registration), `backend/app/services/permissions/permission_engine.py` (manifest check), `frontend/src/constants/resourceTypes.ts` (mirror out of sync)
- **Root cause:** The `PermissionEngine.authorize()` method validates that the requested module exists in `ResourceTypeManifest` BEFORE checking any wildcard policies. Since `"api_keys"` was never registered in the manifest, the engine returns `denied` even for users with `*` wildcard policies that would otherwise grant access.
- **Documentation impact:** `docs/config.yaml` updated with critical convention; fix-log.md tracks resolution

### Fix Tasks
- [x] **Reproduce** — Root cause confirmed via code analysis: `"api_keys"` not in `ResourceTypeManifest`
- [x] **Fix** — Registered `"agent::api_keys"` in `ResourceTypeManifest` (backend + frontend mirror) and updated `require_permission()` call
- [x] **Verify** — All 56 backend tests + 18 frontend tests pass
- [x] **Document** — `docs/config.yaml` updated with critical convention

### Implementation Details

**Root cause**: `require_permission("api_keys", "manage")` in `api_keys.py` was rejected by `PermissionEngine.authorize()` because `"api_keys"` was not registered in `ResourceTypeManifest`. The manifest check happens at line 58-63 of `permission_engine.py` BEFORE any wildcard policy evaluation, so even users with `module="*"` policies got 403.

**Fix**: Registered `"agent::api_keys"` as a namespaced resource type in both the backend manifest and frontend mirror, following the project's `module::submodule` naming convention. Changed the `require_permission()` call to use the namespaced name.

### Code Changes

**Modified files:**
1. `backend/app/core/resource_types.py` — Added `RT_API_KEYS = "agent::api_keys"` constant, added to `ResourceTypeManifest` with `["read", "manage"]` actions, added to `"agent"` module group
2. `backend/app/api/v1/api_keys.py` line 45 — Changed `require_permission("api_keys", "manage")` → `require_permission("agent::api_keys", "manage")`
3. `frontend/src/constants/resourceTypes.ts` — Added `"agent::api_keys"` to `RESOURCE_TYPE_MANIFEST` and `MODULE_GROUPS.agents.submodules`
4. `backend/tests/api/v1/test_api_keys_api.py` — Updated 12 `require_permission()` calls to use `"agent::api_keys"`
5. `frontend/src/__tests__/ResourceTypeManifestMirror.test.ts` — Updated counts: 17→19 manifest entries, 12→14 agent submodules

### Documentation Updates
- `docs/config.yaml` — Added critical convention warning future changes to always register new resource types in BOTH backend and frontend manifests
- `docs/changes/api-key-mcp-hub/fix-log.md` — This entry
