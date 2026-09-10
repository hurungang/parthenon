import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { Outlet } from 'react-router-dom'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

// Stub all page components to simple divs to avoid deep render trees
vi.mock('../../pages/auth/LoginPage', () => ({ LoginPage: () => <div>LoginPage</div> }))
vi.mock('../../pages/auth/OidcCallback', () => ({ OidcCallback: () => <div>OidcCallback</div> }))
vi.mock('../../pages/setup/SetupWizard', () => ({ SetupWizard: () => <div>SetupWizard</div> }))
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
vi.mock('../../pages/trails/AgentTrailsPage', () => ({
  AgentTrailsPage: () => <div>Trails</div>,
}))
vi.mock('../../pages/agent-data/AgentDataPage', () => ({
  AgentDataPage: () => <div>AgentData</div>,
}))
vi.mock('../../pages/agent-outputs/AgentOutputsPage', () => ({
  AgentOutputsPage: () => <div>AgentOutputs</div>,
}))
vi.mock('../../pages/data-types/DataTypesPage', () => ({
  DataTypesPage: () => <div>DataTypes</div>,
}))
vi.mock('../../pages/api-keys/ApiKeyListPage', () => ({
  ApiKeyListPage: () => <div>ApiKeys</div>,
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
  AppShell: () => (
    <div>
      <div>AppShell</div>
      <Outlet />
    </div>
  ),
}))

import { AppRouter } from '../../app/AppRouter'

describe('AppRouter', () => {
  it('redirects root to dashboard', async () => {
    render(<AppRouter />)
    await waitFor(() => {
      expect(screen.getByText('Dashboard')).toBeDefined()
    })
  })
})
