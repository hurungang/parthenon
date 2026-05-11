import { Dialog, DialogContent, DialogTitle, IconButton, Typography } from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { useTranslation } from 'react-i18next'
import { AgentJobPage } from '../../pages/agents/AgentJobPage'

interface AgentExecutionDetailsDialogProps {
  open: boolean
  onClose: () => void
  sessionId: string
}

/**
 * Dialog wrapper for AgentJobPage.
 * Shows execution details and logs in a dialog context for easy back navigation.
 */
export function AgentExecutionDetailsDialog({
  open,
  onClose,
  sessionId,
}: AgentExecutionDetailsDialogProps) {
  const { t } = useTranslation()

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="xl"
      fullWidth
      PaperProps={{ sx: { width: { xs: '100%', sm: '90%', lg: '95%' } } }}
    >
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography variant="h6" component="span">
          {t('agents.sessions.detailsTitle')}
        </Typography>
        <IconButton edge="end" onClick={onClose} size="small">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        <AgentJobPage sessionId={sessionId} />
      </DialogContent>
    </Dialog>
  )
}
