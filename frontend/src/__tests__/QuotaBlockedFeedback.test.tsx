/**
 * QuotaBlockedFeedback — structured quota refusal UI (Phase 10.18,
 * CS-35/CS-36/CS-37/CS-41 frontend contract).
 *
 * - extractQuotaBlocked recognizes ONLY the backend quota contract shape
 *   (HTTP 403, detail.code === 'quota_exhausted') and returns null for
 *   anything else (permission errors, validation, network)
 * - QuotaBlockedAlert renders tier / quota type / usage meter / upgrade
 *   path from the structured payload as-is
 * - Non-quota errors fall through to the standard PermissionDeniedAlert
 * - Wired surface: the MembersPage invite dialog surfaces the structured
 *   block when invitation creation is refused over the user quota
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({
  // Interpolation-aware: values are appended so meter numbers are
  // assertable.
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) =>
      opts ? `${k} ${Object.values(opts).join(' / ')}` : k,
  }),
}))

import {
  createInvitation,
  listMembers,
  listInvitations,
  type TenantMember,
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

import { extractQuotaBlocked } from '../utils/quotaErrorUtils'
import QuotaBlockedAlert from '../components/tenant/QuotaBlockedAlert'
import { MembersPage } from '../pages/tenant/MembersPage'

const mocked = vi.mocked

const quotaError = Object.assign(new Error('quota'), {
  isAxiosError: true,
  response: {
    status: 403,
    data: {
      detail: {
        code: 'quota_exhausted',
        quota_type: 'users',
        tier: 'free',
        limit: 10,
        used: 10,
        upgrade_path:
          'Upgrade your plan (contact your platform administrator) to raise this limit',
      },
    },
  },
})

// ── extractQuotaBlocked (contract recognition) ──────────────────────────────

describe('extractQuotaBlocked', () => {
  it('recognizes the structured quota contract', () => {
    const payload = extractQuotaBlocked(quotaError)
    expect(payload).not.toBeNull()
    expect(payload!.code).toBe('quota_exhausted')
    expect(payload!.quota_type).toBe('users')
    expect(payload!.tier).toBe('free')
    expect(payload!.limit).toBe(10)
    expect(payload!.used).toBe(10)
  })

  it('returns null for non-quota errors', () => {
    const permissionError = Object.assign(new Error('denied'), {
      isAxiosError: true,
      response: { status: 403, data: { detail: 'Permission denied' } },
    })
    expect(extractQuotaBlocked(permissionError)).toBeNull()
    expect(extractQuotaBlocked(new Error('network down'))).toBeNull()
    expect(extractQuotaBlocked(null)).toBeNull()
  })

  it('returns null for malformed payloads', () => {
    const malformed = Object.assign(new Error('bad'), {
      isAxiosError: true,
      response: {
        status: 403,
        data: { detail: { code: 'quota_exhausted', quota_type: 42 } },
      },
    })
    expect(extractQuotaBlocked(malformed)).toBeNull()
  })
})

// ── QuotaBlockedAlert (structured feedback rendering) ───────────────────────

describe('QuotaBlockedAlert', () => {
  it('renders tier, quota type, usage meter and upgrade path as-is', () => {
    render(<QuotaBlockedAlert error={quotaError} fallbackMessage="app.error" />)
    const alert = screen.getByTestId('quota-blocked-alert')
    expect(alert.textContent).toContain('tenant.quota.blockedTitle')
    // quotaType label + used/limit + tier name.
    expect(alert.textContent).toContain('tenant.quota.quotaType.users')
    expect(alert.textContent).toContain('free')
    expect(alert.textContent).toContain('10 / 10')
    // The upgrade path line.
    expect(alert.textContent).toContain('tenant.quota.upgradePath')
  })

  it('falls through to the permission alert for non-quota errors', () => {
    const permissionError = Object.assign(new Error('denied'), {
      isAxiosError: true,
      response: {
        status: 403,
        data: {
          detail: {
            required_permission: {
              resource_type: 'tenant::members',
              action: 'create',
            },
          },
        },
      },
    })
    render(
      <MemoryRouter>
        <QuotaBlockedAlert error={permissionError} fallbackMessage="fallback!" />
      </MemoryRouter>,
    )
    expect(screen.queryByTestId('quota-blocked-alert')).toBeNull()
    // Standard dialog-error handling applies instead.
    expect(screen.getByText(/Permission Denied/)).toBeDefined()
  })

  it('uses the fallback message for plain errors', () => {
    render(
      <MemoryRouter>
        <QuotaBlockedAlert error={new Error('boom')} fallbackMessage="fallback!" />
      </MemoryRouter>,
    )
    expect(screen.queryByTestId('quota-blocked-alert')).toBeNull()
    // The standard alert rendered (an error alert, not the quota one).
    expect(screen.getByRole('alert')).toBeDefined()
  })
})

// ── MembersPage wiring (blocked invite surfaces the contract) ───────────────

const members: TenantMember[] = [
  {
    membership_id: 'm-1',
    user_id: 'u-1',
    display_name: 'Admin A',
    email: 'admin@acme.test',
    tenant_role: 'tenant_admin',
    status: 'active',
    is_default: true,
    is_root: true,
  },
]

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MembersPage />
    </QueryClientProvider>,
  )
}

describe('MembersPage quota-blocked feedback (wired surface)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked(listMembers).mockResolvedValue(members)
    mocked(listInvitations).mockResolvedValue([])
  })

  it('renders the structured quota block when an invite is refused', async () => {
    mocked(createInvitation).mockRejectedValue(quotaError)
    renderPage()
    await waitFor(() => screen.getByText('Admin A'))

    fireEvent.click(screen.getByText('tenant.members.invite'))
    fireEvent.change(screen.getByLabelText('tenant.members.email'), {
      target: { value: 'new@acme.test' },
    })
    fireEvent.click(screen.getByText('tenant.members.inviteSend'))

    // The blocked-action alert renders the full contract as-is.
    const alert = await screen.findByTestId('quota-blocked-alert')
    expect(alert.textContent).toContain('tenant.quota.quotaType.users')
    expect(alert.textContent).toContain('10 / 10')
    expect(alert.textContent).toContain('tenant.quota.upgradePath')
    expect(mocked(createInvitation)).toHaveBeenCalled()
  })

  it('does NOT render the quota block when the invitation succeeds', async () => {
    mocked(createInvitation).mockResolvedValue({
      invitation_id: 'inv-1',
      email: 'new@acme.test',
      tenant_role: 'member',
      status: 'pending',
      accept_token: 'TOKEN',
    } as never)
    renderPage()
    await waitFor(() => screen.getByText('Admin A'))

    fireEvent.click(screen.getByText('tenant.members.invite'))
    fireEvent.change(screen.getByLabelText('tenant.members.email'), {
      target: { value: 'new@acme.test' },
    })
    fireEvent.click(screen.getByText('tenant.members.inviteSend'))

    await waitFor(() => {
      expect(screen.getByText(/TOKEN/)).toBeDefined()
    })
    expect(screen.queryByTestId('quota-blocked-alert')).toBeNull()
  })
})
