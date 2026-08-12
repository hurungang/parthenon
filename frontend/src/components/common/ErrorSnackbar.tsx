import { Alert, Button, IconButton, Snackbar } from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'

interface ErrorSnackbarProps {
  open: boolean
  message: string
  onClose: () => void
  severity?: 'error' | 'warning' | 'info' | 'success'
  autoHideDuration?: number
  actionLabel?: string
  onAction?: () => void
}

/**
 * Reusable snackbar for displaying error, warning, info, or success messages.
 *
 * Usage:
 *   const [errorMsg, setErrorMsg] = useState('')
 *   <ErrorSnackbar
 *     open={!!errorMsg}
 *     message={errorMsg}
 *     severity="error"
 *     onClose={() => setErrorMsg('')}
 *     actionLabel="View Details"
 *     onAction={() => navigate('/details')}
 *   />
 */
export function ErrorSnackbar({
  open,
  message,
  onClose,
  severity = 'error',
  autoHideDuration = 6000,
  actionLabel,
  onAction,
}: ErrorSnackbarProps) {
  return (
    <Snackbar
      open={open}
      autoHideDuration={autoHideDuration}
      onClose={onClose}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
    >
      <Alert
        severity={severity}
        onClose={actionLabel && onAction ? undefined : onClose}
        sx={{ width: '100%' }}
        action={
          actionLabel && onAction ? (
            <>
              <Button 
                variant="contained"
                size="small" 
                onClick={onAction}
                sx={{ 
                  whiteSpace: 'nowrap',
                  bgcolor: 'background.paper',
                  color: 'text.primary',
                  '&:hover': {
                    bgcolor: 'action.hover',
                  },
                }}
              >
                {actionLabel}
              </Button>
              <IconButton
                size="small"
                aria-label="close"
                color="inherit"
                onClick={onClose}
              >
                <CloseIcon fontSize="small" />
              </IconButton>
            </>
          ) : undefined
        }
      >
        {message}
      </Alert>
    </Snackbar>
  )
}
