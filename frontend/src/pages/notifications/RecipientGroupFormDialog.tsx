import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  List,
  ListItem,
  ListItemText,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import RemoveIcon from '@mui/icons-material/Remove'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import { useNotificationChannels } from '../../hooks/useNotificationChannels'
import {
  assignChannelToGroup,
  createRecipientGroup,
  removeChannelFromGroup,
  updateRecipientGroup,
} from '../../services/notificationService'
import type { NotificationChannel, RecipientGroup } from '../../types'
import { AssignChannelDialog } from './AssignChannelDialog'

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 100)
}

interface Props {
  open: boolean
  group: RecipientGroup | null  // null = create mode
  onClose: () => void
  onSaved: () => void
}

export function RecipientGroupFormDialog({ open, group, onClose, onSaved }: Props) {
  const { t } = useTranslation()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()
  const { channels } = useNotificationChannels()

  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugManual, setSlugManual] = useState(false)
  const [description, setDescription] = useState('')
  const [isActive, setIsActive] = useState(true)

  // Track channel assignment changes for edit mode
  const [assignedChannelIds, setAssignedChannelIds] = useState<Set<string>>(new Set())
  const [assigning, setAssigning] = useState<string | null>(null)
  const [assignDialogOpen, setAssignDialogOpen] = useState(false)
  const [channelToAssign, setChannelToAssign] = useState<NotificationChannel | null>(null)

  useEffect(() => {
    if (open) {
      clearDialogError()
      if (group) {
        setName(group.name)
        setSlug(group.slug)
        setSlugManual(true)
        setDescription(group.description ?? '')
        setIsActive(group.is_active)
        setAssignedChannelIds(new Set(group.channel_mappings.map((m) => m.channel_id)))
      } else {
        setName('')
        setSlug('')
        setSlugManual(false)
        setDescription('')
        setIsActive(true)
        setAssignedChannelIds(new Set())
      }
    }
  }, [open, group])

  const handleNameChange = (v: string) => {
    setName(v)
    if (!slugManual) setSlug(slugify(v))
  }

  const handleSave = async () => {
    clearDialogError()
    try {
      if (group) {
        await updateRecipientGroup(group.id, {
          name,
          slug,
          description: description || null,
          is_active: isActive,
        })
      } else {
        await createRecipientGroup({
          name,
          slug: slug || undefined,
          description: description || null,
          is_active: isActive,
        })
      }
      onSaved()
      onClose()
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleToggleChannel = async (channel: NotificationChannel) => {
    if (!group) return
    
    const channelId = channel.id
    
    // If removing, just remove it
    if (assignedChannelIds.has(channelId)) {
      setAssigning(channelId)
      try {
        await removeChannelFromGroup(group.id, channelId)
        setAssignedChannelIds((prev) => {
          const next = new Set(prev)
          next.delete(channelId)
          return next
        })
      } catch (err) {
        setDialogError(err)
      } finally {
        setAssigning(null)
      }
    } else {
      // If adding, open dialog to get recipient properties
      setChannelToAssign(channel)
      setAssignDialogOpen(true)
    }
  }

  const handleAssignConfirm = async (recipientProperties: Record<string, unknown>) => {
    if (!group || !channelToAssign) return
    
    const channelId = channelToAssign.id
    setAssigning(channelId)
    try {
      await assignChannelToGroup(group.id, channelId, recipientProperties)
      setAssignedChannelIds((prev) => new Set([...prev, channelId]))
    } catch (err) {
      setDialogError(err)
    } finally {
      setAssigning(null)
      setChannelToAssign(null)
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
        {group ? t('notifications.groups.edit') : t('notifications.groups.add')}
      </DialogTitle>
      <DialogContent>
        {!!dialogError && (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        )}
        <Stack spacing={2} mt={1}>
          <TextField
            label={t('notifications.groups.name')}
            value={name}
            onChange={(e) => handleNameChange(e.target.value)}
            required
            fullWidth
          />
          <TextField
            label={t('notifications.groups.slug')}
            value={slug}
            onChange={(e) => { setSlug(e.target.value); setSlugManual(true) }}
            fullWidth
            helperText={t('notifications.groups.slugHelp')}
          />
          <TextField
            label={t('notifications.groups.description')}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            fullWidth
            multiline
            rows={2}
          />
          <FormControlLabel
            control={<Switch checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />}
            label={t('notifications.groups.active')}
          />

          {group && (
            <>
              <Divider />
              <Typography variant="subtitle2" color="text.secondary">
                {t('notifications.groups.channelRecipients')}
              </Typography>
              {channels.length === 0 && (
                <Typography variant="body2" color="text.secondary">
                  {t('notifications.channels.empty')}
                </Typography>
              )}
              <List dense>
                {channels.map((ch) => {
                  const assigned = assignedChannelIds.has(ch.id)
                  return (
                    <ListItem
                      key={ch.id}
                      secondaryAction={
                        <Button
                          size="small"
                          variant={assigned ? 'outlined' : 'contained'}
                          color={assigned ? 'error' : 'primary'}
                          startIcon={assigned ? <RemoveIcon /> : <AddIcon />}
                          onClick={() => handleToggleChannel(ch)}
                          disabled={assigning === ch.id}
                        >
                          {assigned
                            ? t('notifications.groups.removeChannel')
                            : t('notifications.groups.configureChannel')}
                        </Button>
                      }
                    >
                      <ListItemText
                        primary={ch.name}
                        secondary={t(`notifications.channelTypes.${ch.channel_type}`, ch.channel_type)}
                      />
                    </ListItem>
                  )
                })}
              </List>
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

      <AssignChannelDialog
        open={assignDialogOpen}
        channel={channelToAssign}
        onClose={() => {
          setAssignDialogOpen(false)
          setChannelToAssign(null)
        }}
        onConfirm={handleAssignConfirm}
      />
    </Dialog>
  )
}
