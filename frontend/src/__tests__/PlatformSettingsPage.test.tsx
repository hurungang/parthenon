/**
 * PlatformSettingsPage — tenancy switch (Phase 6.4, CS-03).
 *
 * - Switch reflects server state (off by default)
 * - Enabling requires the typed confirmation phrase ("ENABLE")
 * - Confirming calls the API with true and reflects the adoption result
 * - Disabling (no confirmation) calls the API with false
 * - Errors surface per the Dialog Error Handling Standard
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

import {
  getPlatformSettings,
  updatePlatformSetting,
} from '../api/platformAdminApi'

vi.mock('../api/platformAdminApi', () => ({
  getPlatformSettings: vi.fn(),
  updatePlatformSetting: vi.fn(),
}))

import { PlatformSettingsPage } from '../pages/platform/PlatformSettingsPage'

const mocked = vi.mocked

/** MUI Switch: the test id sits on the wrapper span; the real input is inside. */
function switchInput(): HTMLInputElement {
  return screen.getByTestId('tenancy-switch').querySelector('input') as HTMLInputElement
}

/** MUI TextField: same wrapper-vs-input nuance for test ids. */
function inputWithin(testId: string): HTMLInputElement {
  return screen.getByTestId(testId).querySelector('input') as HTMLInputElement
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <PlatformSettingsPage />
    </QueryClientProvider>,
  )
}

describe('PlatformSettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked(getPlatformSettings).mockResolvedValue({
      items: [],
      multi_tenancy_enabled: false,
    })
  })

  it('renders the switch reflecting server state (off)', async () => {
    renderPage()
    await waitFor(() => {
      expect(switchInput().checked).toBe(false)
    })
    expect(screen.getByText('platform.settings.tenancyOff')).toBeDefined()
  })

  it('shows the tenancy-on note when enabled', async () => {
    mocked(getPlatformSettings).mockResolvedValue({
      items: [],
      multi_tenancy_enabled: true,
    })
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('platform.settings.tenancyOnNote')).toBeDefined()
    })
    expect(switchInput().checked).toBe(true)
  })

  it('enabling opens a confirmation dialog before the API call', async () => {
    renderPage()
    await waitFor(() => switchInput())

    fireEvent.click(switchInput())
    // Confirmation dialog appears; no API call yet.
    expect(screen.getByText('platform.settings.confirmTitle')).toBeDefined()
    expect(mocked(updatePlatformSetting)).not.toHaveBeenCalled()

    // Typed confirmation is required.
    const input = inputWithin('tenancy-confirm-input')
    fireEvent.change(input, { target: { value: 'enable' } }) // wrong case
    const confirmButton = screen.getByText('platform.settings.confirmEnable') as HTMLButtonElement
    expect(confirmButton.disabled).toBe(true)

    fireEvent.change(input, { target: { value: 'ENABLE' } })
    expect(confirmButton.disabled).toBe(false)
    fireEvent.click(confirmButton)

    await waitFor(() => {
      expect(mocked(updatePlatformSetting)).toHaveBeenCalled()
      expect(mocked(updatePlatformSetting).mock.calls[0].slice(0, 2)).toEqual([
        'multi_tenancy_enabled',
        true,
      ])
    })
  })

  it('reflects the adoption result after enabling', async () => {
    mocked(updatePlatformSetting).mockResolvedValue({
      key: 'multi_tenancy_enabled',
      value: { enabled: true },
      multi_tenancy_enabled: true,
      adoption: { action: 'enabled', slug: 'system', created: true, backfilled_tables: 42, memberships_granted: 3 },
    })
    renderPage()
    await waitFor(() => screen.getByTestId('tenancy-switch'))
    fireEvent.click(screen.getByTestId('tenancy-switch'))
    const input = inputWithin('tenancy-confirm-input')
    fireEvent.change(input, { target: { value: 'ENABLE' } })
    fireEvent.click(screen.getByText('platform.settings.confirmEnable'))

    await waitFor(() => {
      // The adoption success alert renders (interpolation is t()-side).
      expect(screen.getByText('platform.settings.adoptionDone')).toBeDefined()
    })
  })

  it('disabling sends false without a confirmation dialog', async () => {
    mocked(getPlatformSettings).mockResolvedValue({
      items: [],
      multi_tenancy_enabled: true,
    })
    mocked(updatePlatformSetting).mockResolvedValue({
      key: 'multi_tenancy_enabled',
      value: { enabled: false },
      multi_tenancy_enabled: false,
      adoption: { action: 'disabled', data_loss: false },
    })
    renderPage()
    await waitFor(() => {
      expect(switchInput().checked).toBe(true)
    })

    fireEvent.click(switchInput())
    await waitFor(() => {
      expect(mocked(updatePlatformSetting).mock.calls[0].slice(0, 2)).toEqual([
        'multi_tenancy_enabled',
        false,
      ])
    })
    expect(screen.queryByText('platform.settings.confirmTitle')).toBeNull()
  })

  it('shows the disable-done message after switching off', async () => {
    mocked(getPlatformSettings).mockResolvedValue({
      items: [],
      multi_tenancy_enabled: true,
    })
    mocked(updatePlatformSetting).mockResolvedValue({
      key: 'multi_tenancy_enabled',
      value: { enabled: false },
      multi_tenancy_enabled: false,
      adoption: { action: 'disabled', data_loss: false },
    })
    renderPage()
    await waitFor(() => switchInput())
    fireEvent.click(switchInput())
    await waitFor(() => {
      expect(screen.getByText('platform.settings.disableDone')).toBeDefined()
    })
  })

  it('surfaces toggle errors per the dialog error standard', async () => {
    mocked(getPlatformSettings).mockResolvedValue({
      items: [],
      multi_tenancy_enabled: true,
    })
    const forbidden = Object.assign(new Error('denied'), {
      isAxiosError: true,
      response: { status: 403, data: { detail: 'Permission denied' } },
    })
    mocked(updatePlatformSetting).mockRejectedValue(forbidden)
    renderPage()
    await waitFor(() => screen.getByTestId('tenancy-switch'))
    fireEvent.click(screen.getByTestId('tenancy-switch'))
    await waitFor(() => {
      expect(screen.getByText(/Permission denied/)).toBeDefined()
    })
  })
})
