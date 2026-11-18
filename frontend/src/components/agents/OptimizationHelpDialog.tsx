import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
} from '@mui/material'

export interface OptimizationHelpDialogProps {
  open: boolean
  onClose: () => void
}

/**
 * Short "what is optimization / how do I use it" help, opened from the
 * question-mark icon in the Optimized Plan tab. Replaces the old pre-start
 * confirmation dialog: the run itself starts from the chat, not from a wall of
 * explanatory text.
 */
export function OptimizationHelpDialog({
  open,
  onClose,
}: OptimizationHelpDialogProps) {
  const { t } = useTranslation()

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      data-testid="optimization-help-dialog"
    >
      <DialogTitle>
        {t('agents.optimizedPlan.helpTitle', {
          defaultValue: 'About optimization',
        })}
      </DialogTitle>
      <DialogContent dividers>
        <Typography variant="body2" sx={{ mb: 1.5 }}>
          {t('agents.optimizedPlan.helpIntro', {
            defaultValue:
              'Optimization improves how this agent does its work: it authors and verifies an optimized implementation plan and scripts.',
          })}
        </Typography>
        <Box component="ul" sx={{ pl: 2.5, m: 0 }}>
          <Typography component="li" variant="body2" sx={{ mb: 1 }}>
            {t('agents.optimizedPlan.helpIdentity', {
              defaultValue:
                'It runs as this agent — same identity, role and permissions.',
            })}
          </Typography>
          <Typography component="li" variant="body2" sx={{ mb: 1 }}>
            {t('agents.optimizedPlan.helpVerification', {
              defaultValue:
                'Verification replays a real execution. A live test only runs after you approve it, and it runs once.',
            })}
          </Typography>
          <Typography component="li" variant="body2" sx={{ mb: 1 }}>
            {t('agents.optimizedPlan.helpInteraction', {
              defaultValue:
                'Chat with the optimizer to steer it. If it needs a decision or cannot verify something, it will ask you and stop rather than loop.',
            })}
          </Typography>
          <Typography component="li" variant="body2">
            {t('agents.optimizedPlan.helpModel', {
              defaultValue:
                'The model shown on the tab is the one the optimizer will use.',
            })}
          </Typography>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} data-testid="optimization-help-close">
          {t('app.done', { defaultValue: 'Done' })}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default OptimizationHelpDialog
