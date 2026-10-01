/**
 * PlatformAdminRoute — guard for the /platform/* console.
 *
 * Renders children only when:
 * - multi-tenancy is ON (otherwise the console does not exist and the
 *   user is redirected to the dashboard), and
 * - the authenticated caller holds platform-admin rights, probed via a
 *   cheap platform API read; anyone else gets the standard access-denied
 *   experience.
 */
import { type ReactNode, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { isAxiosError } from 'axios'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Box, Button, Card, CardContent, Typography } from '@mui/material'
import LockOutlinedIcon from '@mui/icons-material/LockOutlined'
import { useAuthStore } from '../stores/authStore'
import { getPlatformSettings } from '../api/platformAdminApi'

interface PlatformAdminRouteProps {
  children: ReactNode
}

export function PlatformAdminRoute({ children }: PlatformAdminRouteProps) {
  const { t } = useTranslation()
  const { isAuthenticated, isLoading, isSuperAdmin, multiTenancyEnabled } = useAuthStore()
  const [probeDenied, setProbeDenied] = useState(false)

  // Probe a platform endpoint: 200 = platform admin; 403 = denied.
  const probe = useQuery({
    queryKey: ['platform', 'access-probe'],
    enabled: isAuthenticated && multiTenancyEnabled === true && !isSuperAdmin,
    retry: false,
    staleTime: 60_000,
    queryFn: async () => {
      try {
        return await getPlatformSettings()
      } catch (err) {
        if (isAxiosError(err) && err.response?.status === 403) {
          setProbeDenied(true)
        }
        throw err
      }
    },
  })

  if (isLoading) return null

  if (!isAuthenticated) return <Navigate to="/login" replace />

  // Discovery still resolving: wait — do NOT treat "unknown" as "off",
  // or a platform admin deep-linking / refreshing /platform/* would be
  // bounced to the dashboard before the switch state arrives.
  if (multiTenancyEnabled === null) return null

  // Routes absent entirely when multi-tenancy is off (resolved false).
  if (multiTenancyEnabled === false) return <Navigate to="/dashboard" replace />

  // Super admin is the bootstrap platform administrator.
  if (isSuperAdmin) return <>{children}</>

  if (probeDenied) {
    return (
      <Box display="flex" justifyContent="center" mt={8} p={2}>
        <Card sx={{ maxWidth: 480, width: '100%' }}>
          <CardContent sx={{ textAlign: 'center' }}>
            <LockOutlinedIcon color="error" sx={{ fontSize: 48, mb: 1 }} />
            <Typography variant="h6" gutterBottom>
              {t('platform.accessDenied.title')}
            </Typography>
            <Typography variant="body2" color="text.secondary" mb={2}>
              {t('platform.accessDenied.message')}
            </Typography>
            <Button variant="contained" href="/dashboard">
              {t('platform.accessDenied.back')}
            </Button>
          </CardContent>
        </Card>
      </Box>
    )
  }

  if (probe.isLoading || probe.isFetching) {
    return (
      <Box display="flex" justifyContent="center" mt={8}>
        <Typography color="text.secondary">{t('app.loading')}</Typography>
      </Box>
    )
  }

  if (probe.isError) {
    // Non-403 errors (network etc.) still block the console defensively.
    return (
      <Box display="flex" justifyContent="center" mt={8} p={2}>
        <Card sx={{ maxWidth: 480, width: '100%' }}>
          <CardContent sx={{ textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              {t('platform.accessDenied.message')}
            </Typography>
          </CardContent>
        </Card>
      </Box>
    )
  }

  return <>{children}</>
}
