import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  List,
  ListItem,
  ListItemText,
  MenuItem,
  Select,
  Tab,
  Tabs,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import DeleteIcon from '@mui/icons-material/Delete'
import {
  usePlatformUser,
  useRoles,
  useGroups,
  useAssignUserRole,
  useRemoveUserRole,
  useAddUserToGroup,
  useRemoveUserFromGroup,
} from '../../hooks/usePermissions'

interface ManageAccessModalProps {
  userId: string
  displayName: string
  open: boolean
  onClose: () => void
}

/**
 * Tabbed modal for managing a user's direct roles and group memberships.
 */
export function ManageAccessModal({ userId, displayName, open, onClose }: ManageAccessModalProps) {
  const { t } = useTranslation()
  const [tab, setTab] = useState(0)

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        {t('permissions.users.manageAccess')} — {displayName}
        <IconButton onClick={onClose} size="small">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <Box sx={{ borderBottom: 1, borderColor: 'divider', px: 3 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)}>
          <Tab label={t('permissions.users.directRoles')} />
          <Tab label={t('permissions.users.groupMemberships')} />
        </Tabs>
      </Box>
      <DialogContent>
        {tab === 0 && <DirectRolesTab userId={userId} />}
        {tab === 1 && <GroupMembershipsTab userId={userId} />}
      </DialogContent>
    </Dialog>
  )
}

// ── Direct Roles tab ───────────────────────────────────────────────────────────

function DirectRolesTab({ userId }: { userId: string }) {
  const { t } = useTranslation()
  const { data: user, isLoading } = usePlatformUser(userId)
  const { data: allRoles } = useRoles()
  const assignRole = useAssignUserRole()
  const removeRole = useRemoveUserRole()

  const [selectedRoleId, setSelectedRoleId] = useState('')

  const assignedRoleIds = new Set((user?.direct_roles ?? []).map((r) => r.id))
  const availableRoles = (allRoles ?? []).filter((r) => !assignedRoleIds.has(r.id))

  if (isLoading) return <CircularProgress />

  return (
    <Box>
      {/* Current direct roles */}
      {!(user?.direct_roles?.length) ? (
        <Typography color="text.secondary" variant="body2" mb={2}>
          {t('app.noData')}
        </Typography>
      ) : (
        <List dense sx={{ mb: 2 }}>
          {user.direct_roles.map((role) => (
            <ListItem
              key={role.id}
              secondaryAction={
                <IconButton
                  edge="end"
                  size="small"
                  onClick={() => removeRole.mutate({ userId, roleId: role.id })}
                >
                  <DeleteIcon fontSize="small" />
                </IconButton>
              }
            >
              <ListItemText primary={role.name} secondary={role.description} />
            </ListItem>
          ))}
        </List>
      )}

      {/* Assign new role */}
      <Box display="flex" gap={1} alignItems="center">
        <FormControl size="small" sx={{ flex: 1 }}>
          <InputLabel>{t('permissions.users.assignRole')}</InputLabel>
          <Select
            value={selectedRoleId}
            label={t('permissions.users.assignRole')}
            onChange={(e) => setSelectedRoleId(e.target.value)}
          >
            {availableRoles.map((r) => (
              <MenuItem key={r.id} value={r.id}>{r.name}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <Button
          variant="contained"
          disabled={!selectedRoleId || assignRole.isPending}
          onClick={() => {
            assignRole.mutate({ userId, roleId: selectedRoleId })
            setSelectedRoleId('')
          }}
        >
          {t('permissions.users.assignRole')}
        </Button>
      </Box>
    </Box>
  )
}

// ── Group Memberships tab ──────────────────────────────────────────────────────

function GroupMembershipsTab({ userId }: { userId: string }) {
  const { t } = useTranslation()
  const { data: user, isLoading } = usePlatformUser(userId)
  const { data: allGroups } = useGroups()
  const addToGroup = useAddUserToGroup()
  const removeFromGroup = useRemoveUserFromGroup()

  const [selectedGroupId, setSelectedGroupId] = useState('')

  const memberGroupIds = new Set((user?.group_memberships ?? []).map((m) => m.group_id))
  const availableGroups = (allGroups ?? []).filter((g) => !memberGroupIds.has(g.id))

  if (isLoading) return <CircularProgress />

  return (
    <Box>
      {/* Current memberships */}
      {!(user?.group_memberships?.length) ? (
        <Typography color="text.secondary" variant="body2" mb={2}>
          {t('app.noData')}
        </Typography>
      ) : (
        <List dense sx={{ mb: 2 }}>
          {user.group_memberships.map((m) => (
            <ListItem
              key={m.group_id}
              secondaryAction={
                <IconButton
                  edge="end"
                  size="small"
                  onClick={() => removeFromGroup.mutate({ userId, groupId: m.group_id })}
                >
                  <DeleteIcon fontSize="small" />
                </IconButton>
              }
            >
              <ListItemText primary={m.group_name} secondary={m.joined_at ? new Date(m.joined_at).toLocaleDateString() : ''} />
            </ListItem>
          ))}
        </List>
      )}

      {/* Add to group */}
      <Box display="flex" gap={1} alignItems="center">
        <FormControl size="small" sx={{ flex: 1 }}>
          <InputLabel>{t('permissions.users.addToGroup')}</InputLabel>
          <Select
            value={selectedGroupId}
            label={t('permissions.users.addToGroup')}
            onChange={(e) => setSelectedGroupId(e.target.value)}
          >
            {availableGroups.map((g) => (
              <MenuItem key={g.id} value={g.id}>{g.name}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <Button
          variant="contained"
          disabled={!selectedGroupId || addToGroup.isPending}
          onClick={() => {
            addToGroup.mutate({ userId, groupId: selectedGroupId })
            setSelectedGroupId('')
          }}
        >
          {t('permissions.users.addToGroup')}
        </Button>
      </Box>
    </Box>
  )
}
