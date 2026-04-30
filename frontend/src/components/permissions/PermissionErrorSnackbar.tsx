import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Alert, Snackbar } from '@mui/material'
import {
  PERMISSION_DENIED_EVENT,
  type PermissionDeniedDetail,
} from '../../utils/permissionError'

/**
 * Global snackbar that displays structured 403 "permission denied" messages.
 *
 * Mount once in AppShell.  Listens for the `parthenon:permissionDenied` custom
 * event dispatched by the API client interceptor and shows a targeted message.
 */
export function PermissionErrorSnackbar() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<PermissionDeniedDetail>).detail
      const { resource_type, action, resource_id } = detail.required_permission
      const msg = t('permissions.errors.missingPermission', {
        resource_type,
        action,
        resource_id: resource_id ?? '*',
      })
      setMessage(msg)
      setOpen(true)
    }

    window.addEventListener(PERMISSION_DENIED_EVENT, handler)
    return () => window.removeEventListener(PERMISSION_DENIED_EVENT, handler)
  }, [t])

  return (
    <Snackbar
      open={open}
      autoHideDuration={6000}
      onClose={() => setOpen(false)}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
    >
      <Alert severity="error" onClose={() => setOpen(false)} sx={{ width: '100%' }}>
        {message}
      </Alert>
    </Snackbar>
  )
}
