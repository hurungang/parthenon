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

interface AssignRolesToIdentityDialogProps {
  open: boolean
  identity: AgentIdentity | null
  onClose: () => void
  onSaved: () => Promise<void>
}

/**
 * Dialog to bulk-assign AgentRoles to an AgentIdentity.
 * Fetches all roles, pre-selects those already assigned, and submits the delta.
 */
export function AssignRolesToIdentityDialog({
  open,
  identity,
  onClose,
  onSaved,
}: AssignRolesToIdentityDialogProps) {
  const { t } = useTranslation()
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [saving, setSaving] = useState(false)

  const { data: allRoles, isLoading: loadingAll } = useQuery<AgentRole[]>({
    queryKey: ['agents', 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole[]>('/agents/roles')
      return data
    },
    enabled: open,
  })

  const { data: assignedRoles, isLoading: loadingAssigned } = useQuery<AgentRole[]>({
    queryKey: ['agents', 'identities', identity?.id, 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole[]>(`/agents/identities/${identity!.id}/roles`)
      return data
    },
    enabled: open && !!identity?.id,
  })

  useEffect(() => {
    if (open && assignedRoles) {
      setSelectedIds(assignedRoles.map((r) => r.id))
      setDialogError(null)
    }
  }, [open, assignedRoles])

  const toggle = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const handleSave = async () => {
    if (!identity) return
    try {
      setSaving(true)
      setDialogError(null)

      const previousIds = (assignedRoles ?? []).map((r) => r.id)

      // Roles to add (in selectedIds but not in previousIds)
      const toAdd = selectedIds.filter((id) => !previousIds.includes(id))
      // Roles to remove (in previousIds but not in selectedIds)
      const toRemove = previousIds.filter((id) => !selectedIds.includes(id))

      if (toAdd.length > 0) {
        await apiClient.post(`/agents/identities/${identity.id}/roles`, { role_ids: toAdd })
      }
      for (const roleId of toRemove) {
        await apiClient.delete(`/agents/identities/${identity.id}/roles/${roleId}`)
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
        {t('agents.identities.assignRolesTitle', { name: identity?.name ?? '' })}
      </DialogTitle>

      <DialogContent dividers>
        {dialogError ? (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        ) : null}

        {isLoading ? (
          <Box display="flex" justifyContent="center" py={3}>
            <CircularProgress size={24} />
          </Box>
        ) : (allRoles ?? []).length === 0 ? (
          <Typography color="text.secondary">{t('agents.roles.empty')}</Typography>
        ) : (
          <Box>
            <Typography variant="body2" color="text.secondary" mb={2}>
              {t('agents.identities.assignRolesHint')}
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
              {(allRoles ?? []).map((role) => (
                <FormControlLabel
                  key={role.id}
                  control={
                    <Checkbox
                      size="small"
                      checked={selectedIds.includes(role.id)}
                      onChange={() => toggle(role.id)}
                    />
                  }
                  label={
                    <Box>
                      <Typography variant="body2">{role.name}</Typography>
                      {role.description && (
                        <Typography variant="caption" color="text.secondary">
                          {role.description}
                        </Typography>
                      )}
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
