/**
 * PlatformAuditPage — cross-tenant attempt audit view (Phase 6.5, 2.9/2.11).
 *
 * - Lists audit events with tenant attribution (slug) and security chips
 * - Filters (tenant / event type / security-only / dates) re-query the API
 * - Renders metadata only — never tenant business data
 * - Empty state renders
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

import {
  listAuditEvents,
  listTenants,
  type TenantAuditEvent,
} from '../api/platformAdminApi'

vi.mock('../api/platformAdminApi', () => ({
  listAuditEvents: vi.fn(),
  listTenants: vi.fn(),
}))

import { PlatformAuditPage } from '../pages/platform/PlatformAuditPage'

const mocked = vi.mocked

const events: TenantAuditEvent[] = [
  {
    id: 'e-1',
    tenant_id: 't-1',
    tenant_slug: 'acme',
    event_type: 'cross_tenant_access_denied',
    actor_type: 'tenant_user',
    actor_id: null,
    actor_ip: '10.0.0.1',
    target_resource: 'GET /api/v1/roles',
    detail: { reason: 'mismatch' },
    is_security_relevant: true,
    created_at: '2026-02-01T10:00:00Z',
  },
  {
    id: 'e-2',
    tenant_id: null,
    tenant_slug: null,
    event_type: 'tenant_created',
    actor_type: 'platform_admin',
    actor_id: 'u-1',
    actor_ip: null,
    target_resource: 'tenant:system',
    detail: {},
    is_security_relevant: false,
    created_at: '2026-02-02T10:00:00Z',
  },
]

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <PlatformAuditPage />
    </QueryClientProvider>,
  )
}

describe('PlatformAuditPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked(listAuditEvents).mockResolvedValue({ items: events, total: 2 })
    mocked(listTenants).mockResolvedValue({
      items: [
        {
          id: 't-1', name: 'Acme Corp', slug: 'acme', status: 'active',
          admin_contact_name: 'Ada', admin_contact_email: 'ada@acme.test',
          created_at: '2026-01-01T00:00:00Z', updated_at: null,
          license: null, usage: null,
          is_system_tenant: false, is_onboarded: true,
        },
      ],
      total: 1,
    })
  })

  it('lists events with tenant attribution and event labels', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('acme')).toBeDefined()
    })
    // Platform-level events show the platform sentinel attribution.
    expect(screen.getByText('platform.audit.platform')).toBeDefined()
    expect(screen.getByText('platform.audit.event.cross_tenant_access_denied')).toBeDefined()
    expect(screen.getByText('GET /api/v1/roles')).toBeDefined()
  })

  it('renders the filter bar', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('audit-filters')).toBeDefined()
    })
    // Labels appear as filter labels AND as table headers.
    expect(screen.getAllByText('platform.audit.tenant').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('platform.audit.eventType').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('platform.audit.severity').length).toBeGreaterThanOrEqual(1)
  })

  it('re-queries when a date filter is applied', async () => {
    renderPage()
    await waitFor(() => expect(mocked(listAuditEvents).mock.calls.length).toBe(1))

    const fromInput = screen.getByLabelText('platform.audit.from')
    fireEvent.change(fromInput, { target: { value: '2026-01-01' } })

    await waitFor(() => {
      expect(mocked(listAuditEvents).mock.calls.length).toBe(2)
      const params = mocked(listAuditEvents).mock.calls[1][0] ?? {}
      expect((params as Record<string, unknown>).date_from).toBe('2026-01-01')
    })
  })

  it('renders the empty state', async () => {
    mocked(listAuditEvents).mockResolvedValue({ items: [], total: 0 })
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('platform.audit.empty')).toBeDefined()
    })
  })

  it('renders only audit metadata (no business data columns)', async () => {
    renderPage()
    await waitFor(() => screen.getByText('acme'))
    // The audit contract: time / event / tenant / target / actor ONLY.
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual([
      'platform.audit.time',
      'platform.audit.eventType',
      'platform.audit.tenant',
      'platform.audit.target',
      'platform.audit.actor',
    ])
  })
})
