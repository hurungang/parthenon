/**
 * MembersPage — tenant members & invitations management (tenant admins).
 * List members, change tenant roles, suspend/remove members, and create
 * /revoke single-use invitations.  Errors use the Dialog Error Handling
 * Standard; all strings via i18next t().
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  IconButton,
  MenuItem,
  Paper,
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
import PersonAddIcon from '@mui/icons-material/PersonAdd'
import DeleteIcon from '@mui/icons-material/Delete'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import QuotaBlockedAlert from '../../components/tenant/QuotaBlockedAlert'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import {
  createInvitation,
  listInvitations,
  listMembers,
  revokeInvitation,
  updateMember,
  type TenantMember,
  type TenantRole,
} from '../../api/tenantApi'

export function MembersPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()
  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<TenantRole>('member')
  const [shownToken, setShownToken] = useState<string | null>(null)
  const [removing, setRemoving] = useState<TenantMember | null>(null)

  const membersQuery = useQuery({ queryKey: ['tenant', 'members'], queryFn: listMembers })
  const invitationsQuery = useQuery({
    queryKey: ['tenant', 'invitations'],
    queryFn: listInvitations,
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['tenant'] })
  }

  const inviteMutation = useMutation({
    mutationFn: () =>
      createInvitation({ email: inviteEmail.trim(), tenant_role: inviteRole }),
    onSuccess: (invitation) => {
      setShownToken(invitation.accept_token)
      setInviteEmail('')
      invalidate()
    },
    onError: (err) => setDialogError(err),
  })

  const revokeMutation = useMutation({
    mutationFn: revokeInvitation,
    onSuccess: invalidate,
    onError: (err) => setDialogError(err),
  })

  const memberUpdateMutation = useMutation({
    mutationFn: ({
      membershipId,
      body,
    }: {
      membershipId: string
      body: Parameters<typeof updateMember>[1]
    }) => updateMember(membershipId, body),
    onSuccess: () => {
      setRemoving(null)
      invalidate()
    },
    onError: (err) => setDialogError(err),
  })

  const members = membersQuery.data ?? []
  const invitations = (invitationsQuery.data ?? []).filter(
    (i) => i.status === 'pending',
  )

  return (
    <Box p={3}>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h5">{t('tenant.members.title')}</Typography>
        <Button
          variant="contained"
          startIcon={<PersonAddIcon />}
          onClick={() => {
            clearDialogError()
            setShownToken(null)
            setInviteOpen(true)
          }}
        >
          {t('tenant.members.invite')}
        </Button>
      </Box>

      {dialogError != null && (
        <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
      )}

      <TableContainer component={Paper} sx={{ mb: 3 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t('tenant.members.name')}</TableCell>
              <TableCell>{t('tenant.members.email')}</TableCell>
              <TableCell>{t('tenant.members.roleLabel')}</TableCell>
              <TableCell>{t('tenant.members.status')}</TableCell>
              <TableCell align="right">{t('tenant.members.remove')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {membersQuery.isLoading ? (
              <TableRow>
                <TableCell colSpan={5} align="center">
                  {t('app.loading')}
                </TableCell>
              </TableRow>
            ) : (
              members.map((member) => (
                <TableRow key={member.membership_id}>
                  <TableCell>{member.display_name ?? '—'}</TableCell>
                  <TableCell>{member.email ?? '—'}</TableCell>
                  <TableCell>
                    {member.tenant_role === 'platform_admin' ? (
                      t('tenant.members.role.platform_admin')
                    ) : (
                      <TextField
                        select
                        size="small"
                        value={member.tenant_role}
                        onChange={(e) =>
                          memberUpdateMutation.mutate({
                            membershipId: member.membership_id,
                            body: { tenant_role: e.target.value as TenantRole },
                          })
                        }
                        sx={{ minWidth: 130 }}
                      >
                        <MenuItem value="member">{t('tenant.members.role.member')}</MenuItem>
                        <MenuItem value="tenant_admin">
                          {t('tenant.members.role.tenant_admin')}
                        </MenuItem>
                      </TextField>
                    )}
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      color={member.status === 'active' ? 'success' : 'default'}
                      label={t(`tenant.members.status.${member.status}`)}
                    />
                  </TableCell>
                  <TableCell align="right">
                    {member.tenant_role !== 'platform_admin' &&
                      member.status === 'active' && (
                        <Tooltip title={t('tenant.members.remove')}>
                          <IconButton
                            size="small"
                            onClick={() => {
                              clearDialogError()
                              setRemoving(member)
                            }}
                          >
                            <DeleteIcon />
                          </IconButton>
                        </Tooltip>
                      )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>

      <Typography variant="h6" mb={1}>
        {t('tenant.members.pendingInvitations')}
      </Typography>
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t('tenant.members.email')}</TableCell>
              <TableCell>{t('tenant.members.roleLabel')}</TableCell>
              <TableCell>{t('tenant.members.expires')}</TableCell>
              <TableCell align="right">{t('tenant.members.revoke')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {invitations.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} align="center">
                  {t('tenant.members.noInvitations')}
                </TableCell>
              </TableRow>
            ) : (
              invitations.map((invitation) => (
                <TableRow key={invitation.invitation_id}>
                  <TableCell>{invitation.email}</TableCell>
                  <TableCell>
                    {t(`tenant.members.role.${invitation.tenant_role}`)}
                  </TableCell>
                  <TableCell>
                    {invitation.expires_at
                      ? new Date(invitation.expires_at).toLocaleDateString()
                      : '—'}
                  </TableCell>
                  <TableCell align="right">
                    <Button
                      size="small"
                      color="error"
                      onClick={() => {
                        clearDialogError()
                        revokeMutation.mutate(invitation.invitation_id)
                      }}
                    >
                      {t('tenant.members.revoke')}
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Invite dialog */}
      <Dialog
        open={inviteOpen}
        onClose={() => {
          setInviteOpen(false)
          setShownToken(null)
          clearDialogError()
        }}
      >
        <DialogTitle>{t('tenant.members.inviteTitle')}</DialogTitle>
        <DialogContent>
          {dialogError != null && (
            <QuotaBlockedAlert error={dialogError} fallbackMessage={t('app.error')} />
          )}
          {shownToken ? (
            <>
              <DialogContentText mb={1}>{t('tenant.members.tokenShownOnce')}</DialogContentText>
              <DialogContentText
                sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}
              >
                {shownToken}
              </DialogContentText>
            </>
          ) : (
            <>
              <TextField
                label={t('tenant.members.email')}
                type="email"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                fullWidth
                margin="normal"
                data-testid="invite-email-input"
              />
              <TextField
                select
                label={t('tenant.members.roleLabel')}
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value as TenantRole)}
                fullWidth
                margin="normal"
              >
                <MenuItem value="member">{t('tenant.members.role.member')}</MenuItem>
                <MenuItem value="tenant_admin">
                  {t('tenant.members.role.tenant_admin')}
                </MenuItem>
              </TextField>
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setInviteOpen(false)
              setShownToken(null)
              clearDialogError()
            }}
          >
            {shownToken ? t('app.close') : t('app.cancel')}
          </Button>
          {!shownToken && (
            <Button
              variant="contained"
              disabled={inviteMutation.isPending || !inviteEmail.trim()}
              onClick={() => {
                clearDialogError()
                inviteMutation.mutate()
              }}
            >
              {t('tenant.members.inviteSend')}
            </Button>
          )}
        </DialogActions>
      </Dialog>

      {/* Remove member confirmation */}
      <Dialog
        open={removing !== null}
        onClose={() => {
          setRemoving(null)
          clearDialogError()
        }}
      >
        <DialogTitle>{t('tenant.members.removeTitle')}</DialogTitle>
        <DialogContent>
          {dialogError != null && (
            <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
          )}
          <DialogContentText>
            {t('tenant.members.removeWarning', { name: removing?.email ?? '' })}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setRemoving(null)
              clearDialogError()
            }}
          >
            {t('app.cancel')}
          </Button>
          <Button
            color="error"
            disabled={memberUpdateMutation.isPending}
            onClick={() => {
              clearDialogError()
              if (removing) {
                memberUpdateMutation.mutate({
                  membershipId: removing.membership_id,
                  body: { status: 'removed' },
                })
              }
            }}
          >
            {t('tenant.members.remove')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
