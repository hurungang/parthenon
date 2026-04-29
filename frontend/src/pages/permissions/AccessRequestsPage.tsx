import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  List,
  ListItem,
  ListItemText,
  Paper,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import {
  usePendingAccessRequests,
  useMyAccessRequests,
  useApproveAccessRequest,
  useRejectAccessRequest,
  useSubmitAccessRequest,
  useGroups,
} from '../../hooks/usePermissions'
import { AccessRequestStatus } from '../../types/permissions'
import type { AccessRequest } from '../../types/permissions'

export function AccessRequestsPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useState(0)

  return (
    <Box>
      <Typography variant="h6" mb={1}>
        {t('permissions.accessRequests.title')}
      </Typography>
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)}>
          <Tab label={t('permissions.accessRequests.pendingRequests')} />
          <Tab label={t('permissions.accessRequests.myRequests')} />
        </Tabs>
      </Box>
      {tab === 0 && <PendingRequestsTab />}
      {tab === 1 && <MyRequestsTab />}
    </Box>
  )
}

// ── Pending requests (admin / group owner view) ────────────────────────────────

function PendingRequestsTab() {
  const { t } = useTranslation()
  const { data: requests, isLoading, error } = usePendingAccessRequests()
  const approve = useApproveAccessRequest()
  const reject = useRejectAccessRequest()

  const [approveTarget, setApproveTarget] = useState<AccessRequest | null>(null)
  const [rejectTarget, setRejectTarget] = useState<AccessRequest | null>(null)
  const [approvalNote, setApprovalNote] = useState('')
  const [rejectionReason, setRejectionReason] = useState('')
  const [rejectionError, setRejectionError] = useState(false)

  const handleApprove = async () => {
    if (!approveTarget) return
    await approve.mutateAsync({ requestId: approveTarget.id, reason: approvalNote || undefined })
    setApproveTarget(null)
    setApprovalNote('')
  }

  const handleReject = async () => {
    if (!rejectTarget) return
    if (!rejectionReason.trim()) { setRejectionError(true); return }
    await reject.mutateAsync({ requestId: rejectTarget.id, reason: rejectionReason })
    setRejectTarget(null)
    setRejectionReason('')
    setRejectionError(false)
  }

  if (isLoading) return <CircularProgress />
  if (error) return <Alert severity="error">{t('app.error')}</Alert>
  if (!requests?.length)
    return <Typography color="text.secondary">{t('permissions.accessRequests.noPendingRequests')}</Typography>

  return (
    <>
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t('permissions.accessRequests.requester')}</TableCell>
              <TableCell>{t('permissions.accessRequests.group')}</TableCell>
              <TableCell>{t('permissions.accessRequests.justification')}</TableCell>
              <TableCell>{t('permissions.accessRequests.requestedDate')}</TableCell>
              <TableCell>{t('app.actions')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {requests.map((req) => (
              <TableRow key={req.id}>
                <TableCell>{req.requester_display_name ?? req.user_id}</TableCell>
                <TableCell>{req.group_name ?? req.group_id}</TableCell>
                <TableCell sx={{ maxWidth: 200, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {/* justification is on the batch — shown as tooltip in full page; abbreviated here */}
                  —
                </TableCell>
                <TableCell>{new Date(req.created_at).toLocaleDateString()}</TableCell>
                <TableCell>
                  <Button
                    size="small"
                    color="success"
                    onClick={() => { setApproveTarget(req); setApprovalNote('') }}
                  >
                    {t('permissions.accessRequests.approve')}
                  </Button>
                  <Button
                    size="small"
                    color="error"
                    onClick={() => { setRejectTarget(req); setRejectionReason(''); setRejectionError(false) }}
                    sx={{ ml: 1 }}
                  >
                    {t('permissions.accessRequests.reject')}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Approve dialog */}
      <Dialog open={!!approveTarget} onClose={() => setApproveTarget(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{t('permissions.accessRequests.approve')}</DialogTitle>
        <DialogContent>
          <TextField
            label={t('permissions.accessRequests.approvalNote')}
            placeholder={t('permissions.accessRequests.approvalNotePlaceholder')}
            value={approvalNote}
            onChange={(e) => setApprovalNote(e.target.value)}
            fullWidth
            multiline
            rows={3}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setApproveTarget(null)}>{t('app.cancel')}</Button>
          <Button onClick={handleApprove} variant="contained" color="success" disabled={approve.isPending}>
            {t('permissions.accessRequests.approve')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Reject dialog */}
      <Dialog open={!!rejectTarget} onClose={() => setRejectTarget(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{t('permissions.accessRequests.reject')}</DialogTitle>
        <DialogContent>
          <TextField
            label={t('permissions.accessRequests.rejectionReason')}
            placeholder={t('permissions.accessRequests.rejectionReasonPlaceholder')}
            value={rejectionReason}
            onChange={(e) => { setRejectionReason(e.target.value); setRejectionError(false) }}
            fullWidth
            multiline
            rows={3}
            sx={{ mt: 1 }}
            error={rejectionError}
            helperText={rejectionError ? t('permissions.accessRequests.rejectionReasonRequired') : ''}
            required
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRejectTarget(null)}>{t('app.cancel')}</Button>
          <Button onClick={handleReject} variant="contained" color="error" disabled={reject.isPending}>
            {t('permissions.accessRequests.reject')}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

// ── My requests (end-user view) ────────────────────────────────────────────────

function MyRequestsTab() {
  const { t } = useTranslation()
  const { data: batches, isLoading, error } = useMyAccessRequests()
  const { data: groups } = useGroups()
  const submitRequest = useSubmitAccessRequest()

  const [requestOpen, setRequestOpen] = useState(false)
  const [selectedGroupIds, setSelectedGroupIds] = useState<string[]>([])
  const [justification, setJustification] = useState('')
  const [formErrors, setFormErrors] = useState({ groups: false, justification: false })
  const [successMsg, setSuccessMsg] = useState(false)

  const toggleGroup = (id: string) => {
    setSelectedGroupIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const handleSubmit = async () => {
    const errors = {
      groups: selectedGroupIds.length === 0,
      justification: !justification.trim(),
    }
    setFormErrors(errors)
    if (errors.groups || errors.justification) return

    await submitRequest.mutateAsync({ groupIds: selectedGroupIds, justification })
    setRequestOpen(false)
    setSelectedGroupIds([])
    setJustification('')
    setSuccessMsg(true)
    setTimeout(() => setSuccessMsg(false), 4000)
  }

  const statusColor = (status: AccessRequestStatus) => {
    if (status === AccessRequestStatus.Approved) return 'success'
    if (status === AccessRequestStatus.Rejected) return 'error'
    return 'warning'
  }

  if (isLoading) return <CircularProgress />
  if (error) return <Alert severity="error">{t('app.error')}</Alert>

  return (
    <>
      <Box display="flex" justifyContent="flex-end" mb={2}>
        <Button variant="contained" onClick={() => setRequestOpen(true)}>
          {t('permissions.accessRequests.requestAccess')}
        </Button>
      </Box>

      {successMsg && (
        <Alert severity="success" sx={{ mb: 2 }}>
          {t('permissions.accessRequests.requestSubmitted')}
        </Alert>
      )}

      {!batches?.length ? (
        <Typography color="text.secondary">
          {t('permissions.accessRequests.noMyRequests')}
        </Typography>
      ) : (
        <Stack spacing={2}>
          {batches.map((batch) => (
            <Paper key={batch.id} variant="outlined" sx={{ p: 2 }}>
              <Typography variant="caption" color="text.secondary">
                {t('permissions.accessRequests.justification')}: {batch.justification}
              </Typography>
              <List dense>
                {batch.requests.map((req) => (
                  <ListItem key={req.id} disablePadding>
                    <ListItemText
                      primary={req.group_name ?? req.group_id}
                      secondary={req.reviewer_reason}
                    />
                    <Chip
                      label={t(`permissions.accessRequests.status${req.status.charAt(0).toUpperCase()}${req.status.slice(1)}`)}
                      color={statusColor(req.status)}
                      size="small"
                    />
                  </ListItem>
                ))}
              </List>
            </Paper>
          ))}
        </Stack>
      )}

      {/* Request access dialog */}
      <Dialog open={requestOpen} onClose={() => setRequestOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{t('permissions.accessRequests.requestAccess')}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Box>
              <Typography variant="subtitle2" gutterBottom>
                {t('permissions.accessRequests.selectGroups')}
              </Typography>
              {formErrors.groups && (
                <Alert severity="error" sx={{ mb: 1 }}>
                  {t('permissions.accessRequests.selectGroupsRequired')}
                </Alert>
              )}
              <Typography variant="caption" color="text.secondary">
                {t('permissions.accessRequests.selectGroupsHint')}
              </Typography>
              <List dense sx={{ maxHeight: 200, overflow: 'auto', border: 1, borderColor: 'divider', borderRadius: 1, mt: 0.5 }}>
                {(groups ?? []).map((g) => (
                  <ListItem key={g.id} disablePadding>
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={selectedGroupIds.includes(g.id)}
                          onChange={() => toggleGroup(g.id)}
                          size="small"
                        />
                      }
                      label={g.name}
                      sx={{ px: 1, width: '100%' }}
                    />
                  </ListItem>
                ))}
              </List>
            </Box>
            <TextField
              label={t('permissions.accessRequests.justification')}
              placeholder={t('permissions.accessRequests.justificationPlaceholder')}
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              multiline
              rows={3}
              required
              error={formErrors.justification}
              helperText={formErrors.justification ? t('permissions.accessRequests.justificationRequired') : ''}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRequestOpen(false)}>{t('app.cancel')}</Button>
          <Button
            onClick={handleSubmit}
            variant="contained"
            disabled={submitRequest.isPending}
          >
            {t('permissions.accessRequests.submitRequest')}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
