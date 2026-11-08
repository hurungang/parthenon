import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

const { mockFetch, mockCreate, mockTypeOptions, mockUpdateStatus, mockDelete, mockUpdate } =
  vi.hoisted(() => ({
    mockFetch: vi.fn(),
    mockCreate: vi.fn(),
    mockTypeOptions: vi.fn(),
    mockUpdateStatus: vi.fn(),
    mockDelete: vi.fn(),
    mockUpdate: vi.fn(),
  }))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, d?: string) => d ?? k }),
}))

vi.mock('../../api/agentClientsApi', () => ({
  fetchAgentClients: mockFetch,
  fetchAgentTypeOptions: mockTypeOptions,
  createAgentClient: mockCreate,
  updateAgentClientStatus: mockUpdateStatus,
  updateAgentClient: mockUpdate,
  deleteAgentClient: mockDelete,
  revokeAgentClient: vi.fn(),
  rotateAgentClientCredential: vi.fn(),
}))

import { AgentClientsPage } from '../../pages/agent-types/AgentClientsPage'

const MOCK_CLIENTS = [
  {
    id: 'c1',
    name: 'Acme Support Bot',
    slug: 'acme',
    agent_type_id: 'at1',
    agent_type_name: 'Support Bot',
    key_type: 'publishable',
    key_prefix: 'phn_cl_pk_',
    status: 'active',
    white_label_theme: null,
    allowed_origins: ['https://acme.com'],
    rate_limit: 100,
    rate_limit_window: 'per_minute',
    created_at: '2026-01-01T00:00:00Z',
    last_used_at: null,
    expires_at: null,
  },
]

describe('AgentClientsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockFetch.mockResolvedValue(MOCK_CLIENTS)
    mockTypeOptions.mockResolvedValue([{ id: 'at2', name: 'Triage' }])
  })

  it('renders the client list with agent type and credential type', async () => {
    render(<AgentClientsPage />)
    await waitFor(() => expect(screen.getByText('Acme Support Bot')).toBeInTheDocument())
    expect(screen.getByRole('cell', { name: 'Support Bot' })).toBeInTheDocument()
    expect(screen.getByText('publishable')).toBeInTheDocument()
  })

  it('shows the publishable soft warning in the create dialog', async () => {
    render(<AgentClientsPage />)
    await waitFor(() => expect(screen.getByText('Acme Support Bot')).toBeInTheDocument())
    fireEvent.click(screen.getByText('New Client'))
    expect(screen.getByText(/exposes this agent type/i)).toBeInTheDocument()
  })

  it('creates a client (searchable agent-type dropdown) and shows the credential once', async () => {
    mockCreate.mockResolvedValue({
      id: 'c2',
      name: 'Nimbus',
      key_type: 'secret',
      key_prefix: 'phn_cl_sk_',
      client_key: 'phn_cl_sk_secret_value',
      agent_type_id: 'at2',
      agent_type_name: 'Triage',
      created_at: '2026-01-01T00:00:00Z',
    })

    render(<AgentClientsPage />)
    await waitFor(() => expect(screen.getByText('Acme Support Bot')).toBeInTheDocument())

    fireEvent.click(screen.getByText('New Client'))
    fireEvent.change(screen.getByLabelText('Client name'), { target: { value: 'Nimbus' } })

    // Open the agent-type autocomplete and pick the option.
    const combo = screen.getByRole('combobox', { name: /Agent type/i })
    fireEvent.mouseDown(combo)
    fireEvent.click(await screen.findByText('Triage'))

    // Publishable clients require at least one allowed origin.
    fireEvent.change(screen.getByLabelText('Allowed origins (one per line)'), {
      target: { value: 'https://acme.com' },
    })

    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    expect(mockCreate).toHaveBeenCalledWith(
      expect.objectContaining({ agent_type_id: 'at2', key_type: 'publishable' }),
    )
    await waitFor(() =>
      expect(screen.getByDisplayValue('phn_cl_sk_secret_value')).toBeInTheDocument(),
    )
  })

  it('requires an allowed origin for publishable clients (Save disabled)', async () => {
    render(<AgentClientsPage />)
    await waitFor(() => expect(screen.getByText('Acme Support Bot')).toBeInTheDocument())

    fireEvent.click(screen.getByText('New Client'))
    fireEvent.change(screen.getByLabelText('Client name'), { target: { value: 'X' } })
    const combo = screen.getByRole('combobox', { name: /Agent type/i })
    fireEvent.mouseDown(combo)
    fireEvent.click(await screen.findByText('Triage'))

    // publishable is the default; without an origin, Save stays disabled.
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('deactivates a client via the status toggle', async () => {
    mockUpdateStatus.mockResolvedValue({ ...MOCK_CLIENTS[0], status: 'inactive' })

    const { container } = render(<AgentClientsPage />)
    await waitFor(() => expect(screen.getByText('Acme Support Bot')).toBeInTheDocument())

    const toggle = container.querySelector('input[type="checkbox"]') as HTMLInputElement
    expect(toggle).toBeTruthy()
    fireEvent.click(toggle)
    await waitFor(() => expect(mockUpdateStatus).toHaveBeenCalledWith('c1', 'inactive'))
  })

  it('removes a client after confirmation', async () => {
    mockDelete.mockResolvedValue({ id: 'c1', status: 'deleted', message: 'Client deleted' })

    render(<AgentClientsPage />)
    await waitFor(() => expect(screen.getByText('Acme Support Bot')).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText('delete'))
    fireEvent.click(screen.getByText('Remove'))
    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('c1'))
  })

  it('edits a client (origins + rate limit only) and saves', async () => {    mockUpdate.mockResolvedValue(MOCK_CLIENTS[0])

    render(<AgentClientsPage />)
    await waitFor(() => expect(screen.getByText('Acme Support Bot')).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText('edit'))
    // The edit dialog shows only the origins + rate-limit fields.
    const origins = screen.getByLabelText('Allowed origins (one per line)')
    fireEvent.change(origins, { target: { value: 'https://acme.com\nhttps://*.acme.com' } })
    fireEvent.change(screen.getByLabelText('Rate limit'), { target: { value: '250' } })
    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1))
    expect(mockUpdate).toHaveBeenCalledWith('c1', {
      allowed_origins: ['https://acme.com', 'https://*.acme.com'],
      rate_limit: 250,
      rate_limit_window: 'per_minute',
    })
  })
})
