import { useTranslation } from 'react-i18next'
import { Alert, Box, Button, Chip, Typography } from '@mui/material'
import DiscardIcon from '@mui/icons-material/Undo'
import SaveIcon from '@mui/icons-material/Save'
import PermissionDeniedAlert from '../../permissions/PermissionDeniedAlert'
import { extractBindingValidationErrors } from '../../../utils/errorUtils'
import type { AgentEquipmentSlotId } from '../../../types'

interface PendingChangesTrayProps {
  /** True when the draft differs from the last saved snapshot. */
  dirty: boolean
  /** Slot ids changed in the draft (mapped to localized labels). */
  changedSlotIds: AgentEquipmentSlotId[]
  /** True when a base property (name/description/instruction/guardrails) changed. */
  propertiesChanged?: boolean
  saving: boolean
  /** Optional extra disable for Save (e.g. draft name fails slug validation). */
  saveDisabled?: boolean
  /** Save failure rendered inside the tray area (Dialog/region error standard). */
  saveError: unknown
  onSave: () => void
  onDiscard: () => void
}

/**
 * Dirty-state summary bar of the Agent Management Panel: lists pending draft
 * changes (equipment slots plus the base-properties section) and offers Save
 * (single agent-type PUT) and Discard (revert to snapshot). Inert while the
 * draft is pristine; save errors are surfaced through PermissionDeniedAlert
 * instead of failing silently.
 */
export function PendingChangesTray({
  dirty,
  changedSlotIds,
  propertiesChanged = false,
  saving,
  saveDisabled = false,
  saveError,
  onSave,
  onDiscard,
}: PendingChangesTrayProps) {
  const { t } = useTranslation()

  const changedCount = changedSlotIds.length + (propertiesChanged ? 1 : 0)

  // Structured binding-validation failures (backend 422 detail) render every
  // specific error (which role/skill/SOP + which rule failed); anything else
  // falls back to the generic error alert.
  const bindingErrors = extractBindingValidationErrors(saveError)

  return (
    <Box sx={{ borderTop: 1, borderColor: 'divider', pt: 1.5, mt: 'auto' }}>
      {saveError != null && bindingErrors && (
        <Alert severity="error" sx={{ mb: 2 }}>
          <Typography variant="body2" fontWeight={600}>
            {t('agents.panel.bindingValidationFailed')}
          </Typography>
          <Box component="ul" sx={{ m: 0.5, pl: 2.5 }}>
            {bindingErrors.map((message, index) => (
              <Typography key={index} component="li" variant="caption" sx={{ display: 'list-item' }}>
                {message}
              </Typography>
            ))}
          </Box>
        </Alert>
      )}
      {saveError != null && !bindingErrors && (
        <PermissionDeniedAlert error={saveError} fallbackMessage={t('app.error')} />
      )}
      <Box display="flex" alignItems="center" justifyContent="space-between" gap={1}>
        <Typography variant="caption" color="text.secondary">
          {dirty
            ? t('agents.panel.pendingChanges', { count: changedCount })
            : t('agents.panel.pendingChanges', { count: 0 })}
        </Typography>
        <Chip
          label={dirty ? t('agents.panel.unsavedChip') : t('agents.panel.savedChip')}
          size="small"
          color={dirty ? 'warning' : 'success'}
          variant="outlined"
        />
      </Box>
      {dirty && (
        <Box display="flex" gap={0.5} flexWrap="wrap" sx={{ mt: 0.5 }}>
          {propertiesChanged && (
            <Chip
              label={t('agents.panel.properties.label')}
              size="small"
              variant="outlined"
              sx={{ fontSize: 10, height: 20 }}
            />
          )}
          {changedSlotIds.map((slotId) => (
            <Chip
              key={slotId}
              label={t(`agents.panel.slots.${slotId}.label`)}
              size="small"
              variant="outlined"
              sx={{ fontSize: 10, height: 20 }}
            />
          ))}
        </Box>
      )}
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
        {t('agents.panel.pendingHint')}
      </Typography>
      <Box display="flex" gap={1} justifyContent="flex-end" sx={{ mt: 1 }}>
        <Button
          size="small"
          startIcon={<DiscardIcon />}
          onClick={onDiscard}
          disabled={!dirty || saving}
        >
          {t('agents.panel.discard')}
        </Button>
        <Button
          size="small"
          variant="contained"
          startIcon={<SaveIcon />}
          onClick={onSave}
          disabled={!dirty || saving || saveDisabled}
        >
          {t('agents.panel.save')}
        </Button>
      </Box>
    </Box>
  )
}
