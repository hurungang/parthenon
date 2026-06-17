/**
 * FIX-20260518-140000 — Issue 3: Missing SOP → Skill Auto-Selection
 *
 * Reproduction test. When a user selects a SOP (Standard Operating Procedure)
 * in AgentRoleDialog, any skills required by that SOP should be:
 *   1. Automatically checked (selected) in the Skill list
 *   2. Made read-only/disabled so the user cannot accidentally uncheck them
 *
 * Expected result AFTER fix:
 *   - Selecting a SOP causes its required_skill_ids to be auto-checked
 *   - Those skill checkboxes become disabled (cannot be manually unchecked)
 *
 * Current (broken) behaviour:
 *   - toggleSop() only toggles the SOP ID in selectedSopIds state
 *   - No logic reads required_skill_ids or modifies selectedSkillIds
 *   - Skill checkboxes remain unchecked and enabled → tests FAIL
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

// ── Module mocks ──────────────────────────────────────────────────────────────

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockGet = vi.fn()
const mockPost = vi.fn()
const mockPut = vi.fn()

vi.mock('../../api/apiClient', () => ({
  default: {
    get: mockGet,
    post: mockPost,
    put: mockPut,
  },
}))

vi.mock('../../components/permissions/PermissionDeniedAlert', () => ({
  default: ({ fallbackMessage }: { error: unknown; fallbackMessage?: string }) => (
    <div data-testid="perm-alert">{fallbackMessage}</div>
  ),
}))

vi.mock('../../pages/agents/AssignIdentitiesToRoleDialog', () => ({
  AssignIdentitiesToRoleDialog: () => <div data-testid="assign-identities-dialog" />,
}))

// ── Test data ─────────────────────────────────────────────────────────────────

// The skill that is required by the SOP below
const REQUIRED_SKILL = {
  id: 'skill-uuid-required-001',
  name: 'Data Extraction Skill',
  description: 'Required by the Onboarding SOP',
  is_active: true,
  tool_ids: [],
  tool_binding_count: 1,
}

const OPTIONAL_SKILL = {
  id: 'skill-uuid-optional-002',
  name: 'Reporting Skill',
  description: 'Not required by any SOP',
  is_active: true,
  tool_ids: [],
  tool_binding_count: 0,
}

// SOP with a required_skill_ids field — the fix is expected to populate this
// from the backend and use it to auto-select skills in AgentRoleDialog.
const SOP_WITH_REQUIRED_SKILLS = {
  id: 'sop-uuid-onboarding-001',
  name: 'Onboarding SOP',
  description: 'Standard employee onboarding procedure',
  required_skill_ids: [REQUIRED_SKILL.id], // field that the fix must add/use
  steps: [],
}

// ── Wrapper ───────────────────────────────────────────────────────────────────

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('Issue 3 — AgentRoleDialog: SOP→Skill Auto-Selection (FIX-20260518-140000)', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  function setupMocks() {
    mockGet.mockImplementation((url: string) => {
      if (url === '/sops') {
        return Promise.resolve({ data: [SOP_WITH_REQUIRED_SKILLS] })
      }
      if (url === '/skills') {
        return Promise.resolve({ data: [REQUIRED_SKILL, OPTIONAL_SKILL] })
      }
      // Identities, MCP sessions — return empty
      return Promise.resolve({ data: [] })
    })
  }

  it('auto-checks required skill when its SOP is selected', async () => {
    setupMocks()
    const { AgentRoleDialog } = await import('../../pages/agents/AgentRoleDialog')

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={vi.fn()} onSaved={vi.fn().mockResolvedValue(undefined)} />,
      { wrapper },
    )

    // Wait for SOPs and skills to load
    const sopCheckbox = await screen.findByRole('checkbox', { name: /Onboarding SOP/i })
    const requiredSkillCheckbox = await screen.findByRole('checkbox', { name: /Data Extraction Skill/i })

    // Initially neither is checked
    expect(sopCheckbox).not.toBeChecked()
    expect(requiredSkillCheckbox).not.toBeChecked()

    // Click the SOP checkbox to select it
    fireEvent.click(sopCheckbox)

    await waitFor(() => {
      // EXPECTED (after fix): required skill auto-selected when SOP is checked
      // ACTUAL (broken): skill remains unchecked — toggleSop() only modifies
      // selectedSopIds, has no logic to update selectedSkillIds
      expect(requiredSkillCheckbox).toBeChecked()
    })
  })

  it('makes required skill checkbox disabled (read-only) when its SOP is selected', async () => {
    setupMocks()
    const { AgentRoleDialog } = await import('../../pages/agents/AgentRoleDialog')

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={vi.fn()} onSaved={vi.fn().mockResolvedValue(undefined)} />,
      { wrapper },
    )

    const sopCheckbox = await screen.findByRole('checkbox', { name: /Onboarding SOP/i })
    const requiredSkillCheckbox = await screen.findByRole('checkbox', { name: /Data Extraction Skill/i })

    // Select the SOP
    fireEvent.click(sopCheckbox)

    await waitFor(() => {
      // EXPECTED (after fix): skill checkbox is disabled so user cannot uncheck it
      // ACTUAL (broken): skill checkbox remains enabled — user can still toggle it
      expect(requiredSkillCheckbox).toBeDisabled()
    })
  })

  it('does NOT disable optional skills when a SOP is selected', async () => {
    setupMocks()
    const { AgentRoleDialog } = await import('../../pages/agents/AgentRoleDialog')

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={vi.fn()} onSaved={vi.fn().mockResolvedValue(undefined)} />,
      { wrapper },
    )

    const sopCheckbox = await screen.findByRole('checkbox', { name: /Onboarding SOP/i })
    const optionalSkillCheckbox = await screen.findByRole('checkbox', { name: /Reporting Skill/i })

    // Select the SOP
    fireEvent.click(sopCheckbox)

    await waitFor(() => {
      // Optional skill (not in SOP required_skill_ids) must remain editable
      expect(optionalSkillCheckbox).not.toBeDisabled()
    })
  })

  it('un-checks and re-enables required skill when SOP is deselected', async () => {
    setupMocks()
    const { AgentRoleDialog } = await import('../../pages/agents/AgentRoleDialog')

    render(
      <AgentRoleDialog open={true} editRole={null} onClose={vi.fn()} onSaved={vi.fn().mockResolvedValue(undefined)} />,
      { wrapper },
    )

    const sopCheckbox = await screen.findByRole('checkbox', { name: /Onboarding SOP/i })
    const requiredSkillCheckbox = await screen.findByRole('checkbox', { name: /Data Extraction Skill/i })

    // Select SOP (skill becomes auto-checked + disabled per the fix)
    fireEvent.click(sopCheckbox)

    // Now deselect the SOP
    fireEvent.click(sopCheckbox)

    await waitFor(() => {
      // When SOP is unchecked, skill should no longer be forced-selected
      // EXPECTED (after fix): skill becomes unchecked AND enabled again
      // ACTUAL (broken): test FAILS at the check step above (skill was never checked)
      expect(requiredSkillCheckbox).not.toBeChecked()
      expect(requiredSkillCheckbox).not.toBeDisabled()
    })
  })
})
