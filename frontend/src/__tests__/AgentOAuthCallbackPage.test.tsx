/**
 * Tests for AgentOAuthCallbackPage — the popup page that handles the OAuth
 * authorization code callback for agent realm sign-in.
 *
 * Adjustment: Agent identities are users in a dedicated agent realm. The callback
 * page exchanges the code for tokens via the backend, then posts a message to
 * the opener window and closes the popup.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const mockGet = vi.fn()

vi.mock('../api/apiClient', () => ({
  default: {
    get: mockGet,
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

// Helper: render callback page with query params
async function renderCallbackPage(search: string) {
  const { AgentOAuthCallbackPage } = await import('../pages/agents/AgentOAuthCallbackPage')
  return render(
    <MemoryRouter initialEntries={[`/agents/identities/oauth/callback${search}`]}>
      <AgentOAuthCallbackPage />
    </MemoryRouter>,
  )
}

describe('AgentOAuthCallbackPage', () => {
  let mockOpener: { postMessage: ReturnType<typeof vi.fn> }

  beforeEach(() => {
    vi.clearAllMocks()
    mockOpener = { postMessage: vi.fn() }
    // Stub window.opener and window.close for popup behavior
    vi.stubGlobal('opener', mockOpener)
    vi.stubGlobal('close', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // ── Loading state ────────────────────────────────────────────────────────────

  it('renders a loading spinner while processing', async () => {
    // Mock a slow API call so we can observe the loading state
    mockGet.mockReturnValue(new Promise(() => {})) // never resolves

    await renderCallbackPage('?code=abc123&state=identity-id-1')

    await waitFor(() => {
      // Loading text from i18n key
      expect(screen.getByText('agents.identities.oauthPending')).toBeDefined()
    })
  })

  // ── Success path ─────────────────────────────────────────────────────────────

  it('posts AGENT_OAUTH_SUCCESS to opener when callback succeeds', async () => {
    const fakeIdentity = {
      id: 'identity-id-1',
      name: 'OAuth Bot',
      realm_name: 'ai_agents',
      status: 'active',
    }
    mockGet.mockResolvedValue({ data: fakeIdentity })

    await renderCallbackPage('?code=auth-code-123&state=identity-id-1')

    await waitFor(() => {
      expect(mockOpener.postMessage).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'AGENT_OAUTH_SUCCESS', identity: fakeIdentity }),
        window.location.origin,
      )
    })
  })

  // ── Error paths ───────────────────────────────────────────────────────────────

  it('posts AGENT_OAUTH_ERROR when IdP returns an error param', async () => {
    await renderCallbackPage('?error=access_denied&error_description=User+denied')

    await waitFor(() => {
      expect(mockOpener.postMessage).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'AGENT_OAUTH_ERROR', error: 'access_denied' }),
        window.location.origin,
      )
    })
    // API must not be called when IdP itself returned an error
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('posts AGENT_OAUTH_ERROR when code or state params are missing', async () => {
    // No code or state — malformed callback
    await renderCallbackPage('?foo=bar')

    await waitFor(() => {
      expect(mockOpener.postMessage).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'AGENT_OAUTH_ERROR', error: 'missing_params' }),
        window.location.origin,
      )
    })
  })

  it('posts AGENT_OAUTH_ERROR when backend callback API fails', async () => {
    mockGet.mockRejectedValue({ response: { data: { detail: 'Token exchange failed' } } })

    await renderCallbackPage('?code=bad-code&state=identity-id-1')

    await waitFor(() => {
      expect(mockOpener.postMessage).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'AGENT_OAUTH_ERROR',
          error: 'callback_failed',
        }),
        window.location.origin,
      )
    })
  })
})
