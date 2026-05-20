import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import type { NotificationChannel } from '../../types'

interface Props {
  open: boolean
  channel: NotificationChannel | null
  onClose: () => void
  onConfirm: (recipientProperties: Record<string, unknown>) => void
}

export function AssignChannelDialog({ open, channel, onClose, onConfirm }: Props) {
  const { t } = useTranslation()
  const [recipients, setRecipients] = useState('')
  const [channelId, setChannelId] = useState('')
  const [error, setError] = useState('')

  const handleConfirm = () => {
    setError('')
    
    if (!channel) return

    const channelType = channel.channel_type
    let recipientProperties: Record<string, unknown> = {}

    // For email channels: validate and parse recipients
    if (channelType === 'SMTP' || channelType === 'SENDGRID' || channelType === 'RESEND') {
      const emails = recipients
        .split(/[,\n]/)
        .map((e) => e.trim())
        .filter((e) => e.length > 0)

      if (emails.length === 0) {
        setError(t('notifications.groups.recipientsRequired'))
        return
      }

      // Basic email validation
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
      const invalid = emails.filter((e) => !emailRegex.test(e))
      if (invalid.length > 0) {
        setError(t('notifications.groups.invalidEmails', { emails: invalid.join(', ') }))
        return
      }

      recipientProperties = { recipients: emails }
    }
    // For webhook channels: use channel_id or other properties
    else if (channelType === 'TEAMS_WEBHOOK' || channelType === 'SLACK_WEBHOOK') {
      if (channelId.trim()) {
        recipientProperties = { channel_id: channelId.trim() }
      }
      // Channel ID is optional for webhooks (webhook URL might be sufficient)
    }

    onConfirm(recipientProperties)
    onClose()
    setRecipients('')
    setChannelId('')
    setError('')
  }

  const handleClose = () => {
    onClose()
    setRecipients('')
    setChannelId('')
    setError('')
  }

  if (!channel) return null

  const isEmailChannel = ['SMTP', 'SENDGRID', 'RESEND'].includes(channel.channel_type)
  const isWebhookChannel = ['TEAMS_WEBHOOK', 'SLACK_WEBHOOK'].includes(channel.channel_type)

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t('notifications.groups.assignChannelTitle')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} mt={1}>
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2" fontWeight={600}>
              {t('notifications.channels.name')}:
            </Typography>
            <Typography variant="body2">{channel.name}</Typography>
          </Stack>
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2" fontWeight={600}>
              {t('notifications.channels.type')}:
            </Typography>
            <Chip
              label={t(`notifications.channelTypes.${channel.channel_type}`)}
              size="small"
              color="primary"
              variant="outlined"
            />
          </Stack>

          {isEmailChannel && (
            <>
              <Typography variant="body2" color="text.secondary" mt={1}>
                {t('notifications.groups.recipientsHelp')}
              </Typography>
              <TextField
                label={t('notifications.groups.recipientEmails')}
                value={recipients}
                onChange={(e) => setRecipients(e.target.value)}
                multiline
                rows={4}
                fullWidth
                required
                placeholder="user1@example.com, user2@example.com"
                helperText={t('notifications.groups.recipientsPlaceholder')}
              />
            </>
          )}

          {isWebhookChannel && (
            <>
              <Typography variant="body2" color="text.secondary" mt={1}>
                {t('notifications.groups.webhookHelp')}
              </Typography>
              <TextField
                label={t('notifications.groups.webhookChannelId')}
                value={channelId}
                onChange={(e) => setChannelId(e.target.value)}
                fullWidth
                placeholder="C1234567 or @username"
                helperText={t('notifications.groups.webhookChannelIdHelp')}
              />
            </>
          )}

          {error && (
            <Alert severity="error" onClose={() => setError('')}>
              {error}
            </Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>{t('app.cancel')}</Button>
        <Button variant="contained" onClick={handleConfirm}>
          {t('notifications.groups.assign')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
