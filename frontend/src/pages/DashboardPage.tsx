import { Box, CircularProgress, Grid, Paper, Typography, Button, Chip } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getIdentityProviders, getSuperAdminStatus } from '../api/systemConfigApi'

export function DashboardPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const { data: providersData, isLoading: providersLoading } = useQuery({
    queryKey: ['system', 'identity-providers'],
    queryFn: async () => {
      try {
        return await getIdentityProviders()
      } catch {
        return { items: [], total: 0 }
      }
    },
  })

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

  const isLoading = providersLoading || superAdminLoading

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>
        {t('nav.dashboard')}
      </Typography>
      <Typography variant="body1" color="text.secondary" mb={3}>
        {t('app.tagline')}
      </Typography>

      {isLoading ? (
        <Box textAlign="center" py={3}>
          <CircularProgress size={24} />
        </Box>
      ) : (
        <>
          {/* Identity Provider Status Cards */}
          <Grid container spacing={2} mb={3}>
            {[
              {
                label: t('systemConfig.dashboard.userProviderCard'),
                configured: !!userProvider?.is_enabled,
                providerName: userProvider?.provider_type ?? null,
              },
              {
                label: t('systemConfig.dashboard.agentProviderCard'),
                configured: !!agentProvider?.is_enabled,
                providerName: agentProvider?.provider_type ?? null,
              },
              {
                label: t('systemConfig.dashboard.superAdminCard'),
                configured: superAdminStatus?.is_enabled ?? false,
                providerName: 'super_admin',
              },
            ].map((card) => (
              <Grid key={card.label} >
                <Paper
                  sx={{
                    p: 2,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1.5,
                    minWidth: 260,
                  }}
                >
                  <Box
                    sx={{
                      width: 12,
                      height: 12,
                      borderRadius: '50%',
                      bgcolor: card.configured ? 'success.main' : 'grey.400',
                      flexShrink: 0,
                    }}
                  />
                  <Box>
                    <Typography variant="body2" fontWeight={500}>
                      {card.label}
                    </Typography>
                    <Chip
                      size="small"
                      label={
                        card.configured
                          ? card.providerName === 'super_admin'
                            ? t('systemConfig.dashboard.enabled')
                            : t('systemConfig.dashboard.configured')
                          : card.providerName === 'super_admin'
                            ? t('systemConfig.dashboard.disabled')
                            : t('systemConfig.dashboard.notConfigured')
                      }
                      color={card.configured ? 'success' : 'default'}
                      variant="outlined"
                    />
                  </Box>
                </Paper>
              </Grid>
            ))}
          </Grid>

          {/* Quick actions */}
          <Box display="flex" gap={1} flexWrap="wrap">
            <Button
              variant="outlined"
              size="small"
              onClick={() => navigate('/system/identity-providers')}
            >
              {t('systemConfig.dashboard.configureIdentityProviders')}
            </Button>
          </Box>
        </>
      )}
    </Box>
  )
}
