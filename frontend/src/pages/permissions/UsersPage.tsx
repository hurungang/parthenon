import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  CircularProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import ManageAccountsIcon from '@mui/icons-material/ManageAccounts'
import { usePlatformUsers } from '../../hooks/usePermissions'
import { ManageAccessModal } from '../../components/permissions/ManageAccessModal'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { PlatformUser } from '../../types/permissions'

export function UsersPage() {
  const { t } = useTranslation()
  const { data: users, isLoading, error } = usePlatformUsers()
  const [search, setSearch] = useState('')
  const [manageUser, setManageUser] = useState<PlatformUser | null>(null)

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
            {filtered.map((user) => (
              <TableRow key={user.id} hover sx={{ cursor: 'pointer' }}>
                <TableCell>{user.display_name}</TableCell>
                <TableCell>{user.email}</TableCell>
                <TableCell>{user.direct_role_count}</TableCell>
                <TableCell>{user.group_count}</TableCell>
                <TableCell>{new Date(user.last_seen_at).toLocaleDateString()}</TableCell>
                <TableCell>
                  <Button
                    size="small"
                    startIcon={<ManageAccountsIcon />}
                    onClick={() => setManageUser(user)}
                  >
                    {t('permissions.users.manageAccess')}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {manageUser && (
        <ManageAccessModal
          userId={manageUser.id}
          displayName={manageUser.display_name}
          open={!!manageUser}
          onClose={() => setManageUser(null)}
        />
      )}
    </Box>
  )
}
