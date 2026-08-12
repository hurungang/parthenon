import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
} from '@mui/material'
import { useTranslation } from 'react-i18next'

interface ConfirmDialogProps {
  open: boolean
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  confirmColor?: 'primary' | 'error' | 'warning'
  onConfirm: () => void
  onCancel: () => void
}

/**
 * Reusable confirmation dialog for destructive or important actions.
 *
 * Usage:
 *   <ConfirmDialog
 *     open={confirmOpen}
 *     title="Delete Item"
 *     message="Are you sure you want to delete this item?"
 *     confirmColor="error"
 *     onConfirm={handleConfirmDelete}
 *     onCancel={() => setConfirmOpen(false)}
 *   />
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmText,
  cancelText,
  confirmColor = 'primary',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const { t } = useTranslation()

  return (
    <Dialog open={open} onClose={onCancel} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <DialogContentText>{message}</DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel} color="inherit">
          {cancelText || t('app.cancel')}
        </Button>
        <Button onClick={onConfirm} color={confirmColor} variant="contained" autoFocus>
          {confirmText || t('app.confirm')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
