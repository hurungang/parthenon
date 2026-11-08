import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Tooltip,
  Typography,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CloseIcon from '@mui/icons-material/Close'
import { ContentRenderer } from '../ContentRenderer'
import type { InterventionType } from '../../types'

export interface ResolvedInterventionData {
  /** Stable key for list rendering. */
  id: string
  interventionType: InterventionType
  /** The original intervention question (markdown reason, choices appended
   * for choice-type requests). */
  reason: string
  choices?: string[] | null
  agentType?: string | null
  /** Human-readable answer summary, e.g. "Approved", the selected choice, or
   * the free-text answer. */
  answer: string | null
  resolvedAt: string
}

interface ResolvedInterventionBubbleProps {
  data: ResolvedInterventionData
}

/**
 * Bubble rendered in the chat timeline AFTER a human intervention has been
 * actioned. Shows the confirmation (the answer provided) with a button that
 * re-opens the original intervention request in a VIEW-ONLY dialog — the
 * action is already submitted, so no approve/deny controls are offered.
 *
 * Used both for live resolutions (the operator just responded) and for
 * persisted history (intervene_request/intervene_response turn pairs loaded
 * on session resume).
 */
export function ResolvedInterventionBubble({ data }: ResolvedInterventionBubbleProps) {
  const { t } = useTranslation()
  const [viewOpen, setViewOpen] = useState(false)

  return (
    <Box
      display="flex"
      flexDirection="row"
      alignItems="flex-start"
      gap={1}
      mb={2}
      data-testid="resolved-intervention-bubble"
    >
      <Paper
        variant="outlined"
        sx={{
          borderLeft: 3,
          borderColor: 'success.main',
          borderRadius: 1.5,
          bgcolor: 'success.light',
          px: 1.5,
          py: 0.75,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          flexWrap: 'wrap',
          maxWidth: '100%',
        }}
      >
        <CheckCircleIcon sx={{ color: 'success.dark', fontSize: 18 }} />
        <Typography variant="caption" color="text.secondary" component="span">
          {t('conversations.sessions.intervention.resolvedLabel')}
        </Typography>
        <Typography
          variant="caption"
          fontWeight={700}
          component="span"
          sx={{ whiteSpace: 'pre-wrap', maxWidth: 340, overflowWrap: 'anywhere' }}
        >
          {data.answer ?? t('conversations.sessions.intervention.responseSubmittedFallback')}
        </Typography>
        <Button
          size="small"
          variant="text"
          sx={{ ml: 'auto', fontSize: '0.7rem', py: 0, minWidth: 0 }}
          onClick={() => setViewOpen(true)}
        >
          {t('conversations.sessions.intervention.viewRequest')}
        </Button>
        <Tooltip title={new Date(data.resolvedAt).toLocaleString()}>
          <Typography
            color="text.secondary"
            component="span"
            sx={{ fontSize: '0.6rem', whiteSpace: 'nowrap' }}
          >
            {new Date(data.resolvedAt).toLocaleTimeString()}
          </Typography>
        </Tooltip>
      </Paper>

      {/* View-only dialog — the intervention is already actioned, so this is
          strictly a record of what was asked and what was answered. */}
      <Dialog
        open={viewOpen}
        onClose={() => setViewOpen(false)}
        fullWidth
        maxWidth="md"
        data-testid="resolved-intervention-view"
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, pr: 1 }}>
          <CheckCircleIcon sx={{ color: 'success.dark' }} />
          <Box flex={1}>
            {t('conversations.sessions.intervention.viewRequestTitle', {
              agentType: data.agentType ?? 'Agent',
            })}
          </Box>
          <IconButton
            size="small"
            aria-label={t('app.close')}
            onClick={() => setViewOpen(false)}
          >
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers>
          <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
            {t('conversations.sessions.intervention.requestLabel')}
          </Typography>
          <Box sx={{ overflowX: 'auto', mb: 2, '& table': { width: '100%' } }}>
            <ContentRenderer content={data.reason} />
          </Box>
          {data.choices && data.choices.length > 0 && (
            <Box mb={2}>
              <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
                {t('conversations.sessions.intervention.optionsLabel')}
              </Typography>
              {data.choices.map((choice) => (
                <Typography
                  key={choice}
                  variant="body2"
                  sx={{
                    py: 0.25,
                    fontWeight: choice === data.answer ? 700 : 400,
                    color: choice === data.answer ? 'success.dark' : 'text.primary',
                  }}
                >
                  {choice === data.answer ? `✓ ${choice}` : `• ${choice}`}
                </Typography>
              ))}
            </Box>
          )}
          <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
            {t('conversations.sessions.intervention.yourAnswer')}
          </Typography>
          <Box sx={{ p: 1.5, bgcolor: 'success.light', borderRadius: 1 }}>
            <Typography variant="body2" fontWeight={500} sx={{ whiteSpace: 'pre-wrap' }}>
              {data.answer ?? t('conversations.sessions.intervention.responseSubmittedFallback')}
            </Typography>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button variant="contained" onClick={() => setViewOpen(false)}>
            {t('app.close')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
