import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { AgentIdentity, AgentRole } from '../../types'

interface AssignIdentitiesToRoleDialogProps {
  open: boolean
  role: AgentRole | null
  onClose: () => void
  onSaved: () => Promise<void>
}

/**
 * Dialog to bulk-assign AgentIdentities to an AgentRole.
 * Fetches all identities, pre-selects those already assigned, and submits the delta.
 */
export function AssignIdentitiesToRoleDialog({
  open,
  role,
  onClose,
  onSaved,
}: AssignIdentitiesToRoleDialogProps) {
  const { t } = useTranslation()
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [saving, setSaving] = useState(false)

  const { data: allIdentities, isLoading: loadingAll } = useQuery<AgentIdentity[]>({
    queryKey: ['agents', 'identities'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentIdentity[]>('/agents/identities')
      return data
    },
    enabled: open,
  })

  const { data: assignedIdentities, isLoading: loadingAssigned } = useQuery<AgentIdentity[]>({
    queryKey: ['agents', 'roles', role?.id, 'identities'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentIdentity[]>(`/agents/roles/${role!.id}/identities`)
      return data
    },
    enabled: open && !!role?.id,
  })

  useEffect(() => {
    if (open && assignedIdentities) {
      setSelectedIds(assignedIdentities.map((i) => i.id))
      setDialogError(null)
    }
  }, [open, assignedIdentities])

  const toggle = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const handleSave = async () => {
    if (!role) return
    try {
      setSaving(true)
      setDialogError(null)

      const previousIds = (assignedIdentities ?? []).map((i) => i.id)

      // Identities to add (in selectedIds but not in previousIds)
      const toAdd = selectedIds.filter((id) => !previousIds.includes(id))
      // Identities to remove (in previousIds but not in selectedIds)
      const toRemove = previousIds.filter((id) => !selectedIds.includes(id))

      if (toAdd.length > 0) {
        await apiClient.post(`/agents/roles/${role.id}/identities`, { identity_ids: toAdd })
      }
      for (const identityId of toRemove) {
        await apiClient.delete(`/agents/roles/${role.id}/identities/${identityId}`)
      }

      await onSaved()
    } catch (err) {
      setDialogError(err)
    } finally {
      setSaving(false)
    }
  }

  const isLoading = loadingAll || loadingAssigned

  return (
    <Dialog
      open={open}
      onClose={() => { onClose(); setDialogError(null) }}
      maxWidth="lg"
      fullWidth
    >
      <DialogTitle>
        {t('agents.roles.assignIdentitiesTitle', { name: role?.name ?? '' })}
      </DialogTitle>

      <DialogContent dividers>
        {dialogError ? (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        ) : null}

        {isLoading ? (
          <Box display="flex" justifyContent="center" py={3}>
            <CircularProgress size={24} />
          </Box>
        ) : (allIdentities ?? []).length === 0 ? (
          <Typography color="text.secondary">{t('agents.identities.empty')}</Typography>
        ) : (
          <Box>
            <Typography variant="body2" color="text.secondary" mb={2}>
              {t('agents.roles.assignIdentitiesHint')}
            </Typography>
            <Box
              sx={{
                border: 1,
                borderColor: 'divider',
                borderRadius: 1,
                maxHeight: 320,
                overflow: 'auto',
                p: 1,
              }}
            >
              {(allIdentities ?? []).map((identity) => (
                <FormControlLabel
                  key={identity.id}
                  control={
                    <Checkbox
                      size="small"
                      checked={selectedIds.includes(identity.id)}
                      onChange={() => toggle(identity.id)}
                    />
                  }
                  label={
                    <Box>
                      <Typography variant="body2">{identity.name}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {identity.realm_username ?? ''}
                        {identity.realm_name ? ` @ ${identity.realm_name}` : ''}
                      </Typography>
                    </Box>
                  }
                  sx={{ display: 'flex', mx: 0, mb: 0.5 }}
                />
              ))}
            </Box>
          </Box>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={() => { onClose(); setDialogError(null) }} disabled={saving}>
          {t('app.cancel')}
        </Button>
        <Button variant="contained" onClick={handleSave} disabled={saving || isLoading}>
          {saving ? t('app.saving') : t('app.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
