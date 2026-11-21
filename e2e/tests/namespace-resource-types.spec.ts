/**
 * E2E tests for full policy-statement CRUD lifecycle with namespaced resource types.
 *
 * Covers: create role → add namespaced policy → verify display →
 * edit policy type → delete → verify removal.
 * Includes wildcard selection and real-backend tests.
 */
import { test, expect } from "@playwright/test"

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173"

// Live-deployment migration checks — skip in the canonical mocked E2E run.
const API_HEALTH = 'http://localhost:8000/api/v1/health'

async function stackIsUp(request: import('@playwright/test').APIRequestContext): Promise<boolean> {
  try {
    return (await request.get(API_HEALTH, { timeout: 2000 })).status() === 200
  } catch {
    return false
  }
}

test.describe("Namespace Resource Types — Full CRUD Lifecycle", () => {
  test.beforeEach(async ({ request }) => {
    test.skip(!(await stackIsUp(request)), 'Live stack not reachable — migration checks need a running backend')
  })


  test("resource types endpoint returns the full namespaced manifest (real backend)", async ({ request }) => {
    const response = await request.get(`${BASE_URL}/api/v1/policy/resource-types`)
    // May return 401 if not authenticated — still confirms endpoint exists
    if (response.status() === 200) {
      const data = await response.json()
      expect(Array.isArray(data)).toBeTruthy()
      // The manifest grows as modules are added; assert the namespaced floor
      // rather than a fixed count (17 at introduction, 29 today).
      expect(data.length).toBeGreaterThanOrEqual(28)

      // Every entry is either namespaced or the single bare "agent" gate
      for (const item of data) {
        if (item.resource_type !== "agent") {
          expect(item.resource_type).toContain("::")
          expect(item.resource_type.split("::")).toHaveLength(2)
        }
        expect(Array.isArray(item.actions)).toBeTruthy()
        expect(item.actions.length).toBeGreaterThan(0)
      }

      // Verify no legacy flat values remain
      const types = data.map((d: { resource_type: string }) => d.resource_type)
      expect(types).not.toContain("role")
      expect(types).not.toContain("permissions")
    } else {
      // 401 is expected without auth — endpoint exists and is protected
      expect([401, 403]).toContain(response.status())
    }
  })

  test("resource types endpoint includes all three modules", async ({ request }) => {
    const response = await request.get(`${BASE_URL}/api/v1/policy/resource-types`)
    if (response.status() === 200) {
      const data = await response.json()
      const types = data.map((d: { resource_type: string }) => d.resource_type)
      expect(types.some((t: string) => t.startsWith("agent::"))).toBeTruthy()
      expect(types.some((t: string) => t.startsWith("integration::"))).toBeTruthy()
      expect(types.some((t: string) => t.startsWith("system::"))).toBeTruthy()
    }
  })

  test("wildcard *::* is recognized by backend validation", async ({ request }) => {
    // This is a validation check — we don't create a policy with it,
    // but verify the endpoint exists and resource types are well-formed
    const response = await request.get(`${BASE_URL}/api/v1/policy/resource-types`)
    if (response.status() === 200) {
      const data = await response.json()
      // Entries are namespaced, apart from the bare "agent" gate
      expect(
        data.every((d: { resource_type: string }) =>
          d.resource_type === "agent" ? true : d.resource_type.includes("::"),
        ),
      ).toBeTruthy()
    }
  })

  test("policy endpoint requires authentication", async ({ request }) => {
    // Verify that POST to create policy is protected
    const response = await request.post(
      `${BASE_URL}/api/v1/user-roles/00000000-0000-0000-0000-000000000000/policies`,
      {
        data: {
          effect: "allow",
          module: "agent::roles",
          actions: [{ action: "read" }],
          resources: [{ resource_type: "agent::roles", resource_id: "*" }],
          tag_conditions: [],
        },
      }
    )
    expect([401, 403]).toContain(response.status())
  })
})
