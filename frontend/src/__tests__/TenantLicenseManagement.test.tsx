/**
 * TenantLicenseManagement — platform console license assignment
 * (Phase 10.18, CS-33/CS-34/CS-43 UI side).
 *
 * - Tier + usage columns render from the extended tenant list response
 *   (free defaults when unlicensed; aggregate counts only)
 * - License dialog: tier select pre-fills editable per-tier preset
 *   limits; assign vs change button states; invalid input (non-positive
 *   limits) disables saving
 * - Assign/change/remove refresh the parent table WITHOUT a page reload
 *   (TanStack Query invalidation), with an explicit free-fallback
 *   confirmation step before removal
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({
  // Interpolation-aware: values are appended so numeric usage summaries
  // are assertable.
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) =>
      opts ? `${k} ${Object.values(opts).join(' / ')}` : k,
  }),
}))

import {
  listTenants,
  assignTenantLicense,
  removeTenantLicense,
  type Tenant,
} from '../api/platformAdminApi'

vi.mock('../api/platformAdminApi', () => ({
  listTenants: vi.fn(),
  assignTenantLicense: vi.fn(),
  removeTenantLicense: vi.fn(),
  createTenant: vi.fn(),
  updateTenant: vi.fn(),
  suspendTenant: vi.fn(),
  resumeTenant: vi.fn(),
  deleteTenant: vi.fn(),
}))

import { TenantManagementPage } from '../pages/platform/TenantManagementPage'

const mocked = vi.mocked

const usageFree = {
  tier: 'free' as const,
  max_users: 10,
  max_agent_types: 5,
  monthly_agent_executions: 100,
  users: 1,
  agent_types: 0,
  executions_this_month: 3,
}

const usageTeam = {
  tier: 'team' as const,
  max_users: 25,
  max_agent_types: 15,
  monthly_agent_executions: 1000,
  users: 7,
  agent_types: 4,
  executions_this_month: 250,
}

const unlicensed: Tenant = {
  id: '11111111-1111-1111-1111-111111111111',
  name: 'Acme Corp',
  slug: 'acme',
  status: 'active',
  is_system_tenant: false,
  is_onboarded: true,
  admin_contact_name: 'Ada',
  admin_contact_email: 'ada@acme.test',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  license: null,
  usage: usageFree,
}

const licensed: Tenant = {
  ...unlicensed,
  id: '22222222-2222-2222-2222-222222222222',
  name: 'Globex',
  slug: 'globex',
  license: {
    tier: 'team',
    max_users: 25,
    max_agent_types: 15,
    monthly_agent_executions: 1000,
    assigned_at: '2026-02-01T00:00:00Z',
  },
  usage: usageTeam,
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TenantManagementPage />
    </QueryClientProvider>,
  )
}

describe('TenantLicenseManagement (platform console)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked(listTenants).mockResolvedValue({
      items: [unlicensed, licensed],
      total: 2,
    })
    mocked(assignTenantLicense).mockResolvedValue({
      tier: 'team',
      max_users: 25,
      max_agent_types: 15,
      monthly_agent_executions: 1000,
      assigned_at: '2026-02-01T00:00:00Z',
    })
    mocked(removeTenantLicense).mockResolvedValue(undefined)
  })

  it('renders tier and usage columns with free defaults when unlicensed', async () => {
    renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-acme'))

    // Tier chips.
    expect(screen.getByTestId('tenant-tier-acme').textContent).toBe(
      'platform.tenants.tierValue.free',
    )
    expect(screen.getByTestId('tenant-tier-globex').textContent).toBe(
      'platform.tenants.tierValue.team',
    )
    // Usage summaries show used vs limit aggregates only.
    expect(screen.getByTestId('tenant-usage-acme').textContent).toContain('1')
    expect(screen.getByTestId('tenant-usage-acme').textContent).toContain('10')
    expect(screen.getByTestId('tenant-usage-globex').textContent).toContain(
      '250',
    )
  })

  it('assigns a license via the dialog and refreshes the table without reload', async () => {
    const renderResult = renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-acme'))
    const urlBefore = renderResult.baseElement.ownerDocument.location.href

    // Open the license dialog for the unlicensed tenant.
    fireEvent.click(screen.getByTestId('license-button-acme'))
    expect(screen.getByTestId('license-dialog')).toBeDefined()

    // Defaults pre-filled with the FREE tier presets.
    expect(
      (screen.getByTestId('license-max-users').querySelector('input') as HTMLInputElement)
        .value,
    ).toBe('10')

    // Pick the team tier — presets pre-fill (editable) limits.
    fireEvent.change(
      screen.getByTestId('license-tier-select').querySelector('input') as HTMLInputElement,
      { target: { value: 'team' } },
    )
    await waitFor(() => {
      expect(
        (screen.getByTestId('license-max-users').querySelector('input') as HTMLInputElement)
          .value,
      ).toBe('25')
      expect(
        (screen.getByTestId('license-monthly-executions').querySelector('input') as HTMLInputElement)
          .value,
      ).toBe('1000')
    })

    fireEvent.click(screen.getByTestId('license-save-button'))

    await waitFor(() => {
      expect(mocked(assignTenantLicense)).toHaveBeenCalledWith('11111111-1111-1111-1111-111111111111', {
        tier: 'team',
        max_users: 25,
        max_agent_types: 15,
        monthly_agent_executions: 1000,
      })
    })
    // Parent table refreshed automatically (invalidateQueries → refetch).
    await waitFor(() => {
      expect(mocked(listTenants).mock.calls.length).toBeGreaterThanOrEqual(2)
    })
    await waitFor(() => {
      expect(screen.queryByTestId('license-dialog')).toBeNull()
    })
    expect(urlBefore).toBe(
      renderResult.baseElement.ownerDocument.location.href,
    )
  })

  it('shows the CHANGE state for a tenant that already has a license', async () => {
    renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-globex'))

    fireEvent.click(screen.getByTestId('license-button-globex'))
    // Pre-filled from the ACTIVE license, not the free preset.
    expect(
      (screen.getByTestId('license-max-users').querySelector('input') as HTMLInputElement)
        .value,
    ).toBe('25')
    // Assign button shows the change label when a license exists.
    expect(screen.getByTestId('license-save-button').textContent).toBe(
      'platform.tenants.licenseChange',
    )
    // Remove is offered with an explicit free-fallback confirmation step.
    expect(screen.getByTestId('license-remove-button')).toBeDefined()
  })

  it('removes a license only after the explicit free-fallback confirmation', async () => {
    renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-globex'))

    fireEvent.click(screen.getByTestId('license-button-globex'))
    fireEvent.click(screen.getByTestId('license-remove-button'))

    // Confirmation step: warning + confirm button, no direct removal yet.
    expect(
      screen.getByText('platform.tenants.licenseRemoveWarning', { exact: false }),
    ).toBeDefined()
    expect(mocked(removeTenantLicense)).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('license-remove-confirm'))
    await waitFor(() => {
      expect(mocked(removeTenantLicense)).toHaveBeenCalledWith(
        '22222222-2222-2222-2222-222222222222',
      )
    })
    // Table refreshed without reload; dialog closed.
    await waitFor(() => {
      expect(mocked(listTenants).mock.calls.length).toBeGreaterThanOrEqual(2)
      expect(screen.queryByTestId('license-dialog')).toBeNull()
    })
  })

  it('disables saving when any limit is non-positive (invalid input)', async () => {
    renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-acme'))

    fireEvent.click(screen.getByTestId('license-button-acme'))
    const usersInput = screen
      .getByTestId('license-max-users')
      .querySelector('input') as HTMLInputElement

    fireEvent.change(usersInput, { target: { value: '0' } })
    expect(screen.getByTestId('license-save-button')).toHaveProperty(
      'disabled',
      true,
    )

    fireEvent.change(usersInput, { target: { value: '-5' } })
    expect(screen.getByTestId('license-save-button')).toHaveProperty(
      'disabled',
      true,
    )

    fireEvent.change(usersInput, { target: { value: '12' } })
    expect(screen.getByTestId('license-save-button')).toHaveProperty(
      'disabled',
      false,
    )
  })

  it('surfaces license API errors inside the dialog (dialog error standard)', async () => {
    mocked(assignTenantLicense).mockRejectedValue(
      Object.assign(new Error('denied'), {
        isAxiosError: true,
        response: { status: 403, data: { detail: 'Permission denied' } },
      }),
    )
    renderPage()
    await waitFor(() => screen.getByTestId('tenant-row-acme'))

    fireEvent.click(screen.getByTestId('license-button-acme'))
    fireEvent.click(screen.getByTestId('license-save-button'))

    await waitFor(() => {
      expect(screen.getByText(/Permission denied/)).toBeDefined()
    })
    // The dialog stays open so the operator can correct or cancel.
    expect(screen.getByTestId('license-dialog')).toBeDefined()
  })
})
