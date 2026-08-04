import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  MenuItem,
  Alert,
  Box,
  Typography,
  FormControl,
  InputLabel,
  Select,
  IconButton,
  Tooltip,
} from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import VisibilityIcon from '@mui/icons-material/Visibility'
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import { useCreateApiKey, useIdentitiesWithRoles } from '../../hooks/useApiKeys'
import type { ApiKeyCreateResponse } from '../../types/apiKeys'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'

interface CreateApiKeyDialogProps {
  open: boolean
  onClose: () => void
  onCreated: () => void
}

export function CreateApiKeyDialog({ open, onClose, onCreated }: CreateApiKeyDialogProps) {
  const { t } = useTranslation()
  const [step, setStep] = useState<1 | 2>(1)
  const [name, setName] = useState('')
  const [identityId, setIdentityId] = useState('')
  const [roleId, setRoleId] = useState('')
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [createdKey, setCreatedKey] = useState<ApiKeyCreateResponse | null>(null)
  const [keyRevealed, setKeyRevealed] = useState(false)
  const [copied, setCopied] = useState(false)

  const { data: identitiesWithRoles } = useIdentitiesWithRoles()
  const createMutation = useCreateApiKey()

  const selectedIdentity = identitiesWithRoles?.find((i) => i.identity_id === identityId)
  const availableRoles = selectedIdentity?.roles ?? []

  const formValid = name.trim().length > 0 && !!identityId && !!roleId

  const resetForm = () => {
    setStep(1)
    setName('')
    setIdentityId('')
    setRoleId('')
    setDialogError(null)
    setCreatedKey(null)
    setKeyRevealed(false)
    setCopied(false)
  }

  useEffect(() => {
    if (open) {
      resetForm()
    }
  }, [open])

  // Reset role when identity changes
  useEffect(() => {
    if (roleId && !availableRoles.find((r) => r.role_id === roleId)) {
      setRoleId('')
    }
  }, [identityId])

  const handleCreate = async () => {
    if (!formValid) return
    setDialogError(null)
    try {
      const result = await createMutation.mutateAsync({
        name: name.trim(),
        agent_identity_id: identityId,
        agent_role_id: roleId,
      })
      setCreatedKey(result)
      setStep(2)
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleCopyKey = async () => {
    if (!createdKey?.api_key) return
    try {
      await navigator.clipboard.writeText(createdKey.api_key)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback for older browsers
      const ta = document.createElement('textarea')
      ta.value = createdKey.api_key
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleDone = () => {
    onCreated()
  }

  return (
    <Dialog
      open={open}
      onClose={() => { onClose(); setDialogError(null) }}
      maxWidth="sm"
      fullWidth
    >
      {step === 1 && (
        <>
          <DialogTitle>{t('apiKeys.createTitle')}</DialogTitle>
          <DialogContent>
            {dialogError ? (
              <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
            ) : null}

            <Box display="flex" flexDirection="column" gap={2} mt={dialogError ? 1 : 0}>
              <TextField
                label={t('apiKeys.keyName')}
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                fullWidth
                placeholder={t('apiKeys.keyNamePlaceholder')}
                inputProps={{ maxLength: 128 }}
                helperText={`${name.length}/128`}
              />

              <FormControl fullWidth required>
                <InputLabel>{t('apiKeys.agentIdentity')}</InputLabel>
                <Select
                  value={identityId}
                  label={t('apiKeys.agentIdentity')}
                  onChange={(e) => setIdentityId(e.target.value)}
                >
                  {identitiesWithRoles?.map((item) => (
                    <MenuItem key={item.identity_id} value={item.identity_id}>
                      {item.identity_name}
                    </MenuItem>
                  )) ?? []}
                </Select>
              </FormControl>

              <FormControl fullWidth required disabled={!identityId}>
                <InputLabel>{t('apiKeys.agentRole')}</InputLabel>
                <Select
                  value={roleId}
                  label={t('apiKeys.agentRole')}
                  onChange={(e) => setRoleId(e.target.value)}
                >
                  {availableRoles.map((role) => (
                    <MenuItem key={role.role_id} value={role.role_id}>
                      {role.role_name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>

              <Alert severity="info" variant="outlined">
                {t('apiKeys.scopingInfo')}
              </Alert>
            </Box>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => { onClose(); setDialogError(null) }}>
              {t('app.cancel')}
            </Button>
            <Button
              variant="contained"
              onClick={handleCreate}
              disabled={!formValid || createMutation.isPending}
            >
              {createMutation.isPending ? t('app.saving') : t('apiKeys.createKey')}
            </Button>
          </DialogActions>
        </>
      )}

      {step === 2 && createdKey && (
        <>
          <DialogTitle>
            <Box display="flex" alignItems="center" gap={1}>
              <CheckCircleOutlineIcon color="success" />
              {t('apiKeys.createdTitle')}
            </Box>
          </DialogTitle>
          <DialogContent>
            <Alert severity="warning" sx={{ mb: 2 }}>
              {t('apiKeys.saveKeyWarning')}
            </Alert>

            <Box
              sx={{
                bgcolor: 'grey.900',
                color: 'common.white',
                p: 2,
                borderRadius: 1,
                mb: 1,
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                fontFamily: 'monospace',
                fontSize: '14px',
                wordBreak: 'break-all',
              }}
            >
              <Typography fontFamily="monospace" fontSize="14px" sx={{ flex: 1 }}>
                {keyRevealed ? createdKey.api_key : '•'.repeat(40)}
              </Typography>
              <Tooltip title={keyRevealed ? t('apiKeys.hideKey') : t('apiKeys.revealKey')}>
                <IconButton size="small" onClick={() => setKeyRevealed(!keyRevealed)} sx={{ color: 'white' }}>
                  {keyRevealed ? <VisibilityOffIcon fontSize="small" /> : <VisibilityIcon fontSize="small" />}
                </IconButton>
              </Tooltip>
              <Tooltip title={copied ? t('app.copied') : t('app.copy')}>
                <IconButton size="small" onClick={handleCopyKey} sx={{ color: 'white' }}>
                  <ContentCopyIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>

            {copied && (
              <Alert severity="success" sx={{ mb: 2 }}>
                {t('app.copied')}
              </Alert>
            )}

            <Typography variant="caption" color="text.secondary" sx={{ mb: 2, display: 'block' }}>
              {t('apiKeys.keyFormatHint')}
            </Typography>

            <Box display="flex" flexDirection="column" gap={1}>
              <Typography variant="body2">
                <strong>{t('apiKeys.agentIdentity')}:</strong> {createdKey.agent_identity_name}
              </Typography>
              <Typography variant="body2">
                <strong>{t('apiKeys.agentRole')}:</strong> {createdKey.agent_role_name}
              </Typography>
              <Typography variant="body2">
                <strong>{t('apiKeys.keyHint')}:</strong>{' '}
                <Typography component="span" fontFamily="monospace" fontSize="13px">
                  {createdKey.key_prefix}...
                </Typography>
              </Typography>
            </Box>
          </DialogContent>
          <DialogActions>
            <Button variant="contained" onClick={handleDone}>
              {t('apiKeys.doneSaved')}
            </Button>
          </DialogActions>
        </>
      )}
    </Dialog>
  )
}
