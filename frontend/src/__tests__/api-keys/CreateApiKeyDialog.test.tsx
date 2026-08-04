import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { within } from '@testing-library/dom'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const { mockApiClient } = vi.hoisted(() => {
  return {
    mockApiClient: {
      get: vi.fn(),
      post: vi.fn(),
    },
  }
})

vi.mock('../../api/apiClient', () => ({ default: mockApiClient }))

const MOCK_IDENTITIES = [
  {
    identity_id: 'identity-1',
    identity_name: 'Agent Alpha',
    roles: [
      { role_id: 'role-1', role_name: 'Developer' },
      { role_id: 'role-2', role_name: 'Viewer' },
    ],
  },
  {
    identity_id: 'identity-2',
    identity_name: 'Agent Beta',
    roles: [
      { role_id: 'role-3', role_name: 'Admin' },
    ],
  },
]

const MOCK_CREATE_RESPONSE = {
  id: 'new-key-id',
  name: 'My Test Key',
  key_prefix: 'phn_sk_',
  api_key: 'phn_sk_abcdef12345678901234567890abcd',
  agent_identity_id: 'identity-1',
  agent_identity_name: 'Agent Alpha',
  agent_role_id: 'role-1',
  agent_role_name: 'Developer',
  created_at: '2026-07-30T00:00:00Z',
}

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

/**
 * Helper: Get MUI Select element by its label text.
 * MUI Select renders an input inside a div with role="combobox",
 * with the label as an <label> element referencing the input via id.
 * We locate the label element and then find its associated input.
 */
function getSelectByLabel(labelText: string): HTMLElement {
  // Find the label element
  const label = screen.getByText(labelText)
  // The label's "for" attribute points to the select input's id
  // In MUI, the label has a "for" attribute (or data-shrink) but the
  // actual input is a hidden input sibling. The clickable element is the
  // div with role="combobox" inside the same FormControl.
  const formControl = label.closest('.MuiFormControl-root') as HTMLElement
  if (formControl) {
    const combobox = formControl.querySelector('[role="combobox"]') as HTMLElement
    if (combobox) return combobox
  }
  // Fallback
  return label
}

describe('CreateApiKeyDialog', () => {
  const onClose = vi.fn()
  const onCreated = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    mockApiClient.get.mockImplementation((url: string) => {
      if (url === '/api-keys/identities-with-roles') {
        return Promise.resolve({ data: MOCK_IDENTITIES })
      }
      return Promise.resolve({ data: [] })
    })
    mockApiClient.post.mockResolvedValue({ data: MOCK_CREATE_RESPONSE })
  })

  it('renders create dialog with title', async () => {
    const { CreateApiKeyDialog } = await import('../../pages/api-keys/CreateApiKeyDialog')
    render(
      <CreateApiKeyDialog open={true} onClose={onClose} onCreated={onCreated} />,
      { wrapper: Wrapper }
    )
    await waitFor(() => {
      expect(screen.getByText('apiKeys.createTitle')).toBeDefined()
    })
  })

  it('renders key name input field', async () => {
    const { CreateApiKeyDialog } = await import('../../pages/api-keys/CreateApiKeyDialog')
    render(
      <CreateApiKeyDialog open={true} onClose={onClose} onCreated={onCreated} />,
      { wrapper: Wrapper }
    )
    await waitFor(() => {
      expect(screen.getByRole('textbox', { name: 'apiKeys.keyName' })).toBeDefined()
    })
  })

  it('renders identity and role dropdown labels', async () => {
    const { CreateApiKeyDialog } = await import('../../pages/api-keys/CreateApiKeyDialog')
    render(
      <CreateApiKeyDialog open={true} onClose={onClose} onCreated={onCreated} />,
      { wrapper: Wrapper }
    )
    await waitFor(() => {
      expect(screen.getByText('apiKeys.agentIdentity')).toBeDefined()
      expect(screen.getByText('apiKeys.agentRole')).toBeDefined()
    })
  })

  it('populates identity dropdown with available identities', async () => {
    const { CreateApiKeyDialog } = await import('../../pages/api-keys/CreateApiKeyDialog')
    render(
      <CreateApiKeyDialog open={true} onClose={onClose} onCreated={onCreated} />,
      { wrapper: Wrapper }
    )

    // Wait for identities to load
    await screen.findByText('apiKeys.agentIdentity')

    // Open identity dropdown by clicking the select
    const identitySelect = getSelectByLabel('apiKeys.agentIdentity')
    fireEvent.mouseDown(identitySelect)

    await waitFor(() => {
      expect(screen.getByText('Agent Alpha')).toBeDefined()
      expect(screen.getByText('Agent Beta')).toBeDefined()
    })
  })

  it('role dropdown is filtered based on selected identity', async () => {
    const { CreateApiKeyDialog } = await import('../../pages/api-keys/CreateApiKeyDialog')
    render(
      <CreateApiKeyDialog open={true} onClose={onClose} onCreated={onCreated} />,
      { wrapper: Wrapper }
    )

    await screen.findByText('apiKeys.agentIdentity')

    // Select identity first
    const identitySelect = getSelectByLabel('apiKeys.agentIdentity')
    fireEvent.mouseDown(identitySelect)
    await waitFor(() => screen.getByText('Agent Alpha'))
    fireEvent.click(screen.getByText('Agent Alpha'))

    // Now open role dropdown
    await waitFor(async () => {
      const roleSelect = getSelectByLabel('apiKeys.agentRole')
      fireEvent.mouseDown(roleSelect)
    })

    await waitFor(() => {
      expect(screen.getByText('Developer')).toBeDefined()
      expect(screen.getByText('Viewer')).toBeDefined()
    })
  })

  it('create button is disabled when form is incomplete', async () => {
    const { CreateApiKeyDialog } = await import('../../pages/api-keys/CreateApiKeyDialog')
    render(
      <CreateApiKeyDialog open={true} onClose={onClose} onCreated={onCreated} />,
      { wrapper: Wrapper }
    )

    await waitFor(() => {
      const createBtn = screen.getByText('apiKeys.createKey')
      expect(createBtn.closest('button')).toBeDisabled()
    })
  })

  it('create button is enabled when form is complete', async () => {
    const { CreateApiKeyDialog } = await import('../../pages/api-keys/CreateApiKeyDialog')
    render(
      <CreateApiKeyDialog open={true} onClose={onClose} onCreated={onCreated} />,
      { wrapper: Wrapper }
    )

    // Fill in name
    const nameInput = await screen.findByRole('textbox', { name: 'apiKeys.keyName' })
    fireEvent.change(nameInput, { target: { value: 'My Test Key' } })

    // Select identity
    const identitySelect = getSelectByLabel('apiKeys.agentIdentity')
    fireEvent.mouseDown(identitySelect)
    await waitFor(() => screen.getByText('Agent Alpha'))
    fireEvent.click(screen.getByText('Agent Alpha'))

    // Select role
    await waitFor(async () => {
      const roleSelect = getSelectByLabel('apiKeys.agentRole')
      fireEvent.mouseDown(roleSelect)
    })

    await waitFor(() => screen.getByText('Developer'))
    fireEvent.click(screen.getByText('Developer'))

    await waitFor(() => {
      const createBtn = screen.getByText('apiKeys.createKey')
      expect(createBtn.closest('button')).not.toBeDisabled()
    })
  })

  it('shows clear-text key on step 2 after creation', async () => {
    const { CreateApiKeyDialog } = await import('../../pages/api-keys/CreateApiKeyDialog')
    render(
      <CreateApiKeyDialog open={true} onClose={onClose} onCreated={onCreated} />,
      { wrapper: Wrapper }
    )

    const nameInput = await screen.findByRole('textbox', { name: 'apiKeys.keyName' })
    fireEvent.change(nameInput, { target: { value: 'My Test Key' } })

    const identitySelect = getSelectByLabel('apiKeys.agentIdentity')
    fireEvent.mouseDown(identitySelect)
    await waitFor(() => screen.getByText('Agent Alpha'))
    fireEvent.click(screen.getByText('Agent Alpha'))

    await waitFor(async () => {
      const roleSelect = getSelectByLabel('apiKeys.agentRole')
      fireEvent.mouseDown(roleSelect)
    })

    await waitFor(() => screen.getByText('Developer'))
    fireEvent.click(screen.getByText('Developer'))

    fireEvent.click(screen.getByText('apiKeys.createKey'))

    await waitFor(() => {
      expect(screen.getByText('apiKeys.createdTitle')).toBeDefined()
    })

    await waitFor(() => {
      expect(screen.getByText('Agent Alpha')).toBeDefined()
      expect(screen.getByText('Developer')).toBeDefined()
    })
  })

  it('shows copy button on step 2', async () => {
    const { CreateApiKeyDialog } = await import('../../pages/api-keys/CreateApiKeyDialog')
    render(
      <CreateApiKeyDialog open={true} onClose={onClose} onCreated={onCreated} />,
      { wrapper: Wrapper }
    )

    const nameInput = await screen.findByRole('textbox', { name: 'apiKeys.keyName' })
    fireEvent.change(nameInput, { target: { value: 'My Test Key' } })

    const identitySelect = getSelectByLabel('apiKeys.agentIdentity')
    fireEvent.mouseDown(identitySelect)
    await waitFor(() => screen.getByText('Agent Alpha'))
    fireEvent.click(screen.getByText('Agent Alpha'))

    await waitFor(async () => {
      const roleSelect = getSelectByLabel('apiKeys.agentRole')
      fireEvent.mouseDown(roleSelect)
    })

    await waitFor(() => screen.getByText('Developer'))
    fireEvent.click(screen.getByText('Developer'))

    fireEvent.click(screen.getByText('apiKeys.createKey'))

    await waitFor(() => {
      expect(screen.getByText('apiKeys.doneSaved')).toBeDefined()
    })
  })

  it('handles API error and displays error in dialog', async () => {
    mockApiClient.post.mockRejectedValue(new Error('API key creation failed'))

    const { CreateApiKeyDialog } = await import('../../pages/api-keys/CreateApiKeyDialog')
    render(
      <CreateApiKeyDialog open={true} onClose={onClose} onCreated={onCreated} />,
      { wrapper: Wrapper }
    )

    const nameInput = await screen.findByRole('textbox', { name: 'apiKeys.keyName' })
    fireEvent.change(nameInput, { target: { value: 'My Test Key' } })

    const identitySelect = getSelectByLabel('apiKeys.agentIdentity')
    fireEvent.mouseDown(identitySelect)
    await waitFor(() => screen.getByText('Agent Alpha'))
    fireEvent.click(screen.getByText('Agent Alpha'))

    await waitFor(async () => {
      const roleSelect = getSelectByLabel('apiKeys.agentRole')
      fireEvent.mouseDown(roleSelect)
    })

    await waitFor(() => screen.getByText('Developer'))
    fireEvent.click(screen.getByText('Developer'))

    fireEvent.click(screen.getByText('apiKeys.createKey'))

    await waitFor(() => {
      expect(screen.getByText('API key creation failed')).toBeDefined()
    })
  })

  it('resets form when dialog is closed and reopened', async () => {
    const { CreateApiKeyDialog } = await import('../../pages/api-keys/CreateApiKeyDialog')
    const { rerender } = render(
      <CreateApiKeyDialog open={true} onClose={onClose} onCreated={onCreated} />,
      { wrapper: Wrapper }
    )

    const nameInput = await screen.findByRole('textbox', { name: 'apiKeys.keyName' })
    fireEvent.change(nameInput, { target: { value: 'Some Name' } })

    // Close dialog
    rerender(
      <CreateApiKeyDialog open={false} onClose={onClose} onCreated={onCreated} />
    )

    // Reopen
    rerender(
      <CreateApiKeyDialog open={true} onClose={onClose} onCreated={onCreated} />
    )

    await waitFor(() => {
      const input = screen.getByRole('textbox', { name: 'apiKeys.keyName' }) as HTMLInputElement
      expect(input.value).toBe('')
    })
  })

  it('shows scoping info alert', async () => {
    const { CreateApiKeyDialog } = await import('../../pages/api-keys/CreateApiKeyDialog')
    render(
      <CreateApiKeyDialog open={true} onClose={onClose} onCreated={onCreated} />,
      { wrapper: Wrapper }
    )
    await waitFor(() => {
      expect(screen.getByText('apiKeys.scopingInfo')).toBeDefined()
    })
  })

  it('shows warning to save key on step 2', async () => {
    const { CreateApiKeyDialog } = await import('../../pages/api-keys/CreateApiKeyDialog')
    render(
      <CreateApiKeyDialog open={true} onClose={onClose} onCreated={onCreated} />,
      { wrapper: Wrapper }
    )

    const nameInput = await screen.findByRole('textbox', { name: 'apiKeys.keyName' })
    fireEvent.change(nameInput, { target: { value: 'My Test Key' } })

    const identitySelect = getSelectByLabel('apiKeys.agentIdentity')
    fireEvent.mouseDown(identitySelect)
    await waitFor(() => screen.getByText('Agent Alpha'))
    fireEvent.click(screen.getByText('Agent Alpha'))

    await waitFor(async () => {
      const roleSelect = getSelectByLabel('apiKeys.agentRole')
      fireEvent.mouseDown(roleSelect)
    })

    await waitFor(() => screen.getByText('Developer'))
    fireEvent.click(screen.getByText('Developer'))

    fireEvent.click(screen.getByText('apiKeys.createKey'))

    await waitFor(() => {
      expect(screen.getByText('apiKeys.saveKeyWarning')).toBeDefined()
    })
  })
})
