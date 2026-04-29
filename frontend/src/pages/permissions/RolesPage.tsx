import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
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
import EditIcon from '@mui/icons-material/Edit'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import { useRoles, useRole, useCreateRole, useDeleteRole, useCreatePolicyStatement, useDeletePolicyStatement } from '../../hooks/usePermissions'
import { useTagDefinitions } from '../../hooks/usePermissions'
import { useTagValueOptions } from '../../hooks/useTagValueOptions'
import { PolicyEffect } from '../../types/permissions'
import type { Role } from '../../types/permissions'

export function RolesPage() {
  const { t } = useTranslation()
  const { data: roles, isLoading, error } = useRoles()
  const createRole = useCreateRole()
  const deleteRole = useDeleteRole()
  const createPolicy = useCreatePolicyStatement()

  const [addOpen, setAddOpen] = useState(false)
  const [roleForm, setRoleForm] = useState({ name: '', description: '' })
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null)
  const [forceDelete, setForceDelete] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  // Policy statement builder
  const [policyRoleId, setPolicyRoleId] = useState<string | null>(null)
  const [policyForm, setPolicyForm] = useState({
    module: '',
    effect: PolicyEffect.Allow,
    actions: [] as string[],
    actionInput: '',
    resourceIds: [] as string[],
    resourceInput: '',
    tagKey: '',
    tagValue: '',
    tagConditions: [] as { tag_key: string; tag_value: string }[],
  })
  const { data: tagDefs } = useTagDefinitions()
  const tagValueOptions = useTagValueOptions(policyForm.tagKey || null)

  const handleSaveRole = async () => {
    await createRole.mutateAsync(roleForm)
    setAddOpen(false)
    setRoleForm({ name: '', description: '' })
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

  const handleAddPolicy = async () => {
    if (!policyRoleId) return
    await createPolicy.mutateAsync({
      roleId: policyRoleId,
      data: {
        effect: policyForm.effect,
        module: policyForm.module,
        actions: policyForm.actions.map((a) => ({ action: a })),
        resources: policyForm.resourceIds.map((id) => ({
          resource_type: policyForm.module,
          resource_id: id,
        })),
        tag_conditions: policyForm.tagConditions,
      },
    })
    setPolicyRoleId(null)
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
      {error && <Alert severity="error">{t('app.error')}</Alert>}

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
                      onClick={() => setExpandedId(expandedId === role.id ? null : role.id)}
                    >
                      {expandedId === role.id ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                    </IconButton>
                  </TableCell>
                  <TableCell>{role.name}</TableCell>
                  <TableCell>{role.description ?? '—'}</TableCell>
                  <TableCell>{role.policy_count}</TableCell>
                  <TableCell>
                    <Tooltip title={t('permissions.roles.addPolicy')}>
                      <IconButton
                        size="small"
                        onClick={() => { setPolicyRoleId(role.id); setPolicyForm({ module: '', effect: PolicyEffect.Allow, actions: [], actionInput: '', resourceIds: [], resourceInput: '', tagKey: '', tagValue: '', tagConditions: [] }) }}
                      >
                        <AddIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={t('app.delete')}>
                      <IconButton
                        size="small"
                        onClick={() => { setDeleteTarget(role); setDeleteError(null); setForceDelete(false) }}
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
                        <RolePoliciesDetail roleId={role.id} />
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
      <Dialog open={addOpen} onClose={() => setAddOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{t('permissions.roles.addRole')}</DialogTitle>
        <DialogContent>
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
          <Button onClick={handleSaveRole} variant="contained" disabled={createRole.isPending}>
            {t('app.save')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Add Policy Statement dialog */}
      <Dialog open={!!policyRoleId} onClose={() => setPolicyRoleId(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{t('permissions.roles.addPolicy')}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label={t('permissions.roles.module')}
              value={policyForm.module}
              onChange={(e) => setPolicyForm((f) => ({ ...f, module: e.target.value }))}
              required
            />
            <FormControl>
              <InputLabel>{t('permissions.roles.effect')}</InputLabel>
              <Select
                value={policyForm.effect}
                label={t('permissions.roles.effect')}
                onChange={(e) => setPolicyForm((f) => ({ ...f, effect: e.target.value as PolicyEffect }))}
              >
                <MenuItem value={PolicyEffect.Allow}>{t('permissions.roles.effectAllow')}</MenuItem>
                <MenuItem value={PolicyEffect.Deny}>{t('permissions.roles.effectDeny')}</MenuItem>
              </Select>
            </FormControl>

            {/* Actions chip-add */}
            <Box>
              <Typography variant="subtitle2">{t('permissions.roles.actions')}</Typography>
              <Box display="flex" gap={1} mt={0.5}>
                <TextField
                  size="small"
                  placeholder={t('permissions.roles.addAction')}
                  value={policyForm.actionInput}
                  onChange={(e) => setPolicyForm((f) => ({ ...f, actionInput: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      const v = policyForm.actionInput.trim()
                      if (v && !policyForm.actions.includes(v))
                        setPolicyForm((f) => ({ ...f, actions: [...f.actions, v], actionInput: '' }))
                    }
                  }}
                  sx={{ flexGrow: 1 }}
                />
                <Button
                  variant="outlined"
                  onClick={() => {
                    const v = policyForm.actionInput.trim()
                    if (v && !policyForm.actions.includes(v))
                      setPolicyForm((f) => ({ ...f, actions: [...f.actions, v], actionInput: '' }))
                  }}
                >
                  {t('app.create')}
                </Button>
              </Box>
              <Box display="flex" flexWrap="wrap" gap={0.5} mt={0.5}>
                {policyForm.actions.map((a) => (
                  <Chip
                    key={a}
                    label={a}
                    onDelete={() => setPolicyForm((f) => ({ ...f, actions: f.actions.filter((x) => x !== a) }))}
                    size="small"
                  />
                ))}
              </Box>
            </Box>

            {/* Resource IDs chip-add */}
            <Box>
              <Typography variant="subtitle2">{t('permissions.roles.resourceIds')}</Typography>
              <Box display="flex" gap={1} mt={0.5}>
                <TextField
                  size="small"
                  placeholder={t('permissions.roles.resourceIdHint')}
                  value={policyForm.resourceInput}
                  onChange={(e) => setPolicyForm((f) => ({ ...f, resourceInput: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      const v = policyForm.resourceInput.trim()
                      if (v && !policyForm.resourceIds.includes(v))
                        setPolicyForm((f) => ({ ...f, resourceIds: [...f.resourceIds, v], resourceInput: '' }))
                    }
                  }}
                  sx={{ flexGrow: 1 }}
                />
                <Button
                  variant="outlined"
                  onClick={() => {
                    const v = policyForm.resourceInput.trim()
                    if (v && !policyForm.resourceIds.includes(v))
                      setPolicyForm((f) => ({ ...f, resourceIds: [...f.resourceIds, v], resourceInput: '' }))
                  }}
                >
                  {t('permissions.roles.addResourceId')}
                </Button>
              </Box>
              <Box display="flex" flexWrap="wrap" gap={0.5} mt={0.5}>
                {policyForm.resourceIds.map((r) => (
                  <Chip
                    key={r}
                    label={r}
                    onDelete={() => setPolicyForm((f) => ({ ...f, resourceIds: f.resourceIds.filter((x) => x !== r) }))}
                    size="small"
                  />
                ))}
              </Box>
            </Box>

            {/* Tag conditions */}
            <Box>
              <Typography variant="subtitle2">{t('permissions.roles.tagConditions')}</Typography>
              <Box display="flex" gap={1} mt={0.5} alignItems="center">
                <FormControl size="small" sx={{ flex: 1 }}>
                  <InputLabel>{t('permissions.roles.tagKey')}</InputLabel>
                  <Select
                    value={policyForm.tagKey}
                    label={t('permissions.roles.tagKey')}
                    onChange={(e) => setPolicyForm((f) => ({ ...f, tagKey: e.target.value, tagValue: '' }))}
                  >
                    <MenuItem value="">{t('permissions.roles.selectTagKey')}</MenuItem>
                    {(tagDefs ?? []).map((td) => (
                      <MenuItem key={td.id} value={td.key}>{td.key}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <FormControl size="small" sx={{ flex: 1 }}>
                  <InputLabel>{t('permissions.roles.tagValue')}</InputLabel>
                  <Select
                    value={policyForm.tagValue}
                    label={t('permissions.roles.tagValue')}
                    disabled={!policyForm.tagKey}
                    onChange={(e) => setPolicyForm((f) => ({ ...f, tagValue: e.target.value }))}
                  >
                    <MenuItem value="" disabled>{t('permissions.roles.selectTagValue')}</MenuItem>
                    {tagValueOptions.map((v) => (
                      <MenuItem key={v} value={v}>{v}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Button
                  variant="outlined"
                  size="small"
                  disabled={!policyForm.tagKey || !policyForm.tagValue}
                  onClick={() => {
                    setPolicyForm((f) => ({
                      ...f,
                      tagConditions: [...f.tagConditions, { tag_key: f.tagKey, tag_value: f.tagValue }],
                      tagKey: '',
                      tagValue: '',
                    }))
                  }}
                >
                  {t('app.create')}
                </Button>
              </Box>
              <Box display="flex" flexWrap="wrap" gap={0.5} mt={0.5}>
                {policyForm.tagConditions.map((tc, i) => (
                  <Chip
                    key={i}
                    label={`${tc.tag_key}=${tc.tag_value}`}
                    onDelete={() => setPolicyForm((f) => ({ ...f, tagConditions: f.tagConditions.filter((_, j) => j !== i) }))}
                    size="small"
                  />
                ))}
              </Box>
            </Box>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPolicyRoleId(null)}>{t('app.cancel')}</Button>
          <Button onClick={handleAddPolicy} variant="contained" disabled={createPolicy.isPending}>
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
              onClick={() => { setForceDelete(true); handleDelete() }}
            >
              {t('permissions.roles.forceDelete')}
            </Button>
          ) : (
            <Button color="error" variant="contained" onClick={handleDelete} disabled={deleteRole.isPending}>
              {t('app.delete')}
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  )
}

function RolePoliciesDetail({ roleId }: { roleId: string }) {
  const { t } = useTranslation()
  const { data: role, isLoading } = useRole(roleId)
  const deletePolicy = useDeletePolicyStatement()
  const createPolicy = useCreatePolicyStatement()

  const [editJsonPolicy, setEditJsonPolicy] = useState<import('../../types/permissions').PolicyStatement | null>(null)
  const [jsonValue, setJsonValue] = useState('')
  const [jsonError, setJsonError] = useState<string | null>(null)
  const [addActionForPolicy, setAddActionForPolicy] = useState<import('../../types/permissions').PolicyStatement | null>(null)
  const [newActionInput, setNewActionInput] = useState('')

  const openEditJson = (policy: import('../../types/permissions').PolicyStatement) => {
    setEditJsonPolicy(policy)
    setJsonValue(JSON.stringify({
      effect: policy.effect,
      module: policy.module,
      actions: policy.actions.map((a) => ({ action: a.action })),
      resources: policy.resources.map((r) => ({ resource_type: r.resource_type, resource_id: r.resource_id })),
      tag_conditions: policy.tag_conditions.map((tc) => ({ tag_key: tc.tag_key, tag_value: tc.tag_value })),
    }, null, 2))
    setJsonError(null)
  }

  const handleSaveJson = async () => {
    if (!editJsonPolicy) return
    try {
      const parsed = JSON.parse(jsonValue)
      await deletePolicy.mutateAsync({ roleId, policyId: editJsonPolicy.id })
      await createPolicy.mutateAsync({ roleId, data: parsed })
      setEditJsonPolicy(null)
    } catch {
      setJsonError(t('permissions.roles.invalidJson'))
    }
  }

  const handleDeleteAction = async (policy: import('../../types/permissions').PolicyStatement, actionId: string) => {
    const data = {
      effect: policy.effect,
      module: policy.module,
      actions: policy.actions.filter((a) => a.id !== actionId).map((a) => ({ action: a.action })),
      resources: policy.resources.map((r) => ({ resource_type: r.resource_type, resource_id: r.resource_id })),
      tag_conditions: policy.tag_conditions.map((tc) => ({ tag_key: tc.tag_key, tag_value: tc.tag_value })),
    }
    await deletePolicy.mutateAsync({ roleId, policyId: policy.id })
    await createPolicy.mutateAsync({ roleId, data })
  }

  const handleAddAction = async (policy: import('../../types/permissions').PolicyStatement) => {
    const action = newActionInput.trim()
    if (!action) return
    const data = {
      effect: policy.effect,
      module: policy.module,
      actions: [...policy.actions.map((a) => ({ action: a.action })), { action }],
      resources: policy.resources.map((r) => ({ resource_type: r.resource_type, resource_id: r.resource_id })),
      tag_conditions: policy.tag_conditions.map((tc) => ({ tag_key: tc.tag_key, tag_value: tc.tag_value })),
    }
    await deletePolicy.mutateAsync({ roleId, policyId: policy.id })
    await createPolicy.mutateAsync({ roleId, data })
    setAddActionForPolicy(null)
    setNewActionInput('')
  }

  if (isLoading) return <CircularProgress size={16} />
  if (!role?.policies?.length)
    return <Typography variant="body2" sx={{ p: 1 }}>{t('app.noData')}</Typography>
  return (
    <Box sx={{ p: 1 }}>
      {role.policies.map((policy) => (
        <Paper key={policy.id} variant="outlined" sx={{ p: 1, mb: 1 }}>
          <Box display="flex" justifyContent="space-between" alignItems="flex-start">
            <Typography variant="caption" color="text.secondary">
              {t('permissions.roles.effect')}: <strong>{policy.effect}</strong> |{' '}
              {t('permissions.roles.module')}: <strong>{policy.module}</strong>
            </Typography>
            <Button
              size="small"
              variant="outlined"
              startIcon={<EditIcon fontSize="small" />}
              onClick={() => openEditJson(policy)}
            >
              {t('permissions.roles.editAsJson')}
            </Button>
          </Box>
          <Box mt={0.5} display="flex" flexWrap="wrap" gap={0.5} alignItems="center">
            {policy.actions.map((a) => (
              <Chip
                key={a.id}
                label={a.action}
                size="small"
                onDelete={() => handleDeleteAction(policy, a.id)}
              />
            ))}
            <Button
              size="small"
              variant="text"
              startIcon={<AddIcon fontSize="small" />}
              onClick={() => { setAddActionForPolicy(policy); setNewActionInput('') }}
            >
              {t('permissions.roles.addAction')}
            </Button>
          </Box>
          {addActionForPolicy?.id === policy.id && (
            <Box display="flex" gap={1} mt={1} alignItems="center">
              <TextField
                size="small"
                value={newActionInput}
                onChange={(e) => setNewActionInput(e.target.value)}
                placeholder={t('permissions.roles.addAction')}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void handleAddAction(policy) } }}
                sx={{ flexGrow: 1 }}
              />
              <Button size="small" variant="contained" onClick={() => handleAddAction(policy)}>
                {t('app.save')}
              </Button>
              <Button size="small" onClick={() => setAddActionForPolicy(null)}>
                {t('app.cancel')}
              </Button>
            </Box>
          )}
        </Paper>
      ))}

      {/* Edit as JSON dialog */}
      <Dialog open={!!editJsonPolicy} onClose={() => setEditJsonPolicy(null)} maxWidth="md" fullWidth>
        <DialogTitle>{t('permissions.roles.editPolicy')}</DialogTitle>
        <DialogContent>
          {jsonError && <Alert severity="error" sx={{ mb: 1 }}>{jsonError}</Alert>}
          <TextField
            multiline
            fullWidth
            rows={16}
            value={jsonValue}
            onChange={(e) => setJsonValue(e.target.value)}
            inputProps={{ style: { fontFamily: 'monospace', fontSize: 13 } }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditJsonPolicy(null)}>{t('app.cancel')}</Button>
          <Button
            variant="contained"
            onClick={handleSaveJson}
            disabled={deletePolicy.isPending || createPolicy.isPending}
          >
            {t('app.save')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
