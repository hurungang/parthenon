import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import CodeIcon from '@mui/icons-material/Code'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { useRoles, useCreateRole, useDeleteRole } from '../../hooks/usePermissions'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import PolicyEditor from '../../components/permissions/PolicyEditor'
import JSONViewModal from '../../components/permissions/JSONViewModal'
import CloneRoleDialog from '../../components/permissions/CloneRoleDialog'
import type { Role } from '../../types/permissions'

export function RolesPage() {
  const { t } = useTranslation()
  const { data: roles, isLoading, error } = useRoles()
  const createRole = useCreateRole()
  const deleteRole = useDeleteRole()

  const [addOpen, setAddOpen] = useState(false)
  const [addDialogError, setAddDialogError] = useState<unknown>(null)
  const [roleForm, setRoleForm] = useState({ name: '', description: '' })
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null)
  const [forceDelete, setForceDelete] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  // JSON view and clone dialog state
  const [jsonViewRole, setJsonViewRole] = useState<Role | null>(null)
  const [cloneTargetRole, setCloneTargetRole] = useState<Role | null>(null)

  const handleSaveRole = async () => {
    try {
      setAddDialogError(null)
      await createRole.mutateAsync(roleForm)
      setAddOpen(false)
      setRoleForm({ name: '', description: '' })
    } catch (err) {
      setAddDialogError(err)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleteError(null)
    try {
      await deleteRole.mutateAsync({ id: deleteTarget.id, force: forceDelete })
      setDeleteTarget(null)
      setForceDelete(false)
    } catch (e: unknown) {
      const err = e as { response?: { status?: number } }
      if (err?.response?.status === 409 && !forceDelete) {
        setDeleteError('conflict')
      }
    }
  }

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6">{t('permissions.roles.title')}</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setAddOpen(true)}>
          {t('permissions.roles.addRole')}
        </Button>
      </Box>

      {isLoading && <CircularProgress />}
      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell />
              <TableCell>{t('app.name')}</TableCell>
              <TableCell>{t('app.description')}</TableCell>
              <TableCell>{t('permissions.roles.policyCount')}</TableCell>
              <TableCell>{t('app.actions')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(roles ?? []).map((role) => (
              <>
                <TableRow key={role.id}>
                  <TableCell>
                    <IconButton
                      size="small"
                      aria-label={expandedId === role.id ? t('app.collapse') : t('app.expand')}
                      onClick={() => setExpandedId(expandedId === role.id ? null : role.id)}
                    >
                      {expandedId === role.id ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                    </IconButton>
                  </TableCell>
                  <TableCell>{role.name}</TableCell>
                  <TableCell>{role.description ?? '—'}</TableCell>
                  <TableCell>{role.policy_count}</TableCell>
                  <TableCell>
                    <Tooltip title={t('permissions.roles.jsonView')}>
                      <IconButton size="small" onClick={() => setJsonViewRole(role)}>
                        <CodeIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={t('permissions.roles.cloneRole')}>
                      <IconButton size="small" onClick={() => setCloneTargetRole(role)}>
                        <ContentCopyIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={t('app.delete')}>
                      <IconButton
                        size="small"
                        onClick={() => {
                          setDeleteTarget(role)
                          setDeleteError(null)
                          setForceDelete(false)
                        }}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
                {expandedId === role.id && (
                  <TableRow key={`${role.id}-expand`}>
                    <TableCell colSpan={5}>
                      <Collapse in>
                        <PolicyEditor roleId={role.id} />
                      </Collapse>
                    </TableCell>
                  </TableRow>
                )}
              </>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Add Role dialog */}
      <Dialog
        open={addOpen}
        onClose={() => {
          setAddOpen(false)
          setAddDialogError(null)
        }}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>{t('permissions.roles.addRole')}</DialogTitle>
        <DialogContent>
          {addDialogError ? (
            <PermissionDeniedAlert error={addDialogError} fallbackMessage={t('app.error')} />
          ) : null}
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label={t('app.name')}
              value={roleForm.name}
              onChange={(e) => setRoleForm((f) => ({ ...f, name: e.target.value }))}
              required
            />
            <TextField
              label={t('app.description')}
              value={roleForm.description}
              onChange={(e) => setRoleForm((f) => ({ ...f, description: e.target.value }))}
              multiline
              rows={2}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddOpen(false)}>{t('app.cancel')}</Button>
          <Button
            onClick={handleSaveRole}
            variant="contained"
            disabled={createRole.isPending}
          >
            {t('app.save')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete confirmation */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>{t('permissions.roles.deleteRole')}</DialogTitle>
        <DialogContent>
          {deleteError === 'conflict' ? (
            <Alert severity="warning">
              {t('permissions.roles.deleteWithAssignmentsConfirm', { name: deleteTarget?.name })}
            </Alert>
          ) : (
            <Typography>
              {t('permissions.roles.deleteConfirm', { name: deleteTarget?.name })}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>{t('app.cancel')}</Button>
          {deleteError === 'conflict' ? (
            <Button
              color="error"
              variant="contained"
              onClick={() => {
                setForceDelete(true)
                handleDelete()
              }}
            >
              {t('permissions.roles.forceDelete')}
            </Button>
          ) : (
            <Button
              color="error"
              variant="contained"
              onClick={handleDelete}
              disabled={deleteRole.isPending}
            >
              {t('app.delete')}
            </Button>
          )}
        </DialogActions>
      </Dialog>

      {/* JSON View modal */}
      {jsonViewRole && (
        <JSONViewModal
          open={!!jsonViewRole}
          roleId={jsonViewRole.id}
          roleName={jsonViewRole.name}
          onClose={() => setJsonViewRole(null)}
        />
      )}

      {/* Clone Role dialog */}
      <CloneRoleDialog
        open={!!cloneTargetRole}
        sourceRole={cloneTargetRole}
        onClose={() => setCloneTargetRole(null)}
      />
    </Box>
  )
}
