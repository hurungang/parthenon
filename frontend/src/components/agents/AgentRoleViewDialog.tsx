import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { AgentRoleDialog } from '../../pages/agents/AgentRoleDialog'
import type { AgentRole } from '../../types'

interface AgentRoleViewDialogProps {
  open: boolean
  roleId: string | null
  onClose: () => void
}

/**
 * Read-only view dialog for a single AgentRole.
 * Displays role details and provides an Edit button to open AgentRoleDialog.
 */
export function AgentRoleViewDialog({ open, roleId, onClose }: AgentRoleViewDialogProps) {
  const { t } = useTranslation()
  const [editOpen, setEditOpen] = useState(false)

  const {
    data: role,
    isLoading,
    error,
  } = useQuery<AgentRole>({
    queryKey: ['agents', 'roles', roleId],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole>(`/agents/roles/${roleId}`)
      return data
    },
    enabled: open && !!roleId,
  })

  return (
    <>
      <Dialog
        open={open}
        onClose={onClose}
        maxWidth="xl"
        fullWidth
        PaperProps={{ sx: { width: { xs: '100%', sm: '90%', lg: '95%' } } }}
      >
        <DialogTitle>{t('agents.roles.viewTitle')}</DialogTitle>

        <DialogContent dividers>
          {error != null && (
            <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />
          )}
          {isLoading && (
            <Box display="flex" justifyContent="center" p={4}>
              <CircularProgress />
            </Box>
          )}
          {role && (
            <Box display="flex" flexWrap="wrap" gap={2}>
              <Box sx={{ flex: '1 1 40%', minWidth: 160 }}>
                <Typography variant="caption" color="text.secondary" display="block">
                  {t('app.name')}
                </Typography>
                <Typography variant="body2" fontWeight={500} mt={0.25}>
                  {role.name}
                </Typography>
              </Box>

              <Box sx={{ flex: '1 1 40%', minWidth: 160 }}>
                <Typography variant="caption" color="text.secondary" display="block">
                  {t('app.description')}
                </Typography>
                <Typography variant="body2" mt={0.25}>
                  {role.description ?? '—'}
                </Typography>
              </Box>

              <Box sx={{ flex: '1 1 40%', minWidth: 160 }}>
                <Typography variant="caption" color="text.secondary" display="block">
                  {t('agents.roles.assignedSops')}
                </Typography>
                <Box mt={0.25}>
                  {role.sop_ids.length === 0 ? (
                    <Typography variant="body2">—</Typography>
                  ) : (
                    <Chip
                      label={t('agents.roles.sopCount', { count: role.sop_ids.length })}
                      size="small"
                      color="primary"
                      variant="outlined"
                    />
                  )}
                </Box>
              </Box>

              <Box sx={{ flex: '1 1 40%', minWidth: 160 }}>
                <Typography variant="caption" color="text.secondary" display="block">
                  {t('agents.roles.assignedSkills')}
                </Typography>
                <Box mt={0.25}>
                  {role.skill_ids.length === 0 ? (
                    <Typography variant="body2">—</Typography>
                  ) : (
                    <Chip
                      label={t('agents.roles.skillCount', { count: role.skill_ids.length })}
                      size="small"
                      color="secondary"
                      variant="outlined"
                    />
                  )}
                </Box>
              </Box>
            </Box>
          )}
        </DialogContent>

        <DialogActions>
          <Button variant="outlined" onClick={() => setEditOpen(true)} disabled={!role}>
            {t('app.edit')}
          </Button>
          <Button onClick={onClose}>{t('app.close')}</Button>
        </DialogActions>
      </Dialog>

      {role && (
        <AgentRoleDialog
          open={editOpen}
          editRole={role}
          onClose={() => setEditOpen(false)}
          onSaved={async () => {
            setEditOpen(false)
          }}
        />
      )}
    </>
  )
}
