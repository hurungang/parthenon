import { useState, useCallback, useRef } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
} from '@mui/material'

interface UseUnsavedChangesDialogReturn {
  hasUnsavedChanges: boolean
  markUnsaved: () => void
  markSaved: () => void
  handleClose: (closeFn: () => void) => void
  ConfirmationDialog: () => ReactNode
}

export function useUnsavedChangesDialog(): UseUnsavedChangesDialogReturn {
  const { t } = useTranslation()
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const pendingCloseRef = useRef<(() => void) | null>(null)

  const markUnsaved = useCallback(() => {
    setHasUnsavedChanges(true)
  }, [])

  const markSaved = useCallback(() => {
    setHasUnsavedChanges(false)
  }, [])

  const handleClose = useCallback(
    (closeFn: () => void) => {
      if (hasUnsavedChanges) {
        pendingCloseRef.current = closeFn
        setShowConfirm(true)
      } else {
        closeFn()
      }
    },
    [hasUnsavedChanges],
  )

  const handleDiscard = useCallback(() => {
    setShowConfirm(false)
    pendingCloseRef.current?.()
    pendingCloseRef.current = null
  }, [])

  const handleKeepEditing = useCallback(() => {
    setShowConfirm(false)
    pendingCloseRef.current = null
  }, [])

  function ConfirmationDialog() {
    return (
      <Dialog open={showConfirm} onClose={handleKeepEditing} maxWidth="xs" fullWidth>
        <DialogTitle>{t('permissions.roles.discardChangesTitle')}</DialogTitle>
        <DialogContent>
          <Typography>{t('permissions.roles.discardChangesMessage')}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleKeepEditing}>{t('permissions.roles.keepEditing')}</Button>
          <Button onClick={handleDiscard} color="error" variant="contained">
            {t('permissions.roles.discard')}
          </Button>
        </DialogActions>
      </Dialog>
    )
  }

  return {
    hasUnsavedChanges,
    markUnsaved,
    markSaved,
    handleClose,
    ConfirmationDialog,
  }
}
