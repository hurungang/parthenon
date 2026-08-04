import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
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
import { RuntimeControlDashboardPage } from '../pages/agents/RuntimeControlDashboardPage'
import { IntervenePage } from '../pages/agents/IntervenePage'
import OAuthCallback from '../pages/OAuthCallback'
import { GatewayConfigPage } from '../pages/gateway/GatewayConfigPage'
import { ScheduleManagerPage } from '../pages/scheduling/ScheduleManagerPage'
import { ConversationHistoryPage } from '../pages/conversations/ConversationHistoryPage'
import { AgentTrailsPage } from '../pages/trails/AgentTrailsPage'
import { AgentDataPage } from '../pages/agent-data/AgentDataPage'
import { NotificationConfigPage } from '../pages/notifications/NotificationConfigPage'
import { ChannelListPage } from '../pages/notifications/ChannelListPage'
import { RecipientGroupListPage } from '../pages/notifications/RecipientGroupListPage'
import { NotificationLogPage } from '../pages/notifications/NotificationLogPage'
import { ObservabilityDashboard } from '../pages/observability/ObservabilityDashboard'
import { ChatPage } from '../pages/chat/ChatPage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { DashboardPage } from '../pages/DashboardPage'
import { PermissionsPage } from '../pages/permissions/PermissionsPage'
import { AccessRequestsPage } from '../pages/permissions/AccessRequestsPage'
import { SystemConfigPage } from '../pages/system/SystemConfigPage'
import { IdentityProvidersConfigPage } from '../pages/system/IdentityProvidersConfigPage'
import { DataTypesPage } from '../pages/data-types/DataTypesPage'
import { AgentOutputsPage } from '../pages/agent-outputs/AgentOutputsPage'
import { ApiKeyListPage } from '../pages/api-keys/ApiKeyListPage'
import { AccessDeniedPage } from '../pages/AccessDeniedPage'

/**
 * React Router 7 route tree with protected and public route guards.
 * The LoginPage handles all auth routing decisions (super admin, OIDC, setup wizard)
 * based on live provider discovery — no server-side setup-state redirect is needed.
 */
export function AppRouter() {
  return (
    <BrowserRouter>
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
          <Route path="/agents/executions" element={<AgentInstanceDashboardPage />} />
          <Route path="/agents/runtime-control" element={<RuntimeControlDashboardPage />} />
          <Route path="/agents/instances" element={<Navigate to="/agents/executions" replace />} />
          <Route path="/agents/intervene" element={<IntervenePage />} />
          <Route path="/gateway" element={<GatewayConfigPage />} />
          <Route path="/schedules" element={<ScheduleManagerPage />} />
          <Route path="/conversations" element={<ConversationHistoryPage />} />
          <Route path="/agent-trails" element={<AgentTrailsPage />} />
          <Route path="/admin/agent-data" element={<AgentDataPage />} />
          <Route path="/notifications" element={<NotificationConfigPage />} />
          <Route path="/admin/notifications/channels" element={<ChannelListPage />} />
          <Route path="/admin/notifications/groups" element={<RecipientGroupListPage />} />
          <Route path="/admin/notifications/logs" element={<NotificationLogPage />} />
          <Route path="/observability" element={<ObservabilityDashboard />} />
          <Route path="/admin/data-types" element={<DataTypesPage />} />
          <Route path="/admin/agent-outputs" element={<AgentOutputsPage />} />
          <Route path="/system-config" element={<SystemConfigPage />} />
          <Route path="/system/identity-providers" element={<IdentityProvidersConfigPage />} />
          <Route path="/chat/:agentTypeId?" element={<ChatPage />} />
          <Route path="/agents/:agentTypeId/chat/:sessionId" element={<ChatPage />} />
          <Route path="/api-keys" element={<ApiKeyListPage />} />
          <Route path="/permissions/access-requests" element={<AccessRequestsPage />} />
          <Route path="/user-permissions/*" element={<PermissionsPage />} />
        </Route>

        {/* Catch-all */}
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  )
}
