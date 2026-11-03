import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { ConversationDialog } from '../components/agents/ConversationDialog'
import { useChatSession } from '../hooks/useChatSession'
import apiClient from '../api/apiClient'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../api/apiClient', () => ({
  default: {
    get: vi.fn(),
    put: vi.fn(),
    post: vi.fn(),
  },
}))

// ConversationDialog plays a WebSocket on send paths; keep it inert in tests.
class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  readyState = 1
  constructor(public url: string) {
    FakeWebSocket.instances.push(this)
  }
  send = vi.fn()
  close = vi.fn()
}
const OriginalWebSocket = global.WebSocket

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

function mockAssistantModel(selected_model_id: string | null) {
  vi.mocked(apiClient.get).mockImplementation((url: string) => {
    if (url === '/agents/model-configs/assistant-model') {
      return Promise.resolve({ data: { selected_model_id, options: [] } })
    }
    return Promise.resolve({ data: {} })
  })
}

function renderDialog() {
  return render(
    <ConversationDialog
      open
      sessionId={null}
      agentTypeId="at-assistant"
      agentTypeName="Assistant"
      testIdPrefix="assistant-conversation"
      assistantModelConfigCheck
      onClose={vi.fn()}
    />,
    { wrapper },
  )
}

describe('ConversationDialog assistant model guidance', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    global.WebSocket = FakeWebSocket as unknown as typeof WebSocket
  })
  afterAll(() => {
    global.WebSocket = OriginalWebSocket
  })

  it('shows the guidance banner, Configure-model action, and disables input when unconfigured', async () => {
    mockAssistantModel(null)
    renderDialog()

    await waitFor(() => {
      expect(
        screen.getByTestId('assistant-conversation-assistant-model-not-configured'),
      ).toBeDefined()
    })
    expect(screen.getByText('assistant.modelNotConfiguredTitle')).toBeDefined()
    const cta = screen.getByTestId('assistant-conversation-configure-assistant-model')
    expect(cta).toBeDefined()
    expect(cta.textContent).toBe('assistant.modelNotConfiguredCta')

    const input = screen.getByRole('textbox') as HTMLTextAreaElement
    expect(input.disabled).toBe(true)
    expect((screen.getByText('conversations.sessions.send') as HTMLButtonElement).disabled).toBe(
      true,
    )
  })

  it('shows no banner and keeps the input enabled when a model is configured', async () => {
    mockAssistantModel('gpt-4o')
    renderDialog()

    await waitFor(() => {
      expect(vi.mocked(apiClient.get)).toHaveBeenCalledWith(
        '/agents/model-configs/assistant-model',
      )
    })
    expect(
      screen.queryByTestId('assistant-conversation-assistant-model-not-configured'),
    ).toBeNull()
    const input = screen.getByRole('textbox') as HTMLTextAreaElement
    expect(input.disabled).toBe(false)
  })
})

describe('useChatSession structured chat_error mapping', () => {
  beforeEach(() => {
    global.WebSocket = FakeWebSocket as unknown as typeof WebSocket
    FakeWebSocket.instances = []
  })
  afterAll(() => {
    global.WebSocket = OriginalWebSocket
  })

  function Harness({ onState }: { onState: (chatError: { code: string } | null) => void }) {
    const { chatError } = useChatSession('ws-session-1')
    onState(chatError)
    return <div>{chatError?.code ?? 'no-error'}</div>
  }

  it('parses the assistant_model_not_configured payload into chatError state', async () => {
    let latest: { code: string } | null = null
    render(<Harness onState={(e) => (latest = e)} />, { wrapper })

    await waitFor(() => {
      expect(FakeWebSocket.instances.length).toBe(1)
    })
    const ws = FakeWebSocket.instances[0]
    ws.onopen?.()
    ws.onmessage?.({
      data: JSON.stringify({
        type: 'chat_error',
        code: 'assistant_model_not_configured',
        message: 'No model is configured for this workspace yet.',
      }),
    })

    await waitFor(() => {
      expect(latest?.code).toBe('assistant_model_not_configured')
    })
    expect(screen.getByText('assistant_model_not_configured')).toBeDefined()
  })
})
