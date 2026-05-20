import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import {
  createChannel,
  testChannel,
  updateChannel,
} from '../../services/notificationService'
import type { ChannelPropertyWrite, NotificationChannel } from '../../types'

const CHANNEL_TYPES = ['SMTP', 'SENDGRID', 'RESEND', 'TEAMS_WEBHOOK', 'SLACK_WEBHOOK'] as const
const SECRET_PLACEHOLDER = '••••••••••••••••'

interface PropertyField {
  key: string
  label: string
  isSecret: boolean
  placeholder?: string
}

const PROPERTY_FIELDS: Record<string, PropertyField[]> = {
  SMTP: [
    { key: 'smtp_host', label: 'notifications.channels.smtpHost', isSecret: false, placeholder: 'mail.example.com' },
    { key: 'smtp_port', label: 'notifications.channels.smtpPort', isSecret: false, placeholder: '587' },
    { key: 'smtp_username', label: 'notifications.channels.smtpUsername', isSecret: false },
    { key: 'smtp_password', label: 'notifications.channels.smtpPassword', isSecret: true },
    { key: 'from_address', label: 'notifications.channels.fromAddress', isSecret: false },
    { key: 'use_tls', label: 'notifications.channels.useTls', isSecret: false, placeholder: 'true' },
    { key: 'default_recipient', label: 'notifications.channels.defaultRecipient', isSecret: false },
  ],
  SENDGRID: [
    { key: 'api_key', label: 'notifications.channels.apiKey', isSecret: true },
    { key: 'from_address', label: 'notifications.channels.fromAddress', isSecret: false },
    { key: 'from_name', label: 'notifications.channels.fromName', isSecret: false },
    { key: 'default_recipient', label: 'notifications.channels.defaultRecipient', isSecret: false },
  ],
  RESEND: [
    { key: 'api_key', label: 'notifications.channels.apiKey', isSecret: true },
    { key: 'from_address', label: 'notifications.channels.fromAddress', isSecret: false },
    { key: 'default_recipient', label: 'notifications.channels.defaultRecipient', isSecret: false },
  ],
  TEAMS_WEBHOOK: [
    { key: 'webhook_url', label: 'notifications.channels.webhookUrl', isSecret: true },
    { key: 'channel_name', label: 'notifications.channels.channelName', isSecret: false },
  ],
  SLACK_WEBHOOK: [
    { key: 'webhook_url', label: 'notifications.channels.webhookUrl', isSecret: true },
    { key: 'channel_name', label: 'notifications.channels.channelName', isSecret: false },
  ],
}

interface Props {
  open: boolean
  channel: NotificationChannel | null  // null = create mode
  onClose: () => void
  onSaved: () => void
}

export function ChannelFormDialog({ open, channel, onClose, onSaved }: Props) {
  const { t } = useTranslation()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()

  const [name, setName] = useState('')
  const [channelType, setChannelType] = useState<string>('WEBHOOK')
  const [description, setDescription] = useState('')
  const [isActive, setIsActive] = useState(true)
  const [propValues, setPropValues] = useState<Record<string, string>>({})

  // Test send state
  const [testRecipient, setTestRecipient] = useState('')
  const [testResult, setTestResult] = useState<{ success: boolean; error?: string | null } | null>(null)
  const [testLoading, setTestLoading] = useState(false)

  // Populate form in edit mode
  useEffect(() => {
    if (open) {
      clearDialogError()
      setTestResult(null)
      if (channel) {
        setName(channel.name)
        setChannelType(channel.channel_type)
        setDescription(channel.description ?? '')
        setIsActive(channel.is_active)
        // Populate property values:
        // - Secret properties that exist: show placeholder (existence means they have a value)
        // - Non-secret properties: show actual value
        const vals: Record<string, string> = {}
        channel.properties.forEach((p) => {
          if (p.is_secret) {
            // Secret property exists in the array → it has a value → show placeholder
            vals[p.key] = SECRET_PLACEHOLDER
          } else {
            // Non-secret property: show the actual value for editing
            vals[p.key] = p.value ?? ''
          }
        })
        setPropValues(vals)
      } else {
        setName('')
        setChannelType('SMTP')
        setDescription('')
        setIsActive(true)
        setPropValues({})
      }
    }
  }, [open, channel])

  const fields = PROPERTY_FIELDS[channelType] ?? []

  const handleSave = async () => {
    clearDialogError()
    try {
      // Build properties list, excluding empty values and unchanged secrets (still showing placeholder)
      const properties: ChannelPropertyWrite[] = fields
        .filter((f) => {
          const val = propValues[f.key]
          // Skip if empty
          if (!val) return false
          // Skip if it's a secret that hasn't been changed (still shows placeholder)
          if (f.isSecret && val === SECRET_PLACEHOLDER) return false
          return true
        })
        .map((f) => ({ key: f.key, value: propValues[f.key] ?? '', is_secret: f.isSecret }))

      if (channel) {
        await updateChannel(channel.id, {
          name,
          description: description || null,
          is_active: isActive,
          properties: properties.length > 0 ? properties : undefined,
        })
      } else {
        await createChannel({ name, channel_type: channelType, description: description || null, properties })
      }
      onSaved()
      onClose()
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleTestSend = async () => {
    if (!channel || !testRecipient) return
    setTestLoading(true)
    setTestResult(null)
    try {
      const result = await testChannel(channel.id, testRecipient)
      setTestResult(result)
    } catch (err) {
      setTestResult({ success: false, error: String(err) })
    } finally {
      setTestLoading(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={() => { onClose(); clearDialogError() }}
      maxWidth="sm"
      fullWidth
    >
      <DialogTitle>
        {channel ? t('notifications.channels.edit') : t('notifications.channels.add')}
      </DialogTitle>
      <DialogContent>
        {!!dialogError && (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        )}
        <Stack spacing={2} mt={1}>
          <TextField
            label={t('notifications.channels.name')}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            fullWidth
          />
          <TextField
            select
            label={t('notifications.channels.type')}
            value={channelType}
            onChange={(e) => { setChannelType(e.target.value); setPropValues({}) }}
            fullWidth
            disabled={!!channel}
          >
            {CHANNEL_TYPES.map((ct) => (
              <MenuItem key={ct} value={ct}>
                {t(`notifications.channelTypes.${ct}`)}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label={t('notifications.channels.description')}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            fullWidth
            multiline
            rows={2}
          />
          <FormControlLabel
            control={<Switch checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />}
            label={t('notifications.channels.active')}
          />

          {fields.length > 0 && (
            <>
              <Divider />
              <Typography variant="subtitle2" color="text.secondary">
                {t('notifications.channels.properties')}
              </Typography>
              {fields.map((f) => {
                const currentValue = propValues[f.key] ?? ''
                const isExistingSecret = f.isSecret && currentValue === SECRET_PLACEHOLDER
                const helperText = f.isSecret 
                  ? (isExistingSecret 
                      ? t('notifications.channels.secretExistsHelp') 
                      : t('notifications.channels.secretHelp'))
                  : undefined
                
                return (
                  <TextField
                    key={f.key}
                    label={t(f.label)}
                    value={currentValue}
                    onChange={(e) => setPropValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
                    type={f.isSecret ? 'password' : 'text'}
                    placeholder={f.placeholder}
                    fullWidth
                    helperText={helperText}
                  />
                )
              })}
            </>
          )}

          {channel && (
            <>
              <Divider />
              <Typography variant="subtitle2" color="text.secondary">
                {t('notifications.channels.testSend')}
              </Typography>
              <Stack direction="row" spacing={1} alignItems="center">
                <TextField
                  label={t('notifications.channels.testRecipient')}
                  value={testRecipient}
                  onChange={(e) => setTestRecipient(e.target.value)}
                  size="small"
                  sx={{ flex: 1 }}
                />
                <Button
                  variant="outlined"
                  onClick={handleTestSend}
                  disabled={!testRecipient || testLoading}
                  size="small"
                >
                  {t('notifications.channels.sendTest')}
                </Button>
              </Stack>
              {testResult && (
                <Alert severity={testResult.success ? 'success' : 'error'}>
                  {testResult.success
                    ? t('notifications.channels.testSuccess')
                    : testResult.error ?? t('app.error')}
                </Alert>
              )}
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => { onClose(); clearDialogError() }}>
          {t('app.cancel')}
        </Button>
        <Button variant="contained" onClick={handleSave}>
          {t('app.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
