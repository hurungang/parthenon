import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Alert, Button, Snackbar } from '@mui/material'
import {
  PERMISSION_DENIED_EVENT,
  type PermissionDeniedDetail,
  type RequiredPermission,
} from '../../utils/permissionError'
import { RequestPermissionModal } from './RequestPermissionModal'

/**
 * Global snackbar that displays structured 403 "permission denied" messages.
 *
 * Mount once in AppShell.  Listens for the `parthenon:permissionDenied` custom
 * event dispatched by the API client interceptor and shows a targeted message
 * with a "Request Access" action button.
 */
export function PermissionErrorSnackbar() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState('')
  const [permissionContext, setPermissionContext] = useState<RequiredPermission | null>(null)
  const [modalOpen, setModalOpen] = useState(false)

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
      setPermissionContext(detail.required_permission)
      setOpen(true)
    }

    window.addEventListener(PERMISSION_DENIED_EVENT, handler)
    return () => window.removeEventListener(PERMISSION_DENIED_EVENT, handler)
  }, [t])

  const handleRequestAccess = () => {
    setOpen(false)
    setModalOpen(true)
  }

  return (
    <>
      <Snackbar
        open={open}
        autoHideDuration={6000}
        onClose={() => setOpen(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          severity="error"
          onClose={() => setOpen(false)}
          sx={{ width: '100%' }}
          action={
            <Button color="inherit" size="small" onClick={handleRequestAccess}>
              {t('permissions.errors.requestAccessButton')}
            </Button>
          }
        >
          {message}
        </Alert>
      </Snackbar>
      <RequestPermissionModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        permissionContext={permissionContext}
      />
    </>
  )
}

