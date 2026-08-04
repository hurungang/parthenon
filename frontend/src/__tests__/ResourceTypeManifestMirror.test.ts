/**
 * Tests that the frontend resource type manifest mirror stays in sync
 * with the backend manifest. Verifies all 17 identifiers are present,
 * module groupings are correct, and no legacy flat values exist.
 */
import { describe, it, expect } from "vitest"
import {
  RESOURCE_TYPE_MANIFEST,
  MODULE_GROUPS,
  RESOURCE_TYPE_OPTIONS,
  getActionsForResourceType,
  getModuleForResourceType,
} from "../constants/resourceTypes"

describe("ResourceTypeManifestMirror", () => {
  it("has exactly 19 namespaced resource types", () => {
    const keys = Object.keys(RESOURCE_TYPE_MANIFEST)
    expect(keys).toHaveLength(19)
  })

  it("all identifiers use :: delimiter with exactly two layers", () => {
    for (const key of Object.keys(RESOURCE_TYPE_MANIFEST)) {
      expect(key).toMatch(/^[a-z_]+::[a-z_]+$/)
      const parts = key.split("::")
      expect(parts).toHaveLength(2)
    }
  })

  it("has 14 agent submodules", () => {
    expect(MODULE_GROUPS.agents.submodules).toHaveLength(14)
  })

  it("has 2 integration submodules", () => {
    expect(MODULE_GROUPS.integrations.submodules).toHaveLength(2)
  })

  it("has 3 system submodules", () => {
    expect(MODULE_GROUPS.system.submodules).toHaveLength(3)
  })

  it("has three module groups with correct labels", () => {
    expect(MODULE_GROUPS.agents.label).toBe("Agents")
    expect(MODULE_GROUPS.integrations.label).toBe("Integrations")
    expect(MODULE_GROUPS.system.label).toBe("System")
  })

  it("all module group submodules are keys in the manifest", () => {
    const manifestKeys = new Set(Object.keys(RESOURCE_TYPE_MANIFEST))
    for (const group of Object.values(MODULE_GROUPS)) {
      for (const submodule of group.submodules) {
        expect(manifestKeys.has(submodule)).toBe(true)
      }
    }
  })

  it("all manifest keys appear in exactly one module group", () => {
    const seen = new Set<string>()
    for (const group of Object.values(MODULE_GROUPS)) {
      for (const submodule of group.submodules) {
        expect(seen.has(submodule)).toBe(false)
        seen.add(submodule)
      }
    }
    expect(seen.size).toBe(19)
  })

  it("all agent submodules start with 'agent::'", () => {
    for (const submodule of MODULE_GROUPS.agents.submodules) {
      expect(submodule.startsWith("agent::")).toBe(true)
    }
  })

  it("all integration submodules start with 'integration::'", () => {
    for (const submodule of MODULE_GROUPS.integrations.submodules) {
      expect(submodule.startsWith("integration::")).toBe(true)
    }
  })

  it("all system submodules start with 'system::'", () => {
    for (const submodule of MODULE_GROUPS.system.submodules) {
      expect(submodule.startsWith("system::")).toBe(true)
    }
  })

  it("RESOURCE_TYPE_OPTIONS contains all 19 types", () => {
    expect(RESOURCE_TYPE_OPTIONS).toHaveLength(19)
  })

  it("no legacy flat values in the manifest", () => {
    const keys = Object.keys(RESOURCE_TYPE_MANIFEST)
    const legacyValues = [
      "agent", "role", "skill", "sop", "mcp_server", "notification",
      "permissions", "group", "user", "tag", "access_request",
      "conversation", "result", "schedule", "model_config",
      "intervene", "runtime", "identity",
    ]
    for (const legacy of legacyValues) {
      expect(keys).not.toContain(legacy)
    }
  })

  it("getActionsForResourceType returns correct actions", () => {
    expect(getActionsForResourceType("agent::roles")).toEqual(["read", "manage"])
    expect(getActionsForResourceType("system::permissions")).toContain("manage")
    expect(getActionsForResourceType("system::permissions")).toContain("approve")
  })

  it("getActionsForResourceType returns empty array for unknown type", () => {
    expect(getActionsForResourceType("nonexistent::type")).toEqual([])
    expect(getActionsForResourceType("agent")).toEqual([])
    expect(getActionsForResourceType("")).toEqual([])
  })

  it("getModuleForResourceType extracts the module prefix", () => {
    expect(getModuleForResourceType("agent::roles")).toBe("agent")
    expect(getModuleForResourceType("integration::mcp_hub")).toBe("integration")
    expect(getModuleForResourceType("system::permissions")).toBe("system")
  })

  it("getModuleForResourceType returns empty string for flat values", () => {
    expect(getModuleForResourceType("agent")).toBe("")
    expect(getModuleForResourceType("not-namespaced")).toBe("")
    expect(getModuleForResourceType("")).toBe("")
  })

  it("specific submodules are present", () => {
    const keys = Object.keys(RESOURCE_TYPE_MANIFEST)
    // Check key submodules
    expect(keys).toContain("agent::roles")
    expect(keys).toContain("agent::identities")
    expect(keys).toContain("agent::management")
    expect(keys).toContain("agent::runtime_control")
    expect(keys).toContain("agent::skills")
    expect(keys).toContain("agent::sops")
    expect(keys).toContain("agent::model_configs")
    expect(keys).toContain("agent::schedules")
    expect(keys).toContain("agent::trails")
    expect(keys).toContain("agent::human_intervention")
    expect(keys).toContain("agent::data_types")
    expect(keys).toContain("agent::outputs")
    expect(keys).toContain("integration::mcp_hub")
    expect(keys).toContain("integration::notifications")
    expect(keys).toContain("system::observability")
    expect(keys).toContain("system::permissions")
    expect(keys).toContain("system::system_config")
  })
})
