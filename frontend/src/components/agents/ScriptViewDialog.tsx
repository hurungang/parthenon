import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Typography,
} from '@mui/material'

// ── Types ──────────────────────────────────────────────────────────────────────

export interface ScriptViewData {
  name?: string | null
  description?: string | null
  version_label?: string | null
  python_source?: string | null
}

interface ScriptViewDialogProps {
  open: boolean
  script: ScriptViewData | null
  onClose: () => void
}

// ── Component ──────────────────────────────────────────────────────────────────

/**
 * Reusable read-only script viewer dialog: shows a script's python_source,
 * description and version. Used directly from the Optimized Plan tab's
 * per-step "View script" links (the standalone Scripts tab was removed).
 */
export function ScriptViewDialog({ open, script, onClose }: ScriptViewDialogProps) {
  const { t } = useTranslation()
  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        {t('agents.scripts.scriptViewer.title', {
          label: script?.version_label ?? script?.name ?? '',
        })}
      </DialogTitle>
      <DialogContent dividers>
        {script ? (
          <>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              {script.name && (
                <Chip label={script.name} size="small" variant="outlined" />
              )}
              {script.version_label && (
                <Chip
                  label={t('agents.scripts.columnCurrentVersion') + ': ' + script.version_label}
                  size="small"
                  color="success"
                  variant="outlined"
                />
              )}
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              {script.description ?? '—'}
            </Typography>
            <Box
              component="pre"
              data-testid="script-view-source"
              sx={{
                m: 0,
                p: 1.5,
                borderRadius: 1,
                bgcolor: 'action.hover',
                fontSize: 12,
                overflow: 'auto',
                maxHeight: 420,
                fontFamily: 'monospace',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {script.python_source ?? ''}
            </Box>
          </>
        ) : null}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('agents.scripts.scriptViewer.close')}</Button>
      </DialogActions>
    </Dialog>
  )
}
