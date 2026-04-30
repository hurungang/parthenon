import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from '@mui/material'
import { useGroupRoles, useAssignGroupRole, useRemoveGroupRole, useRoles } from '../../hooks/usePermissions'
import { extractErrorMessage } from '../../utils/errorUtils'
import type { Group } from '../../types/permissions'

interface ManageGroupRolesModalProps {
  open: boolean
  onClose: () => void
  group: Group | null
}

export function ManageGroupRolesModal({ open, onClose, group }: ManageGroupRolesModalProps) {
  const { t } = useTranslation()
  const [selectedRoleId, setSelectedRoleId] = useState('')

  const { data: assignedRoles, isLoading: rolesLoading, error: rolesError } = useGroupRoles(group?.id ?? null)
  const { data: allRoles } = useRoles()
  const assignGroupRole = useAssignGroupRole()
  const removeGroupRole = useRemoveGroupRole()

  const assignedRoleIds = new Set((assignedRoles ?? []).map((r) => r.id))
  const availableRoles = (allRoles ?? []).filter((r) => !assignedRoleIds.has(r.id))

  const handleAdd = async () => {
    if (!group || !selectedRoleId) return
    await assignGroupRole.mutateAsync({ groupId: group.id, roleId: selectedRoleId })
    setSelectedRoleId('')
  }

  const handleRemove = async (roleId: string) => {
    if (!group) return
    await removeGroupRole.mutateAsync({ groupId: group.id, roleId })
  }

  const handleClose = () => {
    setSelectedRoleId('')
    onClose()
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        {t('permissions.groups.manageRolesTitle', { groupName: group?.name ?? '' })}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="subtitle2">{t('permissions.groups.assignedRoles')}</Typography>

          {rolesLoading && <CircularProgress size={20} />}
          {rolesError && (
            <Alert severity="error">{extractErrorMessage(rolesError, t('app.error'))}</Alert>
          )}

          {!rolesLoading && !rolesError && assignedRoles?.length === 0 && (
            <Typography variant="body2" color="text.secondary">
              {t('permissions.groups.noRolesAssigned')}
            </Typography>
          )}

          {!rolesLoading && assignedRoles && assignedRoles.length > 0 && (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
              {assignedRoles.map((role) => (
                <Chip
                  key={role.id}
                  label={role.name}
                  onDelete={() => handleRemove(role.id)}
                  disabled={removeGroupRole.isPending}
                />
              ))}
            </Box>
          )}

          <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-end' }}>
            <FormControl size="small" sx={{ flex: 1 }}>
              <InputLabel>{t('permissions.groups.selectRole')}</InputLabel>
              <Select
                value={selectedRoleId}
                label={t('permissions.groups.selectRole')}
                onChange={(e) => setSelectedRoleId(e.target.value)}
              >
                {availableRoles.map((role) => (
                  <MenuItem key={role.id} value={role.id}>
                    {role.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button
              variant="contained"
              onClick={handleAdd}
              disabled={!selectedRoleId || assignGroupRole.isPending}
            >
              {t('permissions.groups.addRole')}
            </Button>
          </Box>

          {assignGroupRole.isError && (
            <Alert severity="error">
              {extractErrorMessage(assignGroupRole.error, t('app.error'))}
            </Alert>
          )}
          {removeGroupRole.isError && (
            <Alert severity="error">
              {extractErrorMessage(removeGroupRole.error, t('app.error'))}
            </Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>{t('app.close')}</Button>
      </DialogActions>
    </Dialog>
  )
}
