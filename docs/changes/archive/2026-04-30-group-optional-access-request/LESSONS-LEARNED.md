# Lessons Learned: group-optional-access-request

## Issue: Migration Not Applied, Tests Still Passed

### What Happened

**Production Failure:**
- User submitted access request with empty group_ids
- Backend returned 500 Internal Server Error with CORS error (misleading)
- Root cause: Alembic migration `dd1dd4f940eb_make_access_request_group_id_optional.py` was generated but never applied to the database
- Database still had `group_id NOT NULL` constraint, rejected the INSERT with NULL value

**Why Tests Didn't Catch It:**

1. **Backend tests**: Used `db_session` fixture that applies migrations automatically in test database
   - Tests passed because test DB had correct schema
   - Never tested against the actual running database

2. **E2E tests**: ALL tests used `page.route()` to mock API calls
   - Never hit the real backend
   - Never touched the real database
   - Couldn't possibly catch migration issue

3. **No schema verification**: No test queried `information_schema` to verify migration actually ran

### The Gap

Tests validated **logic** but not **deployment readiness**. A change requiring database migration can pass all tests while being completely broken in production.

---

## Fixes Applied

### 1. Updated Memory (`/memories/backend-architecture.md`)

Added **Testing Database Migrations (CRITICAL)** section with:
- Rule: Backend integration tests MUST use real database
- Rule: E2E tests need both mocked AND real backend variants
- Pre-test checklist for database changes
- Tester agent instructions for schema verification

### 2. Updated Change-Lifecycle Skill

Added to `test-plan.md` format requirements:

**CRITICAL for Database Changes** section requiring:
1. Backend integration tests verify schema changes took effect (query `information_schema`)
2. E2E tests include at least ONE real backend variant (no mocks)
3. Pre-test checklist: verify migration applied before testing

### 3. Immediate Fix

Ran `alembic upgrade head` to apply the migration. Feature now works correctly.

---

## Action Items for Future Changes

### For Database Schema Changes (`has_db_changes: true`)

**Database Designer Agent:**
- Generate migration: `alembic revision --autogenerate -m "description"`
- Document migration in data-model.md with file reference

**Developer Agent:**
- **MUST run**: `alembic upgrade head` after generating migration (before testing)
- Verify with: `alembic current` shows new migration ID
- Update implementation-plan.md to include this step

**Tester Agent:**

Backend integration tests MUST:
```python
# Verify schema change took effect
async def test_group_id_is_nullable(db_session):
    """Verify access_request.group_id column is nullable in database."""
    result = await db_session.execute(text("""
        SELECT is_nullable
        FROM information_schema.columns
        WHERE table_name = 'access_request' AND column_name = 'group_id'
    """))
    is_nullable = result.scalar()
    assert is_nullable == 'YES'

# Test actual constraint (not just service logic)
async def test_can_insert_null_group_id(db_session):
    """Verify we can actually insert NULL into group_id (tests real DB constraint)."""
    request = AccessRequest(
        batch_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        group_id=None,  # This would fail if migration wasn't applied
        status=AccessRequestStatus.pending
    )
    db_session.add(request)
    await db_session.commit()  # Must not raise constraint violation
```

E2E tests MUST include at least one real backend test:
```typescript
test.describe('Real Backend Integration - Group Optional Access Request', () => {
  // NO page.route() mocks in this test - hits real backend
  test('user can submit access request without group (real API call)', async ({ page }) => {
    // This test would have caught the missing migration
    await page.goto('http://localhost:5173/permissions/access-requests')
    await page.click('[data-testid="request-access-button"]')
    await page.fill('[data-testid="justification-input"]', 'Need access')
    await page.click('[data-testid="submit-button"]')
    
    // Real API POST to http://localhost:8000/api/v1/user-access-requests
    // Would fail with 500 if migration not applied
    await expect(page.locator('[data-testid="success-message"]')).toBeVisible()
  })
})
```

### Pre-Test Checklist (Conductor Agent)

Before delegating to Tester agent for `has_db_changes: true`:

1. ✅ Verify migration file exists: `backend/alembic/versions/<id>_<description>.py`
2. ✅ Verify migration applied locally: `alembic current` shows new migration ID
3. ✅ If not applied: `alembic upgrade head` immediately
4. ✅ Instruct Tester: "Include schema verification tests and at least one real backend E2E test"

---

## Summary

**Root Cause**: Inadequate test coverage for deployment artifacts (migrations)

**Solution**: 
1. Memory updated with testing guidelines
2. Skills updated with mandatory requirements
3. Process includes migration verification step

**Result**: Future database changes will be tested against real databases with real constraints, catching migration issues before production.
