import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

// Mock apiClient so no real HTTP calls
vi.mock('../api/apiClient', () => ({
  default: {
    post: vi.fn().mockResolvedValue({ data: {} }),
    get: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('SetupWizard', () => {
  it('renders the setup title', async () => {
    const { SetupWizard } = await import('../pages/setup/SetupWizard')
    render(<SetupWizard />, { wrapper })
    expect(screen.getByText('setup.title')).toBeDefined()
  })

  it('renders step 1 content initially', async () => {
    const { SetupWizard } = await import('../pages/setup/SetupWizard')
    render(<SetupWizard />, { wrapper })
    // Provider radio options are unique to step 1 content
    expect(screen.getAllByText('setup.provider.bundledKeycloak')[0]).toBeDefined()
  })

  it('shows step 1 stepper label', async () => {
    const { SetupWizard } = await import('../pages/setup/SetupWizard')
    render(<SetupWizard />, { wrapper })
    // The step label appears in both stepper and step header — verify at least one exists
    expect(screen.getAllByText('setup.step.providerSelection.label').length).toBeGreaterThan(0)
  })

  it('advances to step 2 when Next is clicked', async () => {
    const { SetupWizard } = await import('../pages/setup/SetupWizard')
    render(<SetupWizard />, { wrapper })
    const nextBtn = screen.getByRole('button', { name: 'setup.action.next' })
    fireEvent.click(nextBtn)
    // Keycloak URL field label is unique to KeycloakConfigStep
    expect(screen.getByText('setup.field.keycloakUrl')).toBeDefined()
  })

  it('Back button is disabled on step 1', async () => {
    const { SetupWizard } = await import('../pages/setup/SetupWizard')
    render(<SetupWizard />, { wrapper })
    const backBtn = screen.getByRole('button', { name: 'setup.action.back' })
    expect(backBtn).toHaveProperty('disabled', true)
  })
})
