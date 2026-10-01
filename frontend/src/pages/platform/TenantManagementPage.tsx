/**
 * TenantManagementPage — platform admin tenant console.
 *
 * Lists tenants with status/lifecycle/admin contact + license tier and
 * usage columns, create + edit dialogs, license assignment dialog
 * (tier select pre-filling editable limit fields; assign / change /
 * remove with explicit free-fallback confirmation), and
 * suspend/resume/delete actions with confirmation.  Delete requires
 * typing the tenant address (slug).  All errors surface per the Dialog
 * Error Handling Standard (dialogError + PermissionDeniedAlert).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
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
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import PauseCircleIcon from '@mui/icons-material/PauseCircle'
import PlayCircleIcon from '@mui/icons-material/PlayCircle'
import RefreshIcon from '@mui/icons-material/Refresh'
import WorkspacePremiumIcon from '@mui/icons-material/WorkspacePremium'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import {
  assignTenantLicense,
  createTenant,
  deleteTenant,
  listTenants,
  removeTenantLicense,
  resumeTenant,
  suspendTenant,
  updateTenant,
  type Tenant,
  type TenantStatus,
} from '../../api/platformAdminApi'
import type { LicenseTier } from '../../types'

const STATUS_COLOR: Record<TenantStatus, 'success' | 'warning' | 'default'> = {
  active: 'success',
  suspended: 'warning',
  deleted: 'default',
}

/** Per-tier limit presets used to pre-fill (editable) limit fields. */
const TIER_PRESETS: Record<LicenseTier, { users: number; agentTypes: number; executions: number }> = {
  free: { users: 10, agentTypes: 5, executions: 100 },
  team: { users: 25, agentTypes: 15, executions: 1000 },
  enterprise: { users: 100, agentTypes: 50, executions: 10000 },
}

const TIER_COLOR: Record<LicenseTier, 'default' | 'primary' | 'secondary'> = {
  free: 'default',
  team: 'primary',
  enterprise: 'secondary',
}

interface TenantDialogState {
  open: boolean
  mode: 'create' | 'edit'
  tenant: Tenant | null
}

export function TenantManagementPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [dialog, setDialog] = useState<TenantDialogState>({ open: false, mode: 'create', tenant: null })
  const [deleteTarget, setDeleteTarget] = useState<Tenant | null>(null)
  const [confirmSlug, setConfirmSlug] = useState('')
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()
  const [pageError, setPageError] = useState<unknown>(null)

  const tenantsQuery = useQuery({
    queryKey: ['platform', 'tenants'],
    queryFn: () => listTenants(),
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['platform', 'tenants'] })
  }

  const refresh = () => {
    clearDialogError()
    void tenantsQuery.refetch()
  }

  // ── Mutations ────────────────────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: createTenant,
    onSuccess: () => {
      setDialog({ open: false, mode: 'create', tenant: null })
      invalidate()
    },
    onError: (err) => setDialogError(err),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof updateTenant>[1] }) =>
      updateTenant(id, body),
    onSuccess: () => {
      setDialog({ open: false, mode: 'create', tenant: null })
      invalidate()
    },
    onError: (err) => setDialogError(err),
  })

  const suspendMutation = useMutation({
    mutationFn: suspendTenant,
    onSuccess: invalidate,
    onError: (err) => setPageError(err),
  })

  const resumeMutation = useMutation({
    mutationFn: resumeTenant,
    onSuccess: invalidate,
    onError: (err) => setPageError(err),
  })

  const deleteMutation = useMutation({
    mutationFn: ({ id, slug }: { id: string; slug: string }) => deleteTenant(id, slug),
    onSuccess: () => {
      setDeleteTarget(null)
      setConfirmSlug('')
      invalidate()
    },
    onError: (err) => setDialogError(err),
  })

  // ── License dialog state (Phase 10) ──────────────────────────────────────
  const [licenseTarget, setLicenseTarget] = useState<Tenant | null>(null)
  const [licenseTier, setLicenseTier] = useState<LicenseTier>('free')
  const [licenseUsers, setLicenseUsers] = useState<number>(TIER_PRESETS.free.users)
  const [licenseAgentTypes, setLicenseAgentTypes] = useState<number>(TIER_PRESETS.free.agentTypes)
  const [licenseExecutions, setLicenseExecutions] = useState<number>(TIER_PRESETS.free.executions)
  const [removingLicense, setRemovingLicense] = useState(false)

  const licenseMutation = useMutation({
    mutationFn: () =>
      assignTenantLicense(licenseTarget!.id, {
        tier: licenseTier,
        max_users: licenseUsers,
        max_agent_types: licenseAgentTypes,
        monthly_agent_executions: licenseExecutions,
      }),
    onSuccess: () => {
      setLicenseTarget(null)
      invalidate()
    },
    onError: (err) => setDialogError(err),
  })

  const removeLicenseMutation = useMutation({
    mutationFn: () => removeTenantLicense(licenseTarget!.id),
    onSuccess: () => {
      setLicenseTarget(null)
      setRemovingLicense(false)
      invalidate()
    },
    onError: (err) => setDialogError(err),
  })

  const openLicenseDialog = (tenant: Tenant) => {
    clearDialogError()
    setRemovingLicense(false)
    setLicenseTarget(tenant)
    const tier: LicenseTier = tenant.license?.tier ?? 'free'
    setLicenseTier(tier)
    setLicenseUsers(tenant.license?.max_users ?? TIER_PRESETS[tier].users)
    setLicenseAgentTypes(tenant.license?.max_agent_types ?? TIER_PRESETS[tier].agentTypes)
    setLicenseExecutions(tenant.license?.monthly_agent_executions ?? TIER_PRESETS[tier].executions)
  }

  const handleTierChange = (tier: LicenseTier) => {
    setLicenseTier(tier)
    // Pre-fill limit fields with the tier's presets (still editable)
    setLicenseUsers(TIER_PRESETS[tier].users)
    setLicenseAgentTypes(TIER_PRESETS[tier].agentTypes)
    setLicenseExecutions(TIER_PRESETS[tier].executions)
  }

  const licenseInputsValid =
    licenseUsers > 0 && licenseAgentTypes > 0 && licenseExecutions > 0

  const tenants: Tenant[] = tenantsQuery.data?.items ?? []

  return (
    <Box p={3}>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h5">{t('platform.tenants.title')}</Typography>
        <Box>
          <Tooltip title={t('app.refresh')}>
            <IconButton onClick={refresh} aria-label="refresh">
              <RefreshIcon />
            </IconButton>
          </Tooltip>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => {
              clearDialogError()
              setDialog({ open: true, mode: 'create', tenant: null })
            }}
            sx={{ ml: 1 }}
          >
            {t('platform.tenants.create')}
          </Button>
        </Box>
      </Box>

      {pageError != null && <PermissionDeniedAlert error={pageError} fallbackMessage={t('app.error')} />}

      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t('platform.tenants.name')}</TableCell>
              <TableCell>{t('platform.tenants.slug')}</TableCell>
              <TableCell>{t('platform.tenants.status')}</TableCell>
              <TableCell>{t('platform.tenants.tier')}</TableCell>
              <TableCell>{t('platform.tenants.usage')}</TableCell>
              <TableCell>{t('platform.tenants.adminContact')}</TableCell>
              <TableCell>{t('platform.tenants.created')}</TableCell>
              <TableCell align="right">{t('platform.tenants.actions')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {tenantsQuery.isLoading ? (
              <TableRow>
                <TableCell colSpan={8} align="center">
                  <CircularProgress size={24} />
                </TableCell>
              </TableRow>
            ) : (
              tenants.map((tenant) => (
                <TableRow key={tenant.id} data-testid={`tenant-row-${tenant.slug}`}>
                  <TableCell>
                    {tenant.name}
                    {tenant.is_system_tenant && (
                      <Chip size="small" label={t('platform.tenants.system')} sx={{ ml: 1 }} />
                    )}
                  </TableCell>
                  <TableCell>{tenant.slug}</TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      color={STATUS_COLOR[tenant.status]}
                      label={t(`platform.tenants.status.${tenant.status}`)}
                    />
                  </TableCell>
                  <TableCell data-testid={`tenant-tier-${tenant.slug}`}>
                    <Chip
                      size="small"
                      color={TIER_COLOR[tenant.usage?.tier ?? 'free']}
                      label={t(`platform.tenants.tierValue.${tenant.usage?.tier ?? 'free'}`)}
                    />
                  </TableCell>
                  <TableCell data-testid={`tenant-usage-${tenant.slug}`}>
                    {tenant.usage
                      ? t('platform.tenants.usageSummary', {
                          users: tenant.usage.users,
                          maxUsers: tenant.usage.max_users,
                          agentTypes: tenant.usage.agent_types,
                          maxAgentTypes: tenant.usage.max_agent_types,
                          executions: tenant.usage.executions_this_month,
                          maxExecutions: tenant.usage.monthly_agent_executions,
                        })
                      : '—'}
                  </TableCell>
                  <TableCell>
                    {tenant.admin_contact_name || '—'}
                    {tenant.admin_contact_email ? ` (${tenant.admin_contact_email})` : ''}
                  </TableCell>
                  <TableCell>
                    {tenant.created_at ? new Date(tenant.created_at).toLocaleDateString() : '—'}
                  </TableCell>
                  <TableCell align="right">
                    <Tooltip title={t('platform.tenants.license')}>
                      <IconButton
                        size="small"
                        aria-label={`license-${tenant.slug}`}
                        data-testid={`license-button-${tenant.slug}`}
                        onClick={() => openLicenseDialog(tenant)}
                      >
                        <WorkspacePremiumIcon />
                      </IconButton>
                    </Tooltip>
                    {tenant.status === 'active' && !tenant.is_system_tenant && (
                      <Tooltip title={t('platform.tenants.suspend')}>
                        <IconButton
                          size="small"
                          aria-label={`suspend-${tenant.slug}`}
                          onClick={() =>
                            suspendMutation.mutate(tenant.id, { onError: (err) => setPageError(err) })
                          }
                        >
                          <PauseCircleIcon />
                        </IconButton>
                      </Tooltip>
                    )}
                    {tenant.status === 'suspended' && (
                      <Tooltip title={t('platform.tenants.resume')}>
                        <IconButton
                          size="small"
                          aria-label={`resume-${tenant.slug}`}
                          onClick={() => resumeMutation.mutate(tenant.id)}
                        >
                          <PlayCircleIcon />
                        </IconButton>
                      </Tooltip>
                    )}
                    <Tooltip title={t('platform.tenants.edit')}>
                      <IconButton
                        size="small"
                        aria-label={`edit-${tenant.slug}`}
                        onClick={() => {
                          clearDialogError()
                          setDialog({ open: true, mode: 'edit', tenant })
                        }}
                      >
                        <EditIcon />
                      </IconButton>
                    </Tooltip>
                    {!tenant.is_system_tenant && (
                      <Tooltip title={t('platform.tenants.delete')}>
                        <IconButton
                          size="small"
                          aria-label={`delete-${tenant.slug}`}
                          onClick={() => {
                            clearDialogError()
                            setConfirmSlug('')
                            setDeleteTarget(tenant)
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

      {/* Create / Edit dialog */}
      <TenantFormDialog
        dialog={dialog}
        creating={createMutation.isPending}
        saving={updateMutation.isPending}
        dialogError={dialogError}
        clearDialogError={clearDialogError}
        onClose={() => setDialog({ open: false, mode: 'create', tenant: null })}
        onSubmit={(values) => {
          if (dialog.mode === 'create') {
            createMutation.mutate(values.create!)
          } else if (dialog.tenant) {
            updateMutation.mutate({ id: dialog.tenant.id, body: values.update! })
          }
        }}
      />

      {/* Delete confirmation dialog — confirm by typing the tenant address */}
      <Dialog
        open={deleteTarget !== null}
        onClose={() => {
          setDeleteTarget(null)
          setConfirmSlug('')
          clearDialogError()
        }}
      >
        <DialogTitle>{t('platform.tenants.deleteTitle')}</DialogTitle>
        <DialogContent>
          {dialogError != null && (
            <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
          )}
          <DialogContentText mb={2}>
            {t('platform.tenants.deleteWarning', { name: deleteTarget?.name ?? '' })}
          </DialogContentText>
          <DialogContentText mb={1}>
            {t('platform.tenants.deleteConfirmPrompt', { slug: deleteTarget?.slug ?? '' })}
          </DialogContentText>
          <TextField
            size="small"
            fullWidth
            value={confirmSlug}
            onChange={(e) => setConfirmSlug(e.target.value)}
            data-testid="delete-confirm-input"
          />
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setDeleteTarget(null)
              setConfirmSlug('')
              clearDialogError()
            }}
          >
            {t('app.cancel')}
          </Button>
          <Button
            color="error"
            disabled={confirmSlug !== deleteTarget?.slug || deleteMutation.isPending}
            onClick={() => {
              clearDialogError()
              if (deleteTarget) {
                deleteMutation.mutate({ id: deleteTarget.id, slug: deleteTarget.slug })
              }
            }}
          >
            {t('platform.tenants.delete')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* License assignment dialog (Phase 10) — tier select pre-fills
          editable limit fields; assign / change / remove with explicit
          free-fallback confirmation */}
      <Dialog
        open={licenseTarget !== null}
        onClose={() => {
          setLicenseTarget(null)
          setRemovingLicense(false)
          clearDialogError()
        }}
        maxWidth="sm"
        fullWidth
        data-testid="license-dialog"
      >
        <DialogTitle>
          {t('platform.tenants.licenseTitle', { name: licenseTarget?.name ?? '' })}
        </DialogTitle>
        <DialogContent>
          {dialogError != null && (
            <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
          )}
          {removingLicense ? (
            <>
              <DialogContentText mb={2}>
                {t('platform.tenants.licenseRemoveWarning', {
                  tier: t(`platform.tenants.tierValue.${licenseTarget?.license?.tier ?? 'free'}`),
                })}
              </DialogContentText>
              <DialogContentText>
                {t('platform.tenants.licenseRemoveFallback')}
              </DialogContentText>
            </>
          ) : (
            <>
              <DialogContentText mb={2}>
                {t('platform.tenants.licenseHelp')}
              </DialogContentText>
              <TextField
                select
                label={t('platform.tenants.licenseTier')}
                value={licenseTier}
                onChange={(e) => handleTierChange(e.target.value as LicenseTier)}
                fullWidth
                margin="normal"
                data-testid="license-tier-select"
              >
                {(Object.keys(TIER_PRESETS) as LicenseTier[]).map((tier) => (
                  <MenuItem key={tier} value={tier}>
                    {t(`platform.tenants.tierValue.${tier}`)}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                label={t('platform.tenants.maxUsers')}
                type="number"
                value={licenseUsers}
                onChange={(e) => setLicenseUsers(Number(e.target.value))}
                fullWidth
                margin="normal"
                inputProps={{ min: 1 }}
                error={licenseUsers <= 0}
                data-testid="license-max-users"
              />
              <TextField
                label={t('platform.tenants.maxAgentTypes')}
                type="number"
                value={licenseAgentTypes}
                onChange={(e) => setLicenseAgentTypes(Number(e.target.value))}
                fullWidth
                margin="normal"
                inputProps={{ min: 1 }}
                error={licenseAgentTypes <= 0}
                data-testid="license-max-agent-types"
              />
              <TextField
                label={t('platform.tenants.monthlyExecutions')}
                type="number"
                value={licenseExecutions}
                onChange={(e) => setLicenseExecutions(Number(e.target.value))}
                fullWidth
                margin="normal"
                inputProps={{ min: 1 }}
                error={licenseExecutions <= 0}
                data-testid="license-monthly-executions"
              />
            </>
          )}
        </DialogContent>
        <DialogActions>
          {removingLicense ? (
            <>
              <Button
                onClick={() => {
                  setRemovingLicense(false)
                  clearDialogError()
                }}
              >
                {t('app.cancel')}
              </Button>
              <Button
                color="error"
                disabled={removeLicenseMutation.isPending}
                data-testid="license-remove-confirm"
                onClick={() => removeLicenseMutation.mutate()}
              >
                {t('platform.tenants.licenseRemoveConfirm')}
              </Button>
            </>
          ) : (
            <>
              {licenseTarget?.license && (
                <Button
                  color="error"
                  disabled={licenseMutation.isPending || removeLicenseMutation.isPending}
                  data-testid="license-remove-button"
                  onClick={() => {
                    clearDialogError()
                    setRemovingLicense(true)
                  }}
                >
                  {t('platform.tenants.licenseRemove')}
                </Button>
              )}
              <Button
                onClick={() => {
                  setLicenseTarget(null)
                  clearDialogError()
                }}
              >
                {t('app.cancel')}
              </Button>
              <Button
                variant="contained"
                disabled={!licenseInputsValid || licenseMutation.isPending}
                data-testid="license-save-button"
                onClick={() => licenseMutation.mutate()}
              >
                {licenseTarget?.license
                  ? t('platform.tenants.licenseChange')
                  : t('platform.tenants.licenseAssign')}
              </Button>
            </>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  )
}

// ── Create/Edit form dialog ─────────────────────────────────────────────────

interface TenantFormDialogProps {
  dialog: TenantDialogState
  creating: boolean
  saving: boolean
  dialogError: unknown
  clearDialogError: () => void
  onClose: () => void
  onSubmit: (values: {
    create?: Parameters<typeof createTenant>[0]
    update?: Parameters<typeof updateTenant>[1]
  }) => void
}

function TenantFormDialog({
  dialog,
  creating,
  saving,
  dialogError,
  clearDialogError,
  onClose,
  onSubmit,
}: TenantFormDialogProps) {
  const { t } = useTranslation()
  const editing = dialog.mode === 'edit' ? dialog.tenant : null
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [contactName, setContactName] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [initializedFor, setInitializedFor] = useState<string | null>(null)

  // Re-seed fields when the dialog target changes
  if (dialog.open && initializedFor !== (editing?.id ?? '__create__')) {
    setName(editing?.name ?? '')
    setSlug(editing?.slug ?? '')
    setContactName(editing?.admin_contact_name ?? '')
    setContactEmail(editing?.admin_contact_email ?? '')
    setInitializedFor(editing?.id ?? '__create__')
  }

  return (
    <Dialog
      open={dialog.open}
      onClose={() => {
        onClose()
        clearDialogError()
        setInitializedFor(null)
      }}
    >
      <DialogTitle>
        {editing ? t('platform.tenants.editTitle') : t('platform.tenants.createTitle')}
      </DialogTitle>
      <DialogContent>
        {dialogError != null && (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        )}
        <TextField
          label={t('platform.tenants.name')}
          value={name}
          onChange={(e) => setName(e.target.value)}
          fullWidth
          margin="normal"
          data-testid="tenant-name-input"
        />
        <TextField
          label={t('platform.tenants.slug')}
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          fullWidth
          margin="normal"
          disabled={editing !== null}
          helperText={t('platform.tenants.slugHelp')}
          data-testid="tenant-slug-input"
        />
        <TextField
          label={t('platform.tenants.adminContactName')}
          value={contactName}
          onChange={(e) => setContactName(e.target.value)}
          fullWidth
          margin="normal"
        />
        <TextField
          label={t('platform.tenants.adminContactEmail')}
          value={contactEmail}
          onChange={(e) => setContactEmail(e.target.value)}
          fullWidth
          margin="normal"
          type="email"
        />
      </DialogContent>
      <DialogActions>
        <Button
          onClick={() => {
            onClose()
            clearDialogError()
            setInitializedFor(null)
          }}
        >
          {t('app.cancel')}
        </Button>
        <Button
          variant="contained"
          disabled={creating || saving || !name.trim() || (!editing && !slug.trim())}
          onClick={() =>
            editing
              ? onSubmit({
                  update: {
                    name: name.trim(),
                    admin_contact_name: contactName.trim() || null,
                    admin_contact_email: contactEmail.trim() || null,
                  },
                })
              : onSubmit({
                  create: {
                    name: name.trim(),
                    slug: slug.trim().toLowerCase(),
                    admin_contact_name: contactName.trim() || null,
                    admin_contact_email: contactEmail.trim() || null,
                  },
                })
          }
        >
          {(creating || saving) && <CircularProgress size={16} sx={{ mr: 1 }} />}
          {t('app.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
