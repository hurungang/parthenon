import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})
vi.mock('../../../api/setupApi', () => ({
  postSetupIdentity: vi.fn(),
}))

import { SetupWizard } from '../../../features/setup/SetupWizard'
import { postSetupIdentity } from '../../../api/setupApi'
const mockedPost = vi.mocked(postSetupIdentity)

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('SetupWizard', () => {
  afterEach(() => vi.clearAllMocks())

  it('renders provider selection step initially', () => {
    render(<SetupWizard />, { wrapper })
    expect(screen.getByText('setup.title')).toBeDefined()
    expect(screen.getByText('setup.provider.bundledKeycloak')).toBeDefined()
  })

  it('advances to keycloak config step on Next', () => {
    render(<SetupWizard />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: 'setup.action.next' }))
    expect(screen.getByPlaceholderText('http://localhost:8080')).toBeDefined()
  })

  it('shows external OIDC form when Azure EntraID selected', () => {
    render(<SetupWizard />, { wrapper })
    const radios = screen.getAllByRole('radio')
    fireEvent.click(radios[2]) // Azure EntraID (3rd option)
    fireEvent.click(screen.getByRole('button', { name: 'setup.action.next' }))
    expect(
      screen.getByPlaceholderText(
        'https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration',
      ),
    ).toBeDefined()
  })

  it('submit button disabled until required fields are filled', () => {
    render(<SetupWizard />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: 'setup.action.next' }))
    const submitBtn = screen.getByRole('button', { name: 'setup.action.submit' })
    expect((submitBtn as HTMLButtonElement).disabled).toBe(true)
  })

  it('submit triggers API call and navigates to completion on success', async () => {
    mockedPost.mockResolvedValueOnce({
      success: true,
      provider_type: 'keycloak_bundled',
      oidc_provider_url: 'http://localhost:8080/realms/parthenon',
      realm_name: 'parthenon',
      client_id: 'parthenon',
      error_code: null,
      detail: null,
    })
    render(<SetupWizard />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: 'setup.action.next' }))
    fireEvent.change(screen.getByPlaceholderText('http://localhost:8080'), {
      target: { value: 'http://kc' },
    })
    fireEvent.change(screen.getByPlaceholderText('parthenon'), {
      target: { value: 'myrealm' },
    })
    fireEvent.change(screen.getByPlaceholderText('parthenon-api'), {
      target: { value: 'my-client' },
    })
    fireEvent.change(screen.getByPlaceholderText('admin'), {
      target: { value: 'admin' },
    })
    // Password fields: get by input type
    const passwordInputs = document.querySelectorAll('input[type="password"]')
    await act(async () => {
      fireEvent.change(passwordInputs[0], { target: { value: 'pass1' } })
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'setup.action.submit' }))
    })
    expect(mockedPost).toHaveBeenCalled()
    await waitFor(() => {
      expect(screen.getByText('setup.status.success')).toBeDefined()
    })
  })

  it('shows keycloak unreachable error on 502', async () => {
    const error = Object.assign(new Error('502'), {
      isAxiosError: true,
      response: { status: 502, data: {} },
    })
    mockedPost.mockRejectedValueOnce(error)
    render(<SetupWizard />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: 'setup.action.next' }))
    fireEvent.change(screen.getByPlaceholderText('http://localhost:8080'), {
      target: { value: 'http://kc' },
    })
    fireEvent.change(screen.getByPlaceholderText('parthenon'), {
      target: { value: 'myrealm' },
    })
    fireEvent.change(screen.getByPlaceholderText('parthenon-api'), {
      target: { value: 'my-client' },
    })
    fireEvent.change(screen.getByPlaceholderText('admin'), {
      target: { value: 'admin' },
    })
    const passwordInputs = document.querySelectorAll('input[type="password"]')
    await act(async () => {
      fireEvent.change(passwordInputs[0], { target: { value: 'pass1' } })
    })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'setup.action.submit' }))
    })
    await waitFor(() => {
      expect(screen.getByText('setup.error.keycloakUnreachable')).toBeDefined()
    })
  })
})
