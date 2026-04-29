import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Card,
  CardContent,
  Divider,
  Stack,
  Typography,
} from '@mui/material'
import LockOutlinedIcon from '@mui/icons-material/LockOutlined'
import type { RequiredPermission } from '../utils/permissionError'
import { RequestPermissionModal } from '../components/permissions/RequestPermissionModal'

/**
 * Full-page access denied view rendered at `/access-denied`.
 *
 * Permission context is read from `useLocation().state` (a `RequiredPermission`
 * object placed in router state by the 403 handler).
 */
export function AccessDeniedPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const permissionContext = (location.state as RequiredPermission | null) ?? null

  const [modalOpen, setModalOpen] = useState(false)

  return (
    <Box
      display="flex"
      alignItems="center"
      justifyContent="center"
      minHeight="100vh"
      bgcolor="background.default"
      p={2}
    >
      <Card sx={{ maxWidth: 480, width: '100%' }}>
        <CardContent>
          <Stack spacing={2} alignItems="center" textAlign="center">
            <LockOutlinedIcon sx={{ fontSize: 56, color: 'error.main' }} />
            <Typography variant="h5" fontWeight="bold">
              {t('permissions.errors.accessDeniedTitle')}
            </Typography>
            <Typography variant="body1" color="text.secondary">
              {t('permissions.errors.accessDeniedMessage')}
            </Typography>
          </Stack>

          {permissionContext && (
            <>
              <Divider sx={{ my: 2 }} />
              <Stack spacing={1}>
                <Stack direction="row" justifyContent="space-between">
                  <Typography variant="body2" color="text.secondary">
                    {t('permissions.errors.resourceType')}
                  </Typography>
                  <Typography variant="body2" fontWeight="medium">
                    {permissionContext.resource_type}
                  </Typography>
                </Stack>
                <Stack direction="row" justifyContent="space-between">
                  <Typography variant="body2" color="text.secondary">
                    {t('permissions.errors.action')}
                  </Typography>
                  <Typography variant="body2" fontWeight="medium">
                    {permissionContext.action}
                  </Typography>
                </Stack>
                <Stack direction="row" justifyContent="space-between">
                  <Typography variant="body2" color="text.secondary">
                    {t('permissions.errors.resourceId')}
                  </Typography>
                  <Typography variant="body2" fontWeight="medium">
                    {permissionContext.resource_id ?? '*'}
                  </Typography>
                </Stack>
              </Stack>
            </>
          )}

          <Stack direction="row" spacing={2} justifyContent="center" mt={3}>
            <Button variant="outlined" onClick={() => navigate('/')}>
              {t('permissions.errors.returnToDashboard')}
            </Button>
            <Button variant="contained" onClick={() => setModalOpen(true)}>
              {t('permissions.errors.requestAccessButton')}
            </Button>
          </Stack>
        </CardContent>
      </Card>

      <RequestPermissionModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        permissionContext={permissionContext}
      />
    </Box>
  )
}
