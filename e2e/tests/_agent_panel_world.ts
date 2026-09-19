import type { Locator, Page } from '@playwright/test'

/**
 * Shared mock world for the Agent Management Panel E2E specs.
 *
 * Follows the established `_helpers.ts` conventions:
 *  - `mockApiCatchAllProxyAware` + `standardSetup` are registered by the spec
 *    BEFORE this world (this file's routes are registered after, so they win —
 *    Playwright resolves route handlers last-registered-first).
 *  - Full-URL regexes are used because Playwright `**` globs do not match
 *    cross-port requests; the regex form matches BOTH the same-origin
 *    `/api/v1/...` requests emitted by the preview build and direct
 *    `http://localhost:8000/api/v1/...` calls.
 *
 * The world keeps MUTABLE state (agents/roles/skills/sops/data-types arrays)
 * so inline create flows (POST handlers push into the arrays) are visible to
 * subsequent GETs exactly like the real backend. Every request is logged into
 * `state.requests` via a highest-priority observer route (`route.fallback()`)
 * so specs can assert "zero network requests" for draft-only mutations.
 */

const T = '2026-06-01T00:00:00Z'

export const PANEL_ROLE = {
  id: 'role-p1',
  name: 'panel-e2e-role',
  description: 'E2E panel role',
  sop_ids: ['sop-p1'],
  skill_ids: ['skill-p1'],
  allowed_identity_types: [] as string[],
  created_at: T,
  updated_at: T,
}

export const PANEL_SOP = {
  id: 'sop-p1',
  name: 'panel-e2e-sop',
  description: null,
  instructions: null,
  is_active: true,
  created_at: T,
  updated_at: T,
}

/**
 * SOP detail: sop-p1 composes skill-p2 ("panel-e2e-sop-skill") via a
 * skill_invocation step — the panel topology derives the SOP → skill → tool
 * chain from this.
 */
export const PANEL_SOP_DETAIL = {
  ...PANEL_SOP,
  steps: [
    {
      id: 'step-p1',
      sop_id: 'sop-p1',
      order: 1,
      step_type: 'skill_invocation',
      skill_id: 'skill-p2',
      target_agent_type_id: null,
      step_config: null,
      name: null,
      description: null,
      created_at: T,
    },
  ],
}

export const PANEL_SKILL = {
  id: 'skill-p1',
  name: 'panel-e2e-skill',
  description: null,
  instructions: null,
  instructions_with_tools: null,
  is_active: true,
  is_system: false,
  tool_ids: [] as string[],
  created_at: T,
  updated_at: T,
}

/** Skill composed under sop-p1 (NOT directly bound to any agent). */
export const PANEL_SOP_SKILL = {
  id: 'skill-p2',
  name: 'panel-e2e-sop-skill',
  description: null,
  instructions: null,
  instructions_with_tools: null,
  is_active: true,
  is_system: false,
  tool_ids: ['tool-p1'] as string[],
  created_at: T,
  updated_at: T,
}

export const PANEL_MCP_SERVER = {
  id: 'srv-p1',
  name: 'panel-e2e-server',
  slug: 'panel-e2e-server',
  base_url: 'http://panel-e2e-server.local',
  description: null,
  is_active: true,
  created_at: T,
  updated_at: T,
}

/** MCP tool called by the composed skill-p2. */
export const PANEL_MCP_TOOL = {
  id: 'tool-p1',
  server_id: 'srv-p1',
  name: 'panel____search',
  description: null,
  input_schema: null,
  is_active: true,
  created_at: T,
  updated_at: T,
}

export const PANEL_IDENTITY = {
  id: 'ident-p1',
  name: 'panel-e2e-identity',
  identity_type: 'user',
  realm_name: 'ai_agents',
  realm_username: 'panel-e2e-identity',
  status: 'active',
  token_expires_at: null,
  has_refresh_token: true,
  created_at: T,
  updated_at: T,
}

export const PANEL_DATA_TYPE = {
  id: 'dt-p1',
  name: 'Panel E2E Report',
  slug: 'panel-e2e-report',
  description: null,
  fields: [
    { name: 'summary', type: 'string', enum_values: null, required: false, default: null },
  ],
  created_at: T,
  updated_at: T,
}

export const PANEL_MODEL_CONFIG = {
  id: 'mc-p1',
  display_name: 'Panel E2E GPT',
  provider_type: 'openai',
  api_base_url: null,
  enabled_models: ['gpt-4o'],
  has_credentials: true,
  created_at: T,
  updated_at: T,
}

type AgentOverrides = Record<string, unknown>

/** Full AgentType fixture with sensible equipment defaults. */
export function makeAgentType(id: string, name: string, overrides: AgentOverrides = {}) {
  return {
    id,
    name,
    description: 'E2E panel agent',
    identity_id: null,
    role_id: 'role-p1',
    model_id: 'gpt-4o',
    system_instruction: 'You are an e2e panel agent.',
    input_type: 'none',
    input_schema: null,
    output_type: 'auto',
    output_schema: null,
    output_data_type_id: null,
    output_data_type_name: null,
    sop_bindings: [{ sop_id: 'sop-p1', order: 1 }],
    skill_bindings: [{ skill_id: 'skill-p1', order: 1 }],
    guardrail_max_iterations: 10,
    guardrail_max_delegation_depth: 3,
    guardrail_max_delegated_steps: 20,
    guardrail_execution_timeout_seconds: 300,
    guardrail_token_budget: 100000,
    guardrail_token_enforcement_mode: 'observe',
    guardrail_token_fallback_mode: 'observe_and_log',
    guardrail_conversational_token_visibility_mode: 'enabled',
    guardrail_conversational_continuation_policy: 'allow',
    is_active: true,
    created_at: T,
    updated_at: T,
    plan: null,
    ...overrides,
  }
}

/** Two typed agents with distinct equipment + one conversational agent. */
export function seedAgents() {
  return [
    makeAgentType('at-a', 'panel-e2e-alpha'),
    makeAgentType('at-b', 'panel-e2e-beta', {
      description: 'Beta agent (role only)',
      sop_bindings: [],
      skill_bindings: [],
      model_id: null,
    }),
    makeAgentType('at-c', 'panel-e2e-conv', {
      description: 'Conversational agent',
      input_type: 'conversation',
      output_type: 'auto',
      model_id: null,
    }),
  ]
}

export interface PanelWorldState {
  agents: ReturnType<typeof makeAgentType>[]
  roles: (typeof PANEL_ROLE)[]
  skills: (typeof PANEL_SKILL)[]
  sops: (typeof PANEL_SOP)[]
  dataTypes: (typeof PANEL_DATA_TYPE)[]
  modelConfigs: (typeof PANEL_MODEL_CONFIG)[]
  mcpServers: (typeof PANEL_MCP_SERVER)[]
  mcpTools: (typeof PANEL_MCP_TOOL)[]
  /** Every /api/v1 request seen: "METHOD /pathname" */
  requests: string[]
  /** Bodies of PUT /agents/types/{id} in order. */
  agentPutBodies: Record<string, unknown>[]
  /** Bodies of POST /agents/types. */
  agentPostBodies: Record<string, unknown>[]
  /** Bodies of DELETE targets for /agents/types/{id}. */
  deletedAgentIds: string[]
}

function json(route: import('@playwright/test').Route, status: number, body: unknown) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

/**
 * Locates a MUI `<Select>` combobox by its visible label text. MUI Selects in
 * this codebase do not expose an accessible name that `getByLabel` can
 * resolve, so we locate the enclosing FormControl via the label text.
 * (`hasText` is used instead of `filter({ has })` because a `has` locator
 * built from `scope` would re-anchor the scope *inside* each candidate.)
 */
export function muiCombobox(scope: Locator, labelText: string): Locator {
  return scope
    .locator('.MuiFormControl-root')
    .filter({ hasText: labelText })
    .getByRole('combobox')
}

/**
 * Opens a MUI `<Select>` by label text and picks the first option matching
 * `option` (disabled placeholder options are skipped automatically by
 * Playwright's option matching against enabled elements).
 */
export async function selectMuiOption(
  page: Page,
  scope: Locator,
  labelText: string,
  option: string | RegExp,
) {
  await muiCombobox(scope, labelText).first().click()
  await page.getByRole('option', { name: option }).first().click()
}

/**
 * Registers the full mocked API world for the Agent Management Panel.
 * MUST be called AFTER `mockApiCatchAllProxyAware` / `standardSetup` (its
 * routes take priority over those, and the request observer registered last
 * has the highest priority of all).
 *
 * Returns the mutable state so tests can assert on request traffic and
 * server-side persistence.
 */
export async function mockPanelWorld(
  page: Page,
  opts: { agents?: ReturnType<typeof seedAgents> } = {},
): Promise<PanelWorldState> {
  const state: PanelWorldState = {
    agents: opts.agents ?? seedAgents(),
    roles: [{ ...PANEL_ROLE }],
    skills: [{ ...PANEL_SKILL }, { ...PANEL_SOP_SKILL }],
    sops: [{ ...PANEL_SOP }],
    dataTypes: [{ ...PANEL_DATA_TYPE }],
    modelConfigs: [{ ...PANEL_MODEL_CONFIG }],
    mcpServers: [{ ...PANEL_MCP_SERVER }],
    mcpTools: [{ ...PANEL_MCP_TOOL }],
    requests: [],
    agentPutBodies: [],
    agentPostBodies: [],
    deletedAgentIds: [],
  }

  // ── Agent types (list + CRUD) ────────────────────────────────────────────
  await page.route(/\/api\/v1\/agents\/types(\?.*)?$/, (route) => {
    const req = route.request()
    if (req.method() === 'GET') return json(route, 200, state.agents)
    if (req.method() === 'POST') {
      const body = req.postDataJSON()
      state.agentPostBodies.push(body)
      const created = makeAgentType(`at-new-${state.agents.length + 1}`, body.name, {
        description: body.description ?? null,
        role_id: body.role_id ?? null,
        identity_id: body.identity_id ?? null,
        model_id: body.model_id ?? null,
        system_instruction: body.system_instruction ?? null,
        input_type: body.input_type ?? 'none',
        output_type: body.output_type ?? 'auto',
        sop_bindings: body.sop_bindings ?? [],
        skill_bindings: body.skill_bindings ?? [],
      })
      state.agents.push(created)
      return json(route, 201, created)
    }
    return json(route, 405, { detail: 'method not allowed' })
  })

  await page.route(/\/api\/v1\/agents\/types\/[^/]+(\?.*)?$/, (route) => {
    const req = route.request()
    const id = req.url().split('/agents/types/')[1]?.split('?')[0]
    const agent = state.agents.find((a) => a.id === id)
    if (req.method() === 'GET') {
      if (!agent) return json(route, 404, { detail: 'not found' })
      return json(route, 200, agent)
    }
    if (req.method() === 'PUT') {
      if (!agent) return json(route, 404, { detail: 'not found' })
      const body = req.postDataJSON()
      state.agentPutBodies.push(body)
      Object.assign(agent, body, { updated_at: new Date().toISOString() })
      return json(route, 200, agent)
    }
    if (req.method() === 'DELETE') {
      state.deletedAgentIds.push(id)
      state.agents = state.agents.filter((a) => a.id !== id)
      return route.fulfill({ status: 204 })
    }
    return json(route, 405, { detail: 'method not allowed' })
  })

  // ── Roles ────────────────────────────────────────────────────────────────
  await page.route(/\/api\/v1\/agents\/roles\/[^/]+\/(identities|mcp-sessions)(\?.*)?$/, (route) =>
    json(route, 200, []),
  )
  await page.route(/\/api\/v1\/agents\/roles(\?.*)?$/, (route) => {
    const req = route.request()
    if (req.method() === 'GET') return json(route, 200, state.roles)
    if (req.method() === 'POST') {
      const body = req.postDataJSON()
      const created = {
        ...PANEL_ROLE,
        id: `role-new-${state.roles.length + 1}`,
        name: body.name,
        description: body.description ?? null,
        sop_ids: body.sop_ids ?? [],
        skill_ids: body.skill_ids ?? [],
        updated_at: new Date().toISOString(),
      }
      state.roles.push(created)
      return json(route, 201, created)
    }
    return json(route, 405, { detail: 'method not allowed' })
  })

  // ── Identities ───────────────────────────────────────────────────────────
  await page.route(/\/api\/v1\/agents\/identities\/[^/]+\/roles(\?.*)?$/, (route) =>
    json(route, 200, [PANEL_ROLE]),
  )
  await page.route(/\/api\/v1\/agents\/identities\/oauth\/authorize(\?.*)?$/, (route) =>
    json(route, 200, { authorization_url: 'http://localhost:8082/realms/ai_agents/protocol/openid-connect/auth?client_id=x' }),
  )
  await page.route(/\/api\/v1\/agents\/identities(\?.*)?$/, (route) =>
    json(route, 200, [PANEL_IDENTITY]),
  )

  // ── Model configs ────────────────────────────────────────────────────────
  await page.route(/\/api\/v1\/agents\/model-configs(\?.*)?$/, (route) => {
    const req = route.request()
    if (req.method() === 'GET') return json(route, 200, state.modelConfigs)
    if (req.method() === 'POST') {
      const body = req.postDataJSON()
      const created = {
        ...PANEL_MODEL_CONFIG,
        id: `mc-new-${state.modelConfigs.length + 1}`,
        display_name: body.display_name,
        provider_type: body.provider_type ?? 'openai',
        enabled_models: body.enabled_models ?? [],
        updated_at: new Date().toISOString(),
      }
      state.modelConfigs.push(created)
      return json(route, 201, { id: created.id, display_name: created.display_name })
    }
    return json(route, 405, { detail: 'method not allowed' })
  })

  // ── Skills ───────────────────────────────────────────────────────────────
  await page.route(/\/api\/v1\/skills\/[^/]+\/roles(\?.*)?$/, (route) => json(route, 200, {}))
  await page.route(/\/api\/v1\/skills(\?.*)?$/, (route) => {
    const req = route.request()
    if (req.method() === 'GET') return json(route, 200, state.skills)
    if (req.method() === 'POST') {
      const body = req.postDataJSON()
      const created = {
        ...PANEL_SKILL,
        id: `skill-new-${state.skills.length + 1}`,
        name: body.name,
        description: body.description ?? null,
        updated_at: new Date().toISOString(),
      }
      state.skills.push(created)
      return json(route, 201, created)
    }
    return json(route, 405, { detail: 'method not allowed' })
  })

  // ── SOPs ─────────────────────────────────────────────────────────────────
  await page.route(/\/api\/v1\/sops\/[^/]+\/(steps|roles)(\?.*)?$/, (route) =>
    json(route, 200, {}),
  )
  await page.route(/\/api\/v1\/sops\/[^/]+(\?.*)?$/, (route) => {
    const req = route.request()
    if (req.method() === 'GET') return json(route, 200, PANEL_SOP_DETAIL)
    return json(route, 405, { detail: 'method not allowed' })
  })
  await page.route(/\/api\/v1\/sops(\?.*)?$/, (route) => {
    const req = route.request()
    if (req.method() === 'GET') return json(route, 200, state.sops)
    if (req.method() === 'POST') {
      const body = req.postDataJSON()
      const created = {
        ...PANEL_SOP,
        id: `sop-new-${state.sops.length + 1}`,
        name: body.name,
        description: body.description ?? null,
        updated_at: new Date().toISOString(),
      }
      state.sops.push(created)
      return json(route, 201, created)
    }
    return json(route, 405, { detail: 'method not allowed' })
  })

  // ── Agent Data Types (paginated list) ────────────────────────────────────
  await page.route(/\/api\/v1\/data-types\/[^/]+(\?.*)?$/, (route) => {
    const req = route.request()
    const id = req.url().split('/data-types/')[1]?.split('?')[0]
    const dataType =
      state.dataTypes.find((dt) => dt.id === id) ??
      // Inline-created types referenced by id before the list refetch.
      state.dataTypes[state.dataTypes.length - 1]
    if (req.method() === 'DELETE') return route.fulfill({ status: 204 })
    return json(route, 200, dataType)
  })
  await page.route(/\/api\/v1\/data-types(\?.*)?$/, (route) => {
    const req = route.request()
    if (req.method() === 'GET') {
      return json(route, 200, {
        items: state.dataTypes,
        total: state.dataTypes.length,
        page: 1,
        page_size: 100,
      })
    }
    if (req.method() === 'POST') {
      const body = req.postDataJSON()
      const created = {
        ...PANEL_DATA_TYPE,
        id: `dt-new-${state.dataTypes.length + 1}`,
        name: body.name,
        slug: body.slug,
        description: body.description ?? null,
        fields: body.fields ?? [],
        updated_at: new Date().toISOString(),
      }
      state.dataTypes.push(created)
      return json(route, 201, created)
    }
    return json(route, 405, { detail: 'method not allowed' })
  })

  // ── Supporting lists consumed by the shared dialogs / preview topology ──
  await page.route(/\/api\/v1\/mcp\/servers(\?.*)?$/, (route) => json(route, 200, state.mcpServers))
  await page.route(/\/api\/v1\/mcp\/tools(\?.*)?$/, (route) => json(route, 200, state.mcpTools))
  await page.route(/\/api\/v1\/agents\/sessions(\?.*)?$/, (route) => json(route, 200, []))

  // ── Request observer (highest priority — registered LAST) ───────────────
  // Logs every API request then defers to the real (world/catch-all) handler,
  // so specs can assert that draft mutations fire ZERO network requests.
  await page.route(/\/api\/v1\//, (route) => {
    const req = route.request()
    let pathname = req.url()
    try {
      pathname = new URL(req.url()).pathname
    } catch {
      // keep raw url
    }
    state.requests.push(`${req.method()} ${pathname}`)
    return route.fallback()
  })

  return state
}
