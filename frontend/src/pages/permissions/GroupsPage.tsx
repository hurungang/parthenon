import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  List,
  ListItem,
  ListItemText,
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
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import PeopleIcon from '@mui/icons-material/People'
import { useGroups, useCreateGroup, useUpdateGroup, useDeleteGroup, useGroupMembers } from '../../hooks/usePermissions'
import type { Group } from '../../types/permissions'

export function GroupsPage() {
  const { t } = useTranslation()
  const { data: groups, isLoading, error } = useGroups()
  const createGroup = useCreateGroup()
  const updateGroup = useUpdateGroup()
  const deleteGroup = useDeleteGroup()

  const [addOpen, setAddOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<Group | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Group | null>(null)
  const [viewMembersGroup, setViewMembersGroup] = useState<Group | null>(null)
  const [form, setForm] = useState({ name: '', description: '', idp_claim_value: '' })
  const [search, setSearch] = useState('')

  const { data: members, isLoading: membersLoading } = useGroupMembers(viewMembersGroup?.id ?? null)

  const openAdd = () => {
    setForm({ name: '', description: '', idp_claim_value: '' })
    setEditTarget(null)
    setAddOpen(true)
  }

  const openEdit = (group: Group) => {
    setEditTarget(group)
    setForm({
      name: group.name,
      description: group.description ?? '',
      idp_claim_value: group.idp_claim_value ?? '',
    })
    setAddOpen(true)
  }

  const handleSave = async () => {
    if (editTarget) {
      await updateGroup.mutateAsync({
        id: editTarget.id,
        data: {
          name: form.name,
          description: form.description || undefined,
          idp_claim_value: form.idp_claim_value || undefined,
        },
      })
    } else {
      await createGroup.mutateAsync({
        name: form.name,
        description: form.description || undefined,
        idp_claim_value: form.idp_claim_value || undefined,
      })
    }
    setAddOpen(false)
    setEditTarget(null)
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    await deleteGroup.mutateAsync(deleteTarget.id)
    setDeleteTarget(null)
  }

  const filtered = (groups ?? []).filter(
    (g) => !search || g.name.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6">{t('permissions.groups.title')}</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openAdd}>
          {t('permissions.groups.addGroup')}
        </Button>
      </Box>

      <TextField
        size="small"
        placeholder={t('app.search')}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        sx={{ mb: 2, width: 300 }}
      />

      {isLoading && <CircularProgress />}
      {error && <Alert severity="error">{t('app.error')}</Alert>}

      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t('app.name')}</TableCell>
              <TableCell>{t('permissions.groups.owner')}</TableCell>
              <TableCell>{t('permissions.groups.memberCount')}</TableCell>
              <TableCell>{t('permissions.groups.roleCount')}</TableCell>
              <TableCell>{t('permissions.groups.idpClaimValue')}</TableCell>
              <TableCell>{t('app.actions')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {filtered.map((group) => (
              <TableRow key={group.id}>
                <TableCell>{group.name}</TableCell>
                <TableCell>{group.owner_display_name ?? '—'}</TableCell>
                <TableCell>{group.member_count}</TableCell>
                <TableCell>{group.role_count}</TableCell>
                <TableCell>{group.idp_claim_value ?? '—'}</TableCell>
                <TableCell>
                  <Tooltip title={t('permissions.groups.viewMembers')}>
                    <IconButton size="small" onClick={() => setViewMembersGroup(group)}>
                      <PeopleIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title={t('app.edit')}>
                    <IconButton size="small" onClick={() => openEdit(group)}>
                      <EditIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title={t('app.delete')}>
                    <IconButton size="small" onClick={() => setDeleteTarget(group)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Add / Edit dialog */}
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          {editTarget ? t('permissions.groups.editGroup') : t('permissions.groups.addGroup')}
        </DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label={t('app.name')}
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              required
            />
            <TextField
              label={t('app.description')}
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              multiline
              rows={2}
            />
            <TextField
              label={t('permissions.groups.idpClaimValue')}
              helperText={t('permissions.groups.idpClaimValueHint')}
              value={form.idp_claim_value}
              onChange={(e) => setForm((f) => ({ ...f, idp_claim_value: e.target.value }))}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddOpen(false)}>{t('app.cancel')}</Button>
          <Button
            onClick={handleSave}
            variant="contained"
            disabled={createGroup.isPending || updateGroup.isPending}
          >
            {t('app.save')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete confirmation */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>{t('permissions.groups.deleteGroup')}</DialogTitle>
        <DialogContent>
          <Typography>
            {t('permissions.groups.deleteConfirm', { name: deleteTarget?.name })}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>{t('app.cancel')}</Button>
          <Button
            color="error"
            variant="contained"
            onClick={handleDelete}
            disabled={deleteGroup.isPending}
          >
            {t('app.delete')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* View Members dialog */}
      <Dialog open={!!viewMembersGroup} onClose={() => setViewMembersGroup(null)} maxWidth="sm" fullWidth>
        <DialogTitle>
          {t('permissions.groups.members')} — {viewMembersGroup?.name}
        </DialogTitle>
        <DialogContent>
          {membersLoading && <CircularProgress size={20} />}
          {!membersLoading && (!members || members.length === 0) && (
            <Typography variant="body2" color="text.secondary">{t('app.noData')}</Typography>
          )}
          {members && members.length > 0 && (
            <List dense>
              {members.map((m) => (
                <ListItem key={m.user_id ?? (m as { id?: string }).id}>
                  <ListItemText
                    primary={m.display_name}
                    secondary={m.email}
                  />
                </ListItem>
              ))}
            </List>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setViewMembersGroup(null)}>{t('app.close')}</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
