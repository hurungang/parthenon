import { Chip } from '@mui/material'
import { useTranslation } from 'react-i18next'
import {
  RESUME_STATE_CHIP_COLORS,
  RESUME_STATE_LABEL_KEYS,
  type ResumeState,
} from '../../utils/resumeState'

interface ResumeStateChipProps {
  state: ResumeState
  testId?: string
  size?: 'small' | 'medium'
}

/**
 * The single resume-state vocabulary used by the conversation dialog: waiting
 * for your input / resumed · continuing / resolved / no longer resumable.
 * Colours mirror the approved prototype.
 */
export function ResumeStateChip({ state, testId, size = 'small' }: ResumeStateChipProps) {
  const { t } = useTranslation()
  return (
    <Chip
      data-testid={testId}
      data-resume-state={state}
      label={t(RESUME_STATE_LABEL_KEYS[state])}
      color={RESUME_STATE_CHIP_COLORS[state]}
      size={size}
      variant="outlined"
      sx={{ fontWeight: 600 }}
    />
  )
}
