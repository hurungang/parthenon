import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { ProtectedRoute } from './ProtectedRoute'
import { AppShell } from './AppShell'
import { LoginPage } from '../pages/auth/LoginPage'
import { OidcCallback } from '../pages/auth/OidcCallback'
import { SetupWizard } from '../pages/setup/SetupWizard'
import { McpHubPage } from '../pages/mcp/McpHubPage'
import { SkillListPage } from '../pages/skills/SkillListPage'
import { SopListPage } from '../pages/skills/SopListPage'
import { AgentManagementPage } from '../pages/agents/AgentManagementPage'
import { AgentRoleListPage } from '../pages/agents/AgentRoleListPage'
import { AgentIdentityListPage } from '../pages/agents/AgentIdentityListPage'
import { AgentJobPage } from '../pages/agents/AgentJobPage'
import { AgentOAuthCallbackPage } from '../pages/agents/AgentOAuthCallbackPage'
import { ModelConfigListPage } from '../pages/agents/ModelConfigListPage'
import { AgentInstanceDashboardPage } from '../pages/agents/AgentInstanceDashboardPage'
import OAuthCallback from '../pages/OAuthCallback'
import { GatewayConfigPage } from '../pages/gateway/GatewayConfigPage'
import { ScheduleManagerPage } from '../pages/scheduling/ScheduleManagerPage'
import { ConversationHistoryPage } from '../pages/conversations/ConversationHistoryPage'
import { ResultRepositoryPage } from '../pages/results/ResultRepositoryPage'
import { NotificationConfigPage } from '../pages/notifications/NotificationConfigPage'
import { ObservabilityDashboard } from '../pages/observability/ObservabilityDashboard'
import { ChatPage } from '../pages/chat/ChatPage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { DashboardPage } from '../pages/DashboardPage'
import { PermissionsPage } from '../pages/permissions/PermissionsPage'
import { AccessRequestsPage } from '../pages/permissions/AccessRequestsPage'
import { AccessDeniedPage } from '../pages/AccessDeniedPage'
import { getIdentityStatus } from '../api/setupApi'
import { SetupState } from '../types/setup'

/**
 * Inner router — rendered inside BrowserRouter so it can use hooks.
 * Checks identity status on mount and redirects to /setup when NOT_CONFIGURED.
 */
function AppRoutes() {
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null)
  const location = useLocation()

  useEffect(() => {
    let cancelled = false

    getIdentityStatus()
      .then((status) => {
        if (!cancelled) {
          setNeedsSetup(status.setup_state === SetupState.NOT_CONFIGURED)
        }
      })
      .catch(() => {
        // If status check fails (e.g. backend not yet reachable), assume not configured
        if (!cancelled) {
          setNeedsSetup(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  // While checking, render nothing (prevents flash of wrong content)
  if (needsSetup === null) {
    return null
  }

  // Redirect to /setup if not configured and not already there
  if (needsSetup && location.pathname !== '/setup') {
    return <Navigate to="/setup" replace />
  }

  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/callback" element={<OidcCallback />} />
      <Route path="/setup" element={<SetupWizard />} />
      <Route path="/access-denied" element={<AccessDeniedPage />} />
      {/* Agent OAuth callback — opened in popup; must be accessible without app shell */}
      <Route path="/agents/identities/oauth/callback" element={<AgentOAuthCallbackPage />} />
      {/* MCP OAuth callback — opened in popup; must be accessible without app shell */}
      <Route path="/oauth/callback" element={<OAuthCallback />} />

      {/* Protected routes wrapped in AppShell */}
      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/mcp" element={<McpHubPage />} />
        <Route path="/skills" element={<SkillListPage />} />
        <Route path="/sops" element={<SopListPage />} />
        <Route path="/agents" element={<AgentManagementPage />} />
        <Route path="/agents/roles" element={<AgentRoleListPage />} />
        <Route path="/agents/identities" element={<AgentIdentityListPage />} />
        <Route path="/agents/sessions/:id" element={<AgentJobPage />} />
        <Route path="/agents/model-configs" element={<ModelConfigListPage />} />
        <Route path="/agents/instances" element={<AgentInstanceDashboardPage />} />
        <Route path="/gateway" element={<GatewayConfigPage />} />
        <Route path="/schedules" element={<ScheduleManagerPage />} />
        <Route path="/conversations" element={<ConversationHistoryPage />} />
        <Route path="/results" element={<ResultRepositoryPage />} />
        <Route path="/notifications" element={<NotificationConfigPage />} />
        <Route path="/observability" element={<ObservabilityDashboard />} />
        <Route path="/chat/:agentTypeId?" element={<ChatPage />} />
        <Route path="/permissions/access-requests" element={<AccessRequestsPage />} />
        <Route path="/user-permissions/*" element={<PermissionsPage />} />
      </Route>

      {/* Catch-all */}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}

/**
 * React Router 7 route tree with protected and public route guards.
 * Includes a first-run redirect guard that calls getIdentityStatus() on mount.
 */
export function AppRouter() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}
