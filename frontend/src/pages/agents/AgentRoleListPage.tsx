import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { AgentRoleDialog } from './AgentRoleDialog'
import type { AgentRole } from '../../types'

/**
 * Agent Role list page — displays all roles with SOP/Skill chips and MCP tool count.
 */
export function AgentRoleListPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editRole, setEditRole] = useState<AgentRole | null>(null)

  const { data: roles, isLoading, error } = useQuery<AgentRole[]>({
    queryKey: ['agents', 'roles'],
    queryFn: async () => {
      const { data } = await apiClient.get<AgentRole[]>('/agents/roles')
      return data
    },
  })

  const handleOpenCreate = () => {
    setEditRole(null)
    setDialogOpen(true)
  }

  const handleOpenEdit = (role: AgentRole) => {
    setEditRole(role)
    setDialogOpen(true)
  }

  const handleDelete = async (id: string, name: string) => {
    if (confirm(t('agents.roles.deleteConfirm', { name }))) {
      await apiClient.delete(`/agents/roles/${id}`)
      await queryClient.invalidateQueries({ queryKey: ['agents', 'roles'] })
    }
  }

  const handleDialogClose = () => {
    setDialogOpen(false)
    setEditRole(null)
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
        <Box>
          <Typography variant="h4" fontWeight={700}>{t('agents.roles.title')}</Typography>
          <Typography variant="body2" color="text.secondary" mt={0.5}>
            {t('agents.roles.subtitle')}
          </Typography>
        </Box>
        <Button variant="contained" startIcon={<AddIcon />} onClick={handleOpenCreate}>
          {t('agents.roles.create')}
        </Button>
      </Box>

      {isLoading && <CircularProgress />}
      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      {!isLoading && !error && (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>{t('app.name')}</TableCell>
                <TableCell>{t('app.description')}</TableCell>
                <TableCell>{t('agents.roles.assignedSops')}</TableCell>
                <TableCell>{t('agents.roles.assignedSkills')}</TableCell>
                <TableCell>{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(roles ?? []).map((role) => (
                <TableRow key={role.id} hover>
                  <TableCell>
                    <Typography fontWeight={500}>{role.name}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" color="text.secondary">
                      {role.description ?? '—'}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Box display="flex" gap={0.5} flexWrap="wrap">
                      {role.sop_ids.length === 0 ? (
                        <Typography variant="body2" color="text.secondary">—</Typography>
                      ) : (
                        <Chip
                          label={t('agents.roles.sopCount', { count: role.sop_ids.length })}
                          size="small"
                          color="primary"
                          variant="outlined"
                        />
                      )}
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Box display="flex" gap={0.5} flexWrap="wrap">
                      {role.skill_ids.length === 0 ? (
                        <Typography variant="body2" color="text.secondary">—</Typography>
                      ) : (
                        <Chip
                          label={t('agents.roles.skillCount', { count: role.skill_ids.length })}
                          size="small"
                          color="secondary"
                          variant="outlined"
                        />
                      )}
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Box display="flex" gap={0.5}>
                      <Tooltip title={t('app.edit')}>
                        <IconButton size="small" onClick={() => handleOpenEdit(role)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title={t('app.delete')}>
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => handleDelete(role.id, role.name)}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                  </TableCell>
                </TableRow>
              ))}
              {(roles ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} align="center">
                    <Typography color="text.secondary" py={3}>
                      {t('agents.roles.empty')}
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <AgentRoleDialog
        open={dialogOpen}
        editRole={editRole}
        onClose={handleDialogClose}
        onSaved={async () => {
          await queryClient.invalidateQueries({ queryKey: ['agents', 'roles'] })
          handleDialogClose()
        }}
      />
    </Box>
  )
}
