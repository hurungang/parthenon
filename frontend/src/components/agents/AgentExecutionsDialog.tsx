import { Dialog, DialogContent, DialogTitle, IconButton, Typography } from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { useTranslation } from 'react-i18next'
import { AgentInstanceDashboardPage } from '../../pages/agents/AgentInstanceDashboardPage'

interface AgentExecutionsDialogProps {
  open: boolean
  onClose: () => void
  agentTypeId?: string
  agentTypeName?: string
}

/**
 * Dialog wrapper for AgentInstanceDashboardPage.
 * Shows agent executions in a dialog context for easy back navigation.
 */
export function AgentExecutionsDialog({
  open,
  onClose,
  agentTypeId,
  agentTypeName,
}: AgentExecutionsDialogProps) {
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
          {agentTypeName
            ? `${t('agents.sessions.dashboardTitle')} — ${agentTypeName}`
            : t('agents.sessions.dashboardTitle')}
        </Typography>
        <IconButton edge="end" onClick={onClose} size="small">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        <AgentInstanceDashboardPage agentTypeId={agentTypeId} />
      </DialogContent>
    </Dialog>
  )
}
