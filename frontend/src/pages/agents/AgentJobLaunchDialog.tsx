import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
  IconButton,
  Tooltip,
} from '@mui/material'
import CodeIcon from '@mui/icons-material/Code'
import EditIcon from '@mui/icons-material/Edit'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { DynamicSchemaForm } from '../../components/DynamicSchemaForm'
import type { AgentJob, AgentType } from '../../types'

interface AgentJobLaunchDialogProps {
  open: boolean
  agentType: AgentType
  onClose: () => void
  onLaunched: (sessionId: string) => void
}

/**
 * Dialog for launching a new agent session.
 * Renders the appropriate input form based on the agent type's input_type:
 *   - "none"         → confirm only
 *   - "typed"        → JSON text input based on input_schema
 *   - "conversation" → initial message text area
 *
 * Follows the Dialog Error Handling Standard.
 */
export function AgentJobLaunchDialog({
  open,
  agentType,
  onClose,
  onLaunched,
}: AgentJobLaunchDialogProps) {
  const { t } = useTranslation()
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)
  const [inputText, setInputText] = useState('')
  const [typedInputData, setTypedInputData] = useState<Record<string, any>>({})
  const [useRawJson, setUseRawJson] = useState(false)

  useEffect(() => {
    if (open) {
      setInputText('')
      setTypedInputData({})
      setUseRawJson(false)
      setDialogError(null)
    }
  }, [open])

  const handleLaunch = async () => {
    try {
      setDialogError(null)
      setSubmitting(true)

      let inputData: Record<string, unknown> | null = null

      if (agentType.input_type === 'typed') {
        if (useRawJson) {
          try {
            inputData = inputText.trim() ? (JSON.parse(inputText) as Record<string, unknown>) : null
          } catch {
            throw new Error(t('agents.sessions.invalidJson'))
          }
        } else {
          inputData = Object.keys(typedInputData).length > 0 ? typedInputData : null
        }
      } else if (agentType.input_type === 'conversation') {
        inputData = { message: inputText }
      }

      const { data } = await apiClient.post<AgentJob>('/agents/sessions', {
        agent_type_id: agentType.id,
        input_data: inputData,
      })

      onLaunched(data.id)
    } catch (err) {
      setDialogError(err)
    } finally {
      setSubmitting(false)
    }
  }

  const schemaHint = agentType.input_schema
    ? JSON.stringify(agentType.input_schema, null, 2)
    : undefined

  return (
    <Dialog
      open={open}
      onClose={() => { onClose(); setDialogError(null) }}
      maxWidth="lg"
      fullWidth
    >
      <DialogTitle>
        {t('agents.sessions.launchTitle', { name: agentType.name })}
      </DialogTitle>

      <DialogContent dividers>
        {dialogError ? (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        ) : null}

        <Box display="flex" flexDirection="column" gap={2} pt={1}>
          {agentType.input_type === 'none' && (
            <Alert severity="info">{t('agents.sessions.confirmLaunch')}</Alert>
          )}

          {agentType.input_type === 'typed' && (
            <Box>
              <Box display="flex" alignItems="center" justifyContent="space-between" mb={1}>
                <Typography variant="body2" color="text.secondary">
                  {useRawJson
                    ? t('agents.sessions.typedInputHintRaw')
                    : t('agents.sessions.typedInputHint')}
                </Typography>
                <Tooltip title={useRawJson ? t('agents.sessions.useFormInput') : t('agents.sessions.useRawJson')}>
                  <IconButton size="small" onClick={() => setUseRawJson(!useRawJson)}>
                    {useRawJson ? <EditIcon fontSize="small" /> : <CodeIcon fontSize="small" />}
                  </IconButton>
                </Tooltip>
              </Box>

              {useRawJson ? (
                <Box>
                  {schemaHint && (
                    <Box
                      component="pre"
                      sx={{
                        bgcolor: 'grey.50',
                        border: 1,
                        borderColor: 'divider',
                        borderRadius: 1,
                        p: 1,
                        fontSize: 12,
                        overflow: 'auto',
                        mb: 1,
                      }}
                    >
                      {schemaHint}
                    </Box>
                  )}
                  <TextField
                    label={t('agents.sessions.inputData')}
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    fullWidth
                    multiline
                    rows={5}
                    placeholder='{"key": "value"}'
                    inputProps={{ style: { fontFamily: 'monospace', fontSize: 13 } }}
                  />
                </Box>
              ) : (
                <DynamicSchemaForm
                  schema={agentType.input_schema || ''}
                  value={typedInputData}
                  onChange={setTypedInputData}
                />
              )}
            </Box>
          )}

          {agentType.input_type === 'conversation' && (
            <TextField
              label={t('agents.sessions.initialMessage')}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              fullWidth
              multiline
              rows={4}
              placeholder={t('agents.sessions.initialMessagePlaceholder')}
            />
          )}
        </Box>
      </DialogContent>

      <DialogActions>
        <Button onClick={() => { onClose(); setDialogError(null) }} disabled={submitting}>
          {t('app.cancel')}
        </Button>
        <Button
          variant="contained"
          onClick={handleLaunch}
          disabled={
            submitting ||
            (agentType.input_type === 'conversation' && !inputText.trim())
          }
        >
          {submitting ? t('agents.sessions.launching') : t('agents.sessions.launch')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
