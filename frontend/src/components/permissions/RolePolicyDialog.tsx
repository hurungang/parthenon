import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { useRole, useBatchSaveRolePolicies, useUpdateRole } from '../../hooks/usePermissions'
import { useUnsavedChangesDialog } from '../../hooks/useUnsavedChangesDialog'
import PermissionDeniedAlert from './PermissionDeniedAlert'
import FreeSoloResourceTypeSelect from './FreeSoloResourceTypeSelect'
import FreeSoloActionSelect from './FreeSoloActionSelect'
import { PolicyEffect } from '../../types/permissions'
import type { PolicyStatement, PolicyStatementCreate } from '../../types/permissions'

interface EditingPolicy {
  _key: number
  _state: 'unchanged' | 'modified' | 'added' | 'deleted'
  module: string
  effect: PolicyEffect
  actions: string[]
  resources: { resource_type: string; resource_id: string | null }[]
  tag_conditions: { tag_key: string; tag_value: string }[]
  originalIndex?: number
}

interface RolePolicyDialogProps {
  open: boolean
  roleId: string
  roleName: string
  onClose: () => void
  onSaved: () => void
}

interface JsonValidationResult {
  valid: boolean
  error?: string
  line?: number
  column?: number
  errors?: string[]
}

let _keyCounter = 0
function nextKey(): number {
  _keyCounter += 1
  return _keyCounter
}

function policyToEditing(policy: PolicyStatement, index: number): EditingPolicy {
  return {
    _key: nextKey(),
    _state: 'unchanged',
    module: policy.module,
    effect: policy.effect,
    actions: policy.actions.map((a) => a.action),
    resources: policy.resources.map((r) => ({
      resource_type: r.resource_type,
      resource_id: r.resource_id ?? null,
    })),
    tag_conditions: policy.tag_conditions.map((tc) => ({
      tag_key: tc.tag_key,
      tag_value: tc.tag_value,
    })),
    originalIndex: index,
  }
}

function editingToPayload(p: EditingPolicy): PolicyStatementCreate {
  return {
    effect: p.effect,
    module: p.module,
    actions: p.actions.map((a) => ({ action: a })),
    resources: p.resources,
    tag_conditions: p.tag_conditions.filter((tc) => tc.tag_key && tc.tag_value),
  }
}

function validateJsonText(jsonText: string, t: (key: string) => string): JsonValidationResult {
  try {
    const parsed = JSON.parse(jsonText)
    if (!parsed || typeof parsed !== 'object') {
      return { valid: false, error: t('permissions.roles.structureError') + ': Expected a JSON object with a "policies" array' }
    }
    if (!Array.isArray(parsed.policies)) {
      return { valid: false, error: t('permissions.roles.structureError') + ': Missing "policies" array' }
    }
    const errors: string[] = []
    parsed.policies.forEach((policy: Record<string, unknown>, index: number) => {
      if (!policy.module || typeof policy.module !== 'string') {
        errors.push(t('permissions.roles.policyIndex', { index }) + ': ' + t('permissions.roles.missingModule'))
      } else {
        const moduleStr = policy.module as string
        if (!moduleStr.includes('::') && moduleStr !== '*' && moduleStr !== '*::*') {
          errors.push(t('permissions.roles.policyIndex', { index }) + ': ' + t('permissions.roles.invalidModuleFormat'))
        }
      }
      if (!Array.isArray(policy.actions) || (policy.actions as unknown[]).length === 0) {
        errors.push(t('permissions.roles.policyIndex', { index }) + ': ' + t('permissions.roles.missingActions'))
      }
    })
    if (errors.length > 0) {
      return { valid: false, errors }
    }
    return { valid: true }
  } catch (e: unknown) {
    const err = e as SyntaxError
    return {
      valid: false,
      error: t('permissions.roles.parseError') + ': ' + err.message,
      line: (err as { lineNumber?: number }).lineNumber,
      column: (err as { columnNumber?: number }).columnNumber,
    }
  }
}

export default function RolePolicyDialog({
  open,
  roleId,
  roleName,
  onClose,
  onSaved,
}: RolePolicyDialogProps) {
  const { t } = useTranslation()
  const { data: role, isLoading } = useRole(roleId)
  const batchSave = useBatchSaveRolePolicies()
  const updateRole = useUpdateRole()

  const [policies, setPolicies] = useState<EditingPolicy[]>([])
  const [initialPolicies, setInitialPolicies] = useState<EditingPolicy[]>([])
  const [viewMode, setViewMode] = useState<'form' | 'json'>('form')
  const [jsonText, setJsonText] = useState('')
  const [jsonValidation, setJsonValidation] = useState<JsonValidationResult | null>(null)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [editingKey, setEditingKey] = useState<number | null>(null)
  const editingSnapshot = useRef<EditingPolicy | null>(null)
  const [roleNameField, setRoleNameField] = useState('')
  const [roleDescription, setRoleDescription] = useState('')
  const initialRoleName = useRef('')
  const initialRoleDescription = useRef('')

  const handleStartEdit = useCallback((policy: EditingPolicy) => {
    editingSnapshot.current = structuredClone(policy)
    setEditingKey(policy._key)
  }, [])

  const handleCancelEdit = useCallback(() => {
    if (editingKey != null && editingSnapshot.current) {
      setPolicies((prev) =>
        prev.map((p) => (p._key === editingKey ? editingSnapshot.current! : p)),
      )
    }
    editingSnapshot.current = null
    setEditingKey(null)
  }, [editingKey])

  const {
    markUnsaved,
    markSaved,
    handleClose: handleUnsavedClose,
    ConfirmationDialog,
  } = useUnsavedChangesDialog()

  useEffect(() => {
    if (open && role?.policy_statements) {
      const loaded = role.policy_statements.map((p, i) => policyToEditing(p, i))
      setPolicies(loaded)
      setInitialPolicies(structuredClone(loaded))
      setJsonText(JSON.stringify({ policies: loaded.filter((p) => p._state !== 'deleted').map(editingToPayload) }, null, 2))
      setViewMode('form')
      setJsonValidation(null)
      setDialogError(null)
      setEditingKey(null)
      editingSnapshot.current = null
      setRoleNameField(role.name || '')
      setRoleDescription(role.description || '')
      initialRoleName.current = role.name || ''
      initialRoleDescription.current = role.description || ''
      markSaved()
    }
  }, [open, role, markSaved])

  useEffect(() => {
    if (!open) return
    const changed = JSON.stringify(policies) !== JSON.stringify(initialPolicies)
      || roleNameField !== initialRoleName.current
      || roleDescription !== initialRoleDescription.current
    if (changed) {
      markUnsaved()
    } else {
      markSaved()
    }
  }, [policies, initialPolicies, open, markUnsaved, markSaved, roleNameField, roleDescription])

  const handleViewModeChange = (_e: React.MouseEvent<HTMLElement>, newMode: 'form' | 'json' | null) => {
    if (!newMode) return
    if (newMode === viewMode) return

    if (viewMode === 'form' && newMode === 'json') {
      const active = policies.filter((p) => p._state !== 'deleted')
      setJsonText(JSON.stringify({ policies: active.map(editingToPayload) }, null, 2))
      setJsonValidation(null)
      setEditingKey(null)
    }

    if (viewMode === 'json' && newMode === 'form') {
      try {
        const parsed = JSON.parse(jsonText)
        if (parsed && Array.isArray(parsed.policies)) {
          const newPolicies: EditingPolicy[] = parsed.policies.map(
            (p: PolicyStatementCreate, i: number) => ({
              _key: nextKey(),
              _state: 'modified' as const,
              module: p.module || '',
              effect: p.effect || PolicyEffect.Allow,
              actions: (p.actions || []).map((a: { action: string } | string) =>
                typeof a === 'string' ? a : a.action,
              ),
              resources: (p.resources || []).map(
                (r: { resource_type: string; resource_id?: string | null }) => ({
                  resource_type: r.resource_type || '',
                  resource_id: r.resource_id ?? null,
                }),
              ),
              tag_conditions: (p.tag_conditions || []).map(
                (tc: { tag_key: string; tag_value: string }) => ({
                  tag_key: tc.tag_key || '',
                  tag_value: tc.tag_value || '',
                }),
              ),
              originalIndex: i,
            }),
          )
          setPolicies(newPolicies)
        }
      } catch {
        // keep existing policies
      }
    }

    setViewMode(newMode)
    setJsonValidation(null)
  }

  const handleAddPolicy = () => {
    const newKey = nextKey()
    setPolicies((prev) => [
      ...prev,
      {
        _key: newKey,
        _state: 'added',
        module: '',
        effect: PolicyEffect.Allow,
        actions: [],
        resources: [],
        tag_conditions: [],
      },
    ])
    setEditingKey(newKey)
    editingSnapshot.current = null
  }

  const handleDeletePolicy = (_key: number) => {
    setPolicies((prev) => prev.map((p) => (p._key === _key ? { ...p, _state: 'deleted' as const } : p)))
    if (editingKey === _key) {
      editingSnapshot.current = null
      setEditingKey(null)
    }
  }

  const handlePolicyChange = (_key: number, field: string, value: unknown) => {
    setPolicies((prev) =>
      prev.map((p) => {
        if (p._key !== _key) return p
        return { ...p, [field]: value, _state: p._state === 'unchanged' ? 'modified' as const : p._state }
      }),
    )
  }

  const handleSave = async () => {
    let policiesToSave: PolicyStatementCreate[]

    if (viewMode === 'json') {
      const result = validateJsonText(jsonText, t)
      setJsonValidation(result)
      if (!result.valid) {
        setDialogError(new Error(t('permissions.roles.invalidJson')))
        return
      }
      try {
        const parsed = JSON.parse(jsonText)
        policiesToSave = parsed.policies as PolicyStatementCreate[]
      } catch {
        setDialogError(new Error(t('permissions.roles.invalidJson')))
        return
      }
    } else {
      policiesToSave = policies
        .filter((p) => p._state !== 'deleted')
        .map(editingToPayload)
    }

    try {
      setDialogError(null)
      await batchSave.mutateAsync({
        roleId,
        data: { policies: policiesToSave },
      })
      if (roleNameField !== initialRoleName.current || roleDescription !== initialRoleDescription.current) {
        await updateRole.mutateAsync({
          id: roleId,
          data: { name: roleNameField, description: roleDescription },
        })
        initialRoleName.current = roleNameField
        initialRoleDescription.current = roleDescription
      }
      markSaved()
      onSaved()
      onClose()
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleDialogClose = () => {
    handleUnsavedClose(() => {
      onClose()
      setDialogError(null)
    })
  }

  const visiblePolicies = useMemo(
    () => policies.filter((p) => p._state !== 'deleted'),
    [policies],
  )

  const formatCompactText = useCallback(
    (policy: EditingPolicy) => {
      const parts: string[] = []
      if (policy.effect) parts.push(`${t('permissions.roles.effect')}: ${policy.effect === PolicyEffect.Allow ? t('permissions.roles.effectAllow') : t('permissions.roles.effectDeny')}`)
      if (policy.actions.length > 0) parts.push(`${t('app.actions')}: ${policy.actions.join(', ')}`)
      if (policy.resources.length > 0) parts.push(`${t('permissions.roles.resourceIds')}: ${policy.resources.length}`)
      if (policy.tag_conditions.length > 0) parts.push(`${t('app.tags')}: ${policy.tag_conditions.length}`)
      return parts.join('  |  ')
    },
    [t],
  )

  return (
    <>
      <Dialog
        open={open}
        onClose={(_, reason) => {
          if (reason === 'backdropClick' || reason === 'escapeKeyDown') {
            handleDialogClose()
          }
        }}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          <Box display="flex" justifyContent="space-between" alignItems="center">
            <Typography variant="h6">
              {t('permissions.roles.editPolicy')} — {roleName}
            </Typography>
            <ToggleButtonGroup
              value={viewMode}
              exclusive
              onChange={handleViewModeChange}
              size="small"
            >
              <ToggleButton value="form">{t('permissions.roles.formView')}</ToggleButton>
              <ToggleButton value="json">{t('permissions.roles.jsonView')}</ToggleButton>
            </ToggleButtonGroup>
          </Box>
        </DialogTitle>

        <DialogContent>
          {dialogError != null && (
            <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
          )}

          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5, display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <InfoOutlinedIcon sx={{ fontSize: 18 }} />
            {t('permissions.roles.placeholderFeature')}
          </Typography>

          {isLoading ? (
            <Box display="flex" justifyContent="center" py={4}>
              <CircularProgress />
            </Box>
          ) : viewMode === 'form' ? (
            <Stack spacing={1.5} sx={{ mt: 1 }}>
              <Stack direction="row" spacing={2}>
                <TextField
                  size="small"
                  label={t('app.name')}
                  value={roleNameField}
                  onChange={(e) => setRoleNameField(e.target.value)}
                  disabled={role?.is_system}
                  sx={{ flex: 1 }}
                />
                <TextField
                  size="small"
                  label={t('app.description')}
                  value={roleDescription}
                  onChange={(e) => setRoleDescription(e.target.value)}
                  disabled={role?.is_system}
                  sx={{ flex: 2 }}
                />
              </Stack>
              <Divider />

              {visiblePolicies.length === 0 && (
                <Typography variant="body2" color="text.secondary">
                  {t('permissions.roles.noPolicies')}
                </Typography>
              )}

              {visiblePolicies.map((policy) => (
                <Card
                  key={policy._key}
                  variant="outlined"
                  sx={{
                    border: '1px solid',
                    borderColor: editingKey === policy._key ? 'primary.main' : 'divider',
                  }}
                >
                  {editingKey === policy._key ? (
                    <CardContent sx={{ py: 1, '&:last-child': { pb: 1 } }}>
                      <Stack spacing={1.5}>
                        <Stack direction="row" spacing={1.5} alignItems="flex-start">
                          <Box sx={{ flex: 1 }}>
                            <FreeSoloResourceTypeSelect
                              value={policy.module}
                              onChange={(val) => handlePolicyChange(policy._key, 'module', val)}
                            />
                          </Box>
                          <FormControl size="small" sx={{ minWidth: 120 }}>
                            <InputLabel>{t('permissions.roles.effect')}</InputLabel>
                            <Select
                              value={policy.effect}
                              label={t('permissions.roles.effect')}
                              onChange={(e) =>
                                handlePolicyChange(policy._key, 'effect', e.target.value)
                              }
                            >
                              <MenuItem value={PolicyEffect.Allow}>
                                {t('permissions.roles.effectAllow')}
                              </MenuItem>
                              <MenuItem value={PolicyEffect.Deny}>
                                {t('permissions.roles.effectDeny')}
                              </MenuItem>
                            </Select>
                          </FormControl>
                        </Stack>

                        <FreeSoloActionSelect
                          value={policy.actions}
                          onChange={(val) => handlePolicyChange(policy._key, 'actions', val)}
                          disabled={!policy.module}
                        />

                        {policy.resources.length > 0 && (
                          <>
                            <Divider />
                            <Typography variant="caption" color="text.secondary">
                              {t('permissions.roles.resourceIds')}
                            </Typography>
                            {policy.resources.map((res, resIdx) => (
                              <Box key={resIdx} display="flex" gap={1} alignItems="center">
                                <Typography variant="body2" sx={{ minWidth: 180, fontSize: '0.75rem', flexShrink: 0 }}>
                                  {policy.module || '...'} :
                                </Typography>
                                <TextField
                                  size="small"
                                  fullWidth
                                  placeholder={t('permissions.roles.resourceIdPlaceholder')}
                                  value={res.resource_id || ''}
                                  onChange={(e) => {
                                    const newResources = [...policy.resources]
                                    newResources[resIdx] = {
                                      resource_type: policy.module,
                                      resource_id: e.target.value || null,
                                    }
                                    handlePolicyChange(policy._key, 'resources', newResources)
                                  }}
                                />
                                <IconButton
                                  size="small"
                                  onClick={() => {
                                    const newResources = policy.resources.filter((_, i) => i !== resIdx)
                                    handlePolicyChange(policy._key, 'resources', newResources)
                                  }}
                                >
                                  <DeleteIcon fontSize="small" />
                                </IconButton>
                              </Box>
                            ))}
                          </>
                        )}

                        {policy.module && (
                          <Button
                            size="small"
                            startIcon={<AddIcon />}
                            onClick={() => {
                              const newResources = [
                                ...policy.resources,
                                { resource_type: policy.module, resource_id: null },
                              ]
                              handlePolicyChange(policy._key, 'resources', newResources)
                            }}
                          >
                            {t('permissions.roles.addResourceId')}
                          </Button>
                        )}

                        <Box display="flex" justifyContent="flex-end" gap={1}>
                          <Button size="small" onClick={handleCancelEdit}>
                            {t('app.cancel')}
                          </Button>
                          <Button size="small" variant="contained" onClick={() => setEditingKey(null)}>
                            {t('app.done')}
                          </Button>
                        </Box>
                      </Stack>
                    </CardContent>
                  ) : (
                    <CardContent sx={{ py: 1, '&:last-child': { pb: 1 } }}>
                      <Box display="flex" alignItems="center" justifyContent="space-between">
                        <Box sx={{ flex: 1, minWidth: 0 }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                            {policy.module || t('permissions.roles.newPolicy')}
                          </Typography>
                          <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.8rem' }}>
                            {formatCompactText(policy)}
                          </Typography>
                        </Box>
                        <Box display="flex" alignItems="center" ml={1} sx={{ flexShrink: 0 }}>
                          <IconButton size="small" onClick={() => handleStartEdit(policy)}>
                            <EditIcon fontSize="small" />
                          </IconButton>
                          <IconButton size="small" onClick={() => handleDeletePolicy(policy._key)}>
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </Box>
                      </Box>
                    </CardContent>
                  )}
                </Card>
              ))}

              <Button
                variant="outlined"
                startIcon={<AddIcon />}
                onClick={handleAddPolicy}
              >
                {t('permissions.roles.addPolicyRow')}
              </Button>
            </Stack>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 1 }}>
              <TextField
                multiline
                minRows={15}
                maxRows={30}
                fullWidth
                value={jsonText}
                onChange={(e) => {
                  setJsonText(e.target.value)
                  setJsonValidation(null)
                }}
                sx={{
                  fontFamily: 'monospace',
                  '& .MuiInputBase-input': {
                    fontFamily: 'monospace',
                    fontSize: '0.8rem',
                  },
                }}
              />

              {jsonValidation && !jsonValidation.valid && (
                <Alert severity="error">
                  {jsonValidation.errors ? (
                    <Stack spacing={0.5}>
                      {jsonValidation.errors.map((err, i) => (
                        <Typography key={i} variant="body2">
                          {err}
                        </Typography>
                      ))}
                    </Stack>
                  ) : (
                    <Typography variant="body2">
                      {jsonValidation.error}
                      {jsonValidation.line != null &&
                        ` (line ${jsonValidation.line}${jsonValidation.column != null ? `, col ${jsonValidation.column}` : ''})`}
                    </Typography>
                  )}
                </Alert>
              )}

              {jsonValidation?.valid && (
                <Alert severity="success">{t('permissions.roles.validJson')}</Alert>
              )}
            </Stack>
          )}
        </DialogContent>

        <DialogActions>
          <Button onClick={handleDialogClose}>{t('app.cancel')}</Button>
          <Button
            onClick={handleSave}
            variant="contained"
            disabled={batchSave.isPending}
          >
            {batchSave.isPending ? t('app.saving') : t('permissions.roles.saveBatch')}
          </Button>
        </DialogActions>
      </Dialog>
      <ConfirmationDialog />
    </>
  )
}
