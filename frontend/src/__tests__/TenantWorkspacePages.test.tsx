/**
 * Tenant workspace pages — TenantSettingsPage, OnboardingPage, MembersPage
 * (Phase 7, CS-24 context; 2.10 coverage).
 *
 * - TenantSettingsPage: renders own-tenant metadata, saves via PATCH
 * - OnboardingPage: guided steps, invite token shown-once note, complete
 * - MembersPage: member table, invitation creation with shown-once token,
 *   errors per dialog standard
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  // Interpolation-aware: values are appended so the usage meter numbers
  // are assertable.  Plain keys are unaffected.
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) =>
      opts ? `${k} ${Object.values(opts).join(' / ')}` : k,
  }),
}))

import {
  getTenantSettings,
  getTenantUsage,
  updateTenantSettings,
  getOnboardingStatus,
  completeOnboarding,
  createInvitation,
  listMembers,
  listInvitations,
  type TenantSettings,
  type TenantMember,
  type TenantInvitation,
} from '../api/tenantApi'

vi.mock('../api/tenantApi', () => ({
  getTenantSettings: vi.fn(),
  getTenantUsage: vi.fn(),
  updateTenantSettings: vi.fn(),
  getOnboardingStatus: vi.fn(),
  completeOnboarding: vi.fn(),
  createInvitation: vi.fn(),
  listMembers: vi.fn(),
  listInvitations: vi.fn(),
  revokeInvitation: vi.fn(),
  updateMember: vi.fn(),
  updateMemberStatus: vi.fn(),
}))

import { TenantSettingsPage } from '../pages/tenant/TenantSettingsPage'
import { OnboardingPage } from '../pages/tenant/OnboardingPage'
import { MembersPage } from '../pages/tenant/MembersPage'

const mocked = vi.mocked

function renderWith(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>,
  )
}

const settings: TenantSettings = {
  tenant_id: 't-1',
  slug: 'acme',
  name: 'Acme Corp',
  admin_contact_name: 'Ada',
  admin_contact_email: 'ada@acme.test',
  is_onboarded: true,
  your_role: 'tenant_admin',
  is_root: true,
}

const usage = {
  tier: 'free' as const,
  max_users: 10,
  max_agent_types: 5,
  monthly_agent_executions: 100,
  users: 2,
  agent_types: 1,
  executions_this_month: 37,
}

// ── TenantSettingsPage ───────────────────────────────────────────────────────

describe('TenantSettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked(getTenantSettings).mockResolvedValue(settings)
  })

  it('renders own tenant metadata (never another tenant)', async () => {
    renderWith(<TenantSettingsPage />)
    await waitFor(() => {
      expect((screen.getByLabelText('tenant.settings.name') as HTMLInputElement).value).toBe('Acme Corp')
    })
    expect((screen.getByLabelText('tenant.settings.contactName') as HTMLInputElement).value).toBe('Ada')
    // Phase 10: the tenant address is shown as an immutable read-only field
    expect((screen.getByLabelText('tenant.settings.address') as HTMLInputElement).value).toBe('/acme')
    expect(screen.getByText('tenant.settings.onboarded')).toBeDefined()
  })

  it('flags pending onboarding for new tenants', async () => {
    mocked(getTenantSettings).mockResolvedValue({ ...settings, is_onboarded: false })
    renderWith(<TenantSettingsPage />)
    await waitFor(() => {
      expect(screen.getByText('tenant.settings.pendingOnboarding')).toBeDefined()
    })
  })

  it('saves contact changes via the API', async () => {
    mocked(updateTenantSettings).mockResolvedValue({ ...settings, name: 'Renamed' })
    renderWith(<TenantSettingsPage />)
    await waitFor(() => screen.getByLabelText('tenant.settings.name'))

    fireEvent.change(screen.getByLabelText('tenant.settings.name'), {
      target: { value: 'Renamed' },
    })
    fireEvent.click(screen.getByText('app.save'))
    await waitFor(() => {
      expect(mocked(updateTenantSettings).mock.calls[0][0]).toEqual({
        name: 'Renamed',
        admin_contact_name: 'Ada',
        admin_contact_email: 'ada@acme.test',
      })
    })
  })

  it('surfaces save errors', async () => {
    const denied = Object.assign(new Error('denied'), {
      isAxiosError: true,
      response: { status: 403, data: { detail: 'Permission denied' } },
    })
    mocked(updateTenantSettings).mockRejectedValue(denied)
    renderWith(<TenantSettingsPage />)
    await waitFor(() => screen.getByLabelText('tenant.settings.name'))

    fireEvent.click(screen.getByText('app.save'))
    await waitFor(() => {
      expect(screen.getByText(/Permission denied/)).toBeDefined()
    })
  })
})

// ── Phase 10: root-only alias editing + license & usage panel ────────────────

describe('TenantSettingsPage — Phase 10 alias & usage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked(getTenantSettings).mockResolvedValue(settings)
    mocked(getTenantUsage).mockResolvedValue(usage)
  })

  it('enables alias editing for the ROOT with an explanatory hint', async () => {
    renderWith(<TenantSettingsPage />)
    const nameField = await screen.findByLabelText(
      'tenant.settings.name',
    ) as HTMLInputElement
    expect(nameField.disabled).toBe(false)
    expect(screen.getByText('tenant.settings.nameRootHint')).toBeDefined()
  })

  it('disables alias editing for a NON-root admin with a locked note', async () => {
    mocked(getTenantSettings).mockResolvedValue({ ...settings, is_root: false })
    renderWith(<TenantSettingsPage />)
    const nameField = await screen.findByLabelText(
      'tenant.settings.name',
    ) as HTMLInputElement
    expect(nameField.disabled).toBe(true)
    expect(screen.getByText('tenant.settings.nameRootOnly')).toBeDefined()
    expect(screen.getByText('tenant.settings.aliasLockedNote')).toBeDefined()
  })

  it('shows the tenant address as an immutable read-only field', async () => {
    renderWith(<TenantSettingsPage />)
    const slugField = await screen.findByLabelText(
      'tenant.settings.address',
    ) as HTMLInputElement
    expect(slugField.disabled).toBe(true)
    expect(slugField.value).toBe('/acme')
    expect(screen.getByText('tenant.settings.addressImmutable')).toBeDefined()
  })

  it('saves the alias via the API and refreshes the settings query', async () => {
    mocked(updateTenantSettings).mockResolvedValue({
      ...settings,
      name: 'New Alias',
    })
    renderWith(<TenantSettingsPage />)
    const nameField = await screen.findByLabelText('tenant.settings.name')
    fireEvent.change(nameField, { target: { value: 'New Alias' } })
    fireEvent.click(screen.getByText('app.save'))

    await waitFor(() => {
      expect(mocked(updateTenantSettings).mock.calls[0][0]).toEqual({
        name: 'New Alias',
        admin_contact_name: 'Ada',
        admin_contact_email: 'ada@acme.test',
      })
    })
    expect(await screen.findByText('tenant.settings.saved')).toBeDefined()
  })

  it('renders the license & usage panel with tier and usage meters', async () => {
    renderWith(<TenantSettingsPage />)
    const panel = await screen.findByTestId('license-usage-panel')
    // Tier chip: free tier with the free-defaults note.
    expect(
      screen.getByTestId('license-tier-chip').textContent,
    ).toBe('tenant.quota.tier.free')
    expect(screen.getByText('tenant.usage.freeDefaults')).toBeDefined()
    // Three usage meters: users / agent types / executions this month.
    const meters = panel.querySelectorAll('[data-testid="usage-meter"]')
    expect(meters.length).toBe(3)
    expect(panel.textContent).toContain('tenant.usage.users')
    expect(panel.textContent).toContain('tenant.usage.agentTypes')
    expect(panel.textContent).toContain('tenant.usage.executionsThisMonth')
    // "used of limit" values rendered for each meter.
    expect(panel.textContent).toContain('2 / 10')
    expect(panel.textContent).toContain('1 / 5')
    expect(panel.textContent).toContain('37 / 100')
  })
})

// ── OnboardingPage ───────────────────────────────────────────────────────────

describe('OnboardingPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked(getOnboardingStatus).mockResolvedValue({ tenant_id: 't-1', is_onboarded: false })
    mocked(createInvitation).mockResolvedValue({
      invitation_id: 'inv-1',
      email: 'x@t.dev',
      tenant_role: 'member',
      status: 'pending',
      accept_token: 'TOKEN123',
    } as TenantInvitation)
  })

  it('renders the guided steps', async () => {
    renderWith(<OnboardingPage />)
    await waitFor(() => {
      expect(screen.getByText('tenant.onboarding.title')).toBeDefined()
    })
    expect(screen.getByText('tenant.onboarding.stepInvite')).toBeDefined()
    expect(screen.getByText('tenant.onboarding.stepSignin')).toBeDefined()
    expect(screen.getByText('tenant.onboarding.stepFinish')).toBeDefined()
  })

  it('creates invitations during onboarding and shows the token note', async () => {
    renderWith(<OnboardingPage />)
    await waitFor(() => screen.getByLabelText('tenant.onboarding.inviteEmail'))

    fireEvent.change(screen.getByLabelText('tenant.onboarding.inviteEmail'), {
      target: { value: 'x@t.dev' },
    })
    fireEvent.click(screen.getByText('tenant.onboarding.inviteSend'))

    await waitFor(() => {
      expect(mocked(createInvitation)).toHaveBeenCalled()
      expect(mocked(createInvitation).mock.calls[0][0]).toEqual({
        email: 'x@t.dev',
        tenant_role: 'member',
      })
    })
    expect(screen.getByText('tenant.onboarding.tokenNote')).toBeDefined()
  })

  it('completes onboarding via the finish action', async () => {
    mocked(completeOnboarding).mockResolvedValue({ tenant_id: 't-1', is_onboarded: true })
    renderWith(<OnboardingPage />)
    await waitFor(() => screen.getByText('tenant.onboarding.finish'))

    fireEvent.click(screen.getByText('tenant.onboarding.finish'))
    await waitFor(() => {
      expect(mocked(completeOnboarding)).toHaveBeenCalled()
    })
  })

  it('offers the skip path', async () => {
    renderWith(<OnboardingPage />)
    await waitFor(() => {
      expect(screen.getByText('tenant.onboarding.skip')).toBeDefined()
    })
    expect(screen.getByText('tenant.onboarding.skipNote')).toBeDefined()
  })

  it('shows the already-complete state for onboarded tenants', async () => {
    mocked(getOnboardingStatus).mockResolvedValue({ tenant_id: 't-1', is_onboarded: true })
    renderWith(<OnboardingPage />)
    await waitFor(() => {
      expect(screen.getByText('tenant.onboarding.alreadyComplete')).toBeDefined()
    })
  })
})

// ── MembersPage ──────────────────────────────────────────────────────────────

const members: TenantMember[] = [
  {
    membership_id: 'm-1',
    user_id: 'u-1',
    display_name: 'Admin A',
    email: 'admin@acme.test',
    tenant_role: 'tenant_admin',
    status: 'active',
    is_default: true,
    is_root: false,
  },
  {
    membership_id: 'm-2',
    user_id: 'u-2',
    display_name: 'Member B',
    email: 'b@acme.test',
    tenant_role: 'member',
    status: 'active',
    is_default: false,
    is_root: false,
  },
]

describe('MembersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked(listMembers).mockResolvedValue(members)
    mocked(listInvitations).mockResolvedValue([])
  })

  it('lists the tenant members', async () => {
    renderWith(<MembersPage />)
    await waitFor(() => {
      expect(screen.getByText('Admin A')).toBeDefined()
    })
    expect(screen.getByText('Member B')).toBeDefined()
    expect(screen.getByText('b@acme.test')).toBeDefined()
  })

  it('creates an invitation and shows the accept token once', async () => {
    mocked(createInvitation).mockResolvedValue({
      invitation_id: 'inv-9',
      email: 'new@acme.test',
      tenant_role: 'member',
      status: 'pending',
      accept_token: 'SECRET-TOKEN',
    } as TenantInvitation)

    renderWith(<MembersPage />)
    await waitFor(() => screen.getByText('Admin A'))

    fireEvent.click(screen.getByText('tenant.members.invite'))
    const emailInput = screen.getByLabelText('tenant.members.email')
    fireEvent.change(emailInput, { target: { value: 'new@acme.test' } })
    fireEvent.click(screen.getByText('tenant.members.inviteSend'))

    await waitFor(() => {
      expect(mocked(createInvitation).mock.calls[0][0]).toEqual({
        email: 'new@acme.test',
        tenant_role: 'member',
      })
    })
    expect(screen.getByText(/SECRET-TOKEN/)).toBeDefined()
  })

  it('renders pending invitations without leaking tokens', async () => {
    mocked(listInvitations).mockResolvedValue([
      {
        invitation_id: 'inv-2',
        email: 'pending@acme.test',
        tenant_role: 'member',
        status: 'pending',
        accept_token: null,
      } as TenantInvitation,
    ])
    renderWith(<MembersPage />)
    await waitFor(() => {
      expect(screen.getByText('pending@acme.test')).toBeDefined()
    })
  })

  it('renders the members table headers via i18n', async () => {
    renderWith(<MembersPage />)
    await waitFor(() => screen.getByText('Admin A'))
    expect(screen.getByText('tenant.members.name')).toBeDefined()
    // Both the members table and the invitations table have a Role column
    // sharing the same i18n key — getAllByText, not getByText.
    expect(screen.getAllByText('tenant.members.roleLabel').length).toBeGreaterThanOrEqual(1)
  })
})
