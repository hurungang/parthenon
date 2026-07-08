import { useState } from 'react'
import {
  Alert,
  Box,
  CircularProgress,
  FormControlLabel,
  Paper,
  Snackbar,
  Switch,
  Tabs,
  Tab,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { IdentityProviderConfigForm } from '../../components/system/IdentityProviderConfigForm'
import { SuperAdminConfigSection } from '../../components/system/SuperAdminConfigSection'
import {
  getIdentityProviders,
  createIdentityProvider,
  updateIdentityProvider,
  getSuperAdminStatus,
} from '../../api/systemConfigApi'

export function IdentityProvidersConfigPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()

  const [activeTab, setActiveTab] = useState(0)
  const [sameAsUser, setSameAsUser] = useState(false)
  const [saveSuccessOpen, setSaveSuccessOpen] = useState(false)

  // Fetch identity providers
  const {
    data: providersData,
    isLoading: providersLoading,
  } = useQuery({
    queryKey: ['system', 'identity-providers'],
    queryFn: async () => {
      try {
        return await getIdentityProviders()
      } catch {
        // Public endpoint may fail; return empty list
        return { items: [], total: 0 }
      }
    },
  })

  // Fetch super admin status
  const { data: superAdminStatus, isLoading: superAdminLoading } = useQuery({
    queryKey: ['system', 'super-admin-status'],
    queryFn: async () => {
      try {
        return await getSuperAdminStatus()
      } catch {
        return null
      }
    },
  })

  const providers = providersData?.items ?? []
  const userProvider = providers.find((p) => p.provider_scope === 'user')
  const agentProvider = providers.find((p) => p.provider_scope === 'agent')
  const hasActiveOidcProvider = providers.some((p) => p.is_enabled)

  const handleSaveProvider = async (
    scope: 'user' | 'agent',
    data: {
      provider_type: string
      display_name: string
      issuer_url: string
      client_id: string
      client_secret?: string
      scopes: string
      claim_mappings?: Record<string, string>
      is_enabled: boolean
    },
  ) => {
    try {
      clearDialogError()
      const existing = scope === 'user' ? userProvider : agentProvider

      if (existing) {
        await updateIdentityProvider(scope, {
          ...data,
          client_secret: data.client_secret || null,
        })
      } else {
        await createIdentityProvider({
          provider_scope: scope,
          ...data,
          client_secret: data.client_secret || null,
        })
      }

      void queryClient.invalidateQueries({ queryKey: ['system', 'identity-providers'] })
      setSaveSuccessOpen(true)
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleSameAsUserToggle = (checked: boolean) => {
    setSameAsUser(checked)
  }

  if (providersLoading || superAdminLoading) {
    return (
      <Box textAlign="center" py={6}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={1}>
        {t('systemConfig.identityProvidersTitle')}
      </Typography>

      <Alert severity="info" sx={{ mb: 3 }}>
        <Typography variant="subtitle2" gutterBottom>
          {t('systemConfig.oidcSetup.title')}
        </Typography>
        <Typography variant="body2" component="div">
          <ul style={{ margin: '4px 0', paddingLeft: 20 }}>
            <li><strong>Root URL:</strong> {window.location.origin}</li>
            <li><strong>Home URL:</strong> {window.location.origin}/dashboard</li>
            <li><strong>Redirect URIs:</strong>
              <ul>
                <li>{window.location.origin}/callback — User OIDC login (PKCE)</li>
                <li>{window.location.origin}/* — Wildcard for dev environments</li>
              </ul>
            </li>
            <li><strong>Client setup (user identity):</strong> Register a <strong>public</strong> OIDC client in your provider for browser PKCE login (no secret). This is the <em>UI Client ID</em> field below — the only required client. A separate confidential API client is optional (platform does not enforce client-level access control).</li>
            <li><strong>Client setup (agent identity):</strong> Register a single client for the agent realm. This client is used for both the OAuth authorization flow and token exchange.</li>
          </ul>
        </Typography>
      </Alert>

      {dialogError ? (
        <Box mb={2}>
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        </Box>
      ) : null}

      <Tabs value={activeTab} onChange={(_, v) => setActiveTab(v)} sx={{ mb: 3 }}>
        <Tab label={t('systemConfig.tabs.userIdentityProvider')} />
        <Tab label={t('systemConfig.tabs.agentIdentityProvider')} />
        <Tab label={t('systemConfig.tabs.generalSettings')} />
      </Tabs>

      {/* All tabs rendered with display hiding to preserve form state */}
      <Box display={activeTab === 0 ? 'block' : 'none'}>
        <Paper sx={{ p: 3 }}>
          <IdentityProviderConfigForm
            scope="user"
            currentConfig={userProvider ?? null}
            onSave={async (data) => { await handleSaveProvider('user', data); }}
          />
        </Paper>
      </Box>

      <Box display={activeTab === 1 ? 'block' : 'none'}>
        <Paper sx={{ p: 3 }}>
          <Box mb={2}>
            <FormControlLabel
              control={
                <Switch
                  checked={sameAsUser}
                  onChange={(e) => handleSameAsUserToggle(e.target.checked)}
                />
              }
              label={t('systemConfig.identityProviders.sameAsUser')}
            />
            <Typography variant="caption" color="text.secondary" display="block">
              {t('systemConfig.identityProviders.sameAsUserHint')}
            </Typography>
          </Box>
          <IdentityProviderConfigForm
            scope="agent"
            currentConfig={agentProvider ?? null}
            onSave={async (data) => { await handleSaveProvider('agent', data); }}
            disabled={sameAsUser}
          />
        </Paper>
      </Box>

      <Box display={activeTab === 2 ? 'block' : 'none'}>
        <Paper sx={{ p: 3 }}>
          <SuperAdminConfigSection
            status={superAdminStatus ?? null}
            hasActiveOidcProvider={hasActiveOidcProvider}
          />
        </Paper>
      </Box>

      <Snackbar
        open={saveSuccessOpen}
        autoHideDuration={3000}
        onClose={() => setSaveSuccessOpen(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          onClose={() => setSaveSuccessOpen(false)}
          severity="success"
          variant="filled"
          sx={{ width: '100%' }}
        >
          {t('systemConfig.identityProviders.saveSuccess')}
        </Alert>
      </Snackbar>
    </Box>
  )
}
