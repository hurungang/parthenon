import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'
import ManageAccountsIcon from '@mui/icons-material/ManageAccounts'
import { usePagination } from '../../hooks/usePagination'
import { usePlatformUsers, useDeletePlatformUser } from '../../hooks/usePermissions'
import { ManageAccessModal } from '../../components/permissions/ManageAccessModal'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { PlatformUser } from '../../types/permissions'

export function UsersPage() {
  const { t } = useTranslation()
  const pag = usePagination({ initialRowsPerPage: 20 })
  const { data: users, isLoading, error } = usePlatformUsers(pag.page + 1, pag.rowsPerPage)
  const deleteUser = useDeletePlatformUser()
  const [search, setSearch] = useState('')
  const [manageUser, setManageUser] = useState<PlatformUser | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<PlatformUser | null>(null)

  const isSuperAdmin = (u: PlatformUser) => u.sub.startsWith('super_admin:')

  const filtered = (users ?? []).filter(
    (u) =>
      !search ||
      u.display_name.toLowerCase().includes(search.toLowerCase()) ||
      u.email.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <Box>
      <Typography variant="h6" mb={2}>
        {t('permissions.users.title')}
      </Typography>

      <TextField
        size="small"
        placeholder={t('app.search')}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        sx={{ mb: 2, width: 300 }}
      />

      {isLoading && <CircularProgress />}
      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t('permissions.users.displayName')}</TableCell>
              <TableCell>{t('permissions.users.email')}</TableCell>
              <TableCell>{t('permissions.users.directRoles')}</TableCell>
              <TableCell>{t('permissions.users.groupMemberships')}</TableCell>
              <TableCell>{t('permissions.users.lastSeen')}</TableCell>
              <TableCell>{t('app.actions')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {filtered.map((user) => {
              const sa = isSuperAdmin(user)
              return (
                <TableRow key={user.id} hover sx={{ cursor: 'pointer' }}>
                  <TableCell>
                    {user.display_name}
                    {sa && (
                      <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                        ({t('permissions.users.builtIn')})
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell>{user.email}</TableCell>
                  <TableCell>{user.direct_role_count}</TableCell>
                  <TableCell>{user.group_count}</TableCell>
                  <TableCell>{new Date(user.last_seen_at).toLocaleDateString()}</TableCell>
                  <TableCell>
                    {!sa && (
                      <>
                        <Button
                          size="small"
                          startIcon={<ManageAccountsIcon />}
                          onClick={() => setManageUser(user)}
                        >
                          {t('permissions.users.manageAccess')}
                        </Button>
                        <Button
                          size="small"
                          color="error"
                          startIcon={<DeleteIcon />}
                          onClick={() => setDeleteTarget(user)}
                          sx={{ ml: 0.5 }}
                        >
                          {t('app.delete')}
                        </Button>
                      </>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </TableContainer>

      <TablePagination
        component="div"
        count={-1}
        page={pag.page}
        onPageChange={pag.onPageChange}
        rowsPerPage={pag.rowsPerPage}
        onRowsPerPageChange={pag.onRowsPerPageChange}
        rowsPerPageOptions={pag.rowsPerPageOptions}
        labelRowsPerPage={t('app.rowsPerPage')}
      />

      {manageUser && (
        <ManageAccessModal
          userId={manageUser.id}
          displayName={manageUser.display_name}
          open={!!manageUser}
          onClose={() => setManageUser(null)}
        />
      )}

      <Dialog
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
      >
        <DialogTitle>{t('permissions.users.deleteUserTitle')}</DialogTitle>
        <DialogContent>
          <DialogContentText>
            {t('permissions.users.deleteUserConfirm', { name: deleteTarget?.display_name ?? '' })}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>
            {t('app.cancel')}
          </Button>
          <Button
            color="error"
            disabled={deleteUser.isPending}
            onClick={() => {
              if (deleteTarget) {
                deleteUser.mutate(deleteTarget.id, {
                  onSuccess: () => setDeleteTarget(null),
                })
              }
            }}
          >
            {deleteUser.isPending ? t('app.deleting') : t('app.delete')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
