import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ProtectedRoute } from './ProtectedRoute'
import { AppShell } from './AppShell'
import { LoginPage } from '../pages/auth/LoginPage'
import { SignUpPage } from '../pages/auth/SignUpPage'
import { OidcCallback } from '../pages/auth/OidcCallback'
import { McpHubPage } from '../pages/mcp/McpHubPage'
import { SkillListPage } from '../pages/skills/SkillListPage'
import { SopListPage } from '../pages/skills/SopListPage'
import { AgentManagementPage } from '../pages/agents/AgentManagementPage'
import { AgentManagementPanelPage } from '../pages/agents/AgentManagementPanelPage'
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
import { SystemOneProviderConfigPage } from '../pages/system/SystemOneProviderConfigPage'
import { DecisionToolsPage } from '../pages/agents/DecisionToolsPage'
import { DataTypesPage } from '../pages/data-types/DataTypesPage'
import { AgentOutputsPage } from '../pages/agent-outputs/AgentOutputsPage'
import { ApiKeyListPage } from '../pages/api-keys/ApiKeyListPage'
import { AccessDeniedPage } from '../pages/AccessDeniedPage'
import { TenantSettingsPage } from '../pages/tenant/TenantSettingsPage'
import { OnboardingPage } from '../pages/tenant/OnboardingPage'
import { MembersPage } from '../pages/tenant/MembersPage'
import { InvitationAcceptPage } from '../pages/tenant/InvitationAcceptPage'
import { PlatformAdminRoute } from './PlatformAdminRoute'
import { PlatformRoutes } from './PlatformRoutes'

/**
 * React Router 7 route tree with protected and public route guards.
 * The LoginPage handles all auth routing decisions (password sign-in, OIDC,
 * super admin) based on live provider discovery — the pre-auth setup wizard
 * is removed; identity providers are configured post-sign-in via System
 * Config / Tenant Settings.
 */
export function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public routes */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignUpPage />} />
        <Route path="/callback" element={<OidcCallback />} />
        <Route path="/access-denied" element={<AccessDeniedPage />} />
        <Route path="/invitations/accept" element={<InvitationAcceptPage />} />
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
          <Route path="/agents/panel" element={<AgentManagementPanelPage />} />
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
          <Route path="/system/system-one" element={<SystemOneProviderConfigPage />} />
          {/* Decision Tools live under the Agent module (round 2, task 6.8) */}
          <Route path="/agents/decision-tools" element={<DecisionToolsPage />} />
          <Route path="/chat/:agentTypeId?" element={<ChatPage />} />
          <Route path="/agents/:agentTypeId/chat/:sessionId" element={<ChatPage />} />
          <Route path="/api-keys" element={<ApiKeyListPage />} />
          <Route path="/permissions/access-requests" element={<AccessRequestsPage />} />
          <Route path="/user-permissions/*" element={<PermissionsPage />} />

          {/* Tenant workspace (multi-tenancy on; backend enforces membership) */}
          <Route path="/tenant/settings" element={<TenantSettingsPage />} />
          <Route path="/tenant/onboarding" element={<OnboardingPage />} />
          <Route path="/tenant/members" element={<MembersPage />} />

          {/* Platform admin console (multi-tenancy on + platform admin only) */}
          <Route
            path="/platform/*"
            element={
              <PlatformAdminRoute>
                <PlatformRoutes />
              </PlatformAdminRoute>
            }
          />
        </Route>

        {/* Catch-all */}
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  )
}
