import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { SetupState } from '../../types/setup'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

vi.mock('../../api/setupApi', () => ({
  getIdentityStatus: vi.fn(),
}))

// Stub all page components to simple divs to avoid deep render trees
vi.mock('../../pages/auth/LoginPage', () => ({ LoginPage: () => <div>LoginPage</div> }))
vi.mock('../../pages/auth/OidcCallback', () => ({ OidcCallback: () => <div>OidcCallback</div> }))
vi.mock('../../pages/setup/SetupWizard', () => ({ SetupWizard: () => <div>setup.title</div> }))
vi.mock('../../pages/DashboardPage', () => ({ DashboardPage: () => <div>Dashboard</div> }))
vi.mock('../../pages/NotFoundPage', () => ({ NotFoundPage: () => <div>NotFound</div> }))
vi.mock('../../pages/mcp/McpHubPage', () => ({ McpHubPage: () => <div>Mcp</div> }))
vi.mock('../../pages/skills/SkillListPage', () => ({ SkillListPage: () => <div>Skills</div> }))
vi.mock('../../pages/skills/SopListPage', () => ({ SopListPage: () => <div>Sops</div> }))
vi.mock('../../pages/agents/AgentManagementPage', () => ({
  AgentManagementPage: () => <div>Agents</div>,
}))
vi.mock('../../pages/gateway/GatewayConfigPage', () => ({
  GatewayConfigPage: () => <div>Gateway</div>,
}))
vi.mock('../../pages/scheduling/ScheduleManagerPage', () => ({
  ScheduleManagerPage: () => <div>Schedule</div>,
}))
vi.mock('../../pages/conversations/ConversationHistoryPage', () => ({
  ConversationHistoryPage: () => <div>Conversations</div>,
}))
vi.mock('../../pages/results/ResultRepositoryPage', () => ({
  ResultRepositoryPage: () => <div>Results</div>,
}))
vi.mock('../../pages/notifications/NotificationConfigPage', () => ({
  NotificationConfigPage: () => <div>Notifications</div>,
}))
vi.mock('../../pages/observability/ObservabilityDashboard', () => ({
  ObservabilityDashboard: () => <div>Observability</div>,
}))
vi.mock('../../pages/chat/ChatPage', () => ({ ChatPage: () => <div>Chat</div> }))
vi.mock('../../app/ProtectedRoute', () => ({
  ProtectedRoute: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
vi.mock('../../app/AppShell', () => ({
  AppShell: () => <div>AppShell</div>,
}))

import { AppRouter } from '../../app/AppRouter'
import { getIdentityStatus } from '../../api/setupApi'
const mockedGetIdentityStatus = vi.mocked(getIdentityStatus)

describe('AppRouter first-run redirect', () => {
  afterEach(() => vi.clearAllMocks())

  it('redirects to /setup when NOT_CONFIGURED', async () => {
    mockedGetIdentityStatus.mockResolvedValueOnce({
      setup_state: SetupState.NOT_CONFIGURED,
      provider_type: null,
      oidc_provider_url: null,
    })
    render(<AppRouter />)
    await waitFor(() => {
      expect(screen.getByText('setup.title')).toBeDefined()
    })
  })

  it('renders normal routes when CONFIGURED', async () => {
    mockedGetIdentityStatus.mockResolvedValueOnce({
      setup_state: SetupState.CONFIGURED,
      provider_type: 'keycloak_bundled',
      oidc_provider_url: 'http://localhost:8080',
    })
    render(<AppRouter />)
    await waitFor(() => {
      expect(screen.queryByText('setup.title')).toBeNull()
    })
  })

  it('does NOT redirect when identity check throws', async () => {
    mockedGetIdentityStatus.mockRejectedValueOnce(new Error('network fail'))
    render(<AppRouter />)
    await waitFor(() => {
      expect(screen.queryByText('setup.title')).toBeNull()
    })
  })
})
