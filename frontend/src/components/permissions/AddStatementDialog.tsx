import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'
import AddIcon from '@mui/icons-material/Add'
import {
  useTagDefinitions,
  useCreatePolicyStatement,
  useUpdatePolicyStatement,
} from '../../hooks/usePermissions'
import { useTagValueOptions } from '../../hooks/useTagValueOptions'
import PermissionDeniedAlert from './PermissionDeniedAlert'
import FreeSoloResourceTypeSelect from './FreeSoloResourceTypeSelect'
import FreeSoloActionSelect from './FreeSoloActionSelect'
import { PolicyEffect } from '../../types/permissions'
import type { PolicyStatement } from '../../types/permissions'

interface TagConditionRow {
  tag_key: string
  tag_value: string
}

interface AddStatementDialogProps {
  open: boolean
  roleId: string
  editingPolicy?: PolicyStatement | null
  onClose: () => void
}

function TagConditionRowEditor({
  row,
  index,
  onChange,
  onRemove,
}: {
  row: TagConditionRow
  index: number
  onChange: (index: number, field: 'tag_key' | 'tag_value', value: string) => void
  onRemove: (index: number) => void
}) {
  const { t } = useTranslation()
  const { data: tagDefs } = useTagDefinitions()
  const valueOptions = useTagValueOptions(row.tag_key || null)

  return (
    <Box display="flex" gap={1} alignItems="center">
      <FormControl size="small" sx={{ flex: 1 }}>
        <InputLabel>{t('permissions.roles.tagKey')}</InputLabel>
        <Select
          value={row.tag_key}
          label={t('permissions.roles.tagKey')}
          onChange={(e) => onChange(index, 'tag_key', e.target.value)}
        >
          <MenuItem value="">{t('permissions.roles.selectTagKey')}</MenuItem>
          {(tagDefs ?? []).map((td) => (
            <MenuItem key={td.id} value={td.key}>
              {td.key}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      <FormControl size="small" sx={{ flex: 1 }}>
        <InputLabel>{t('permissions.roles.tagValue')}</InputLabel>
        <Select
          value={row.tag_value}
          label={t('permissions.roles.tagValue')}
          disabled={!row.tag_key}
          onChange={(e) => onChange(index, 'tag_value', e.target.value)}
        >
          <MenuItem value="" disabled>
            {t('permissions.roles.selectTagValue')}
          </MenuItem>
          {valueOptions.map((v) => (
            <MenuItem key={v} value={v}>
              {v}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      <IconButton size="small" onClick={() => onRemove(index)}>
        <DeleteIcon fontSize="small" />
      </IconButton>
    </Box>
  )
}

interface ResourceRow {
  resource_type: string
  resource_id: string | null
}

function ResourceRowEditor({
  row,
  index,
  resourceType,
  onChange,
  onRemove,
}: {
  row: ResourceRow
  index: number
  resourceType: string
  onChange: (index: number, value: string | null) => void
  onRemove: (index: number) => void
}) {
  const { t } = useTranslation()

  return (
    <Box display="flex" gap={1} alignItems="center">
      <Typography variant="body2" sx={{ minWidth: 100 }}>
        {resourceType}:
      </Typography>
      <TextField
        size="small"
        fullWidth
        placeholder={t('permissions.roles.resourceIdPlaceholder')}
        value={row.resource_id || ''}
        onChange={(e) => onChange(index, e.target.value || null)}
      />
      <IconButton size="small" onClick={() => onRemove(index)}>
        <DeleteIcon fontSize="small" />
      </IconButton>
    </Box>
  )
}

const DEFAULT_FORM = {
  resourceType: '',
  effect: PolicyEffect.Allow,
  actions: [] as string[],
  resources: [] as ResourceRow[],
  tagConditions: [] as TagConditionRow[],
}

export default function AddStatementDialog({
  open,
  roleId,
  editingPolicy = null,
  onClose,
}: AddStatementDialogProps) {
  const { t } = useTranslation()
  const createStatement = useCreatePolicyStatement()
  const updateStatement = useUpdatePolicyStatement()

  const isEditMode = !!editingPolicy

  const [dialogError, setDialogError] = useState<unknown>(null)
  const [form, setForm] = useState(DEFAULT_FORM)

  // Populate form in edit mode, reset in add mode
  useEffect(() => {
    if (open) {
      if (editingPolicy) {
        setForm({
          resourceType: editingPolicy.module,
          effect: editingPolicy.effect,
          actions: editingPolicy.actions.map((a) => a.action),
          resources: editingPolicy.resources.map((r) => ({
            resource_type: r.resource_type,
            resource_id: r.resource_id ?? null,
          })),
          tagConditions: editingPolicy.tag_conditions.map((tc) => ({
            tag_key: tc.tag_key,
            tag_value: tc.tag_value,
          })),
        })
      } else {
        setForm(DEFAULT_FORM)
      }
      setDialogError(null)
    }
  }, [open, editingPolicy])

  const handleResourceTypeChange = (value: string) => {
    setForm((f) => ({ ...f, resourceType: value, actions: [], resources: [] }))
  }

  const handleConditionChange = (
    index: number,
    field: 'tag_key' | 'tag_value',
    value: string
  ) => {
    setForm((f) => {
      const updated = [...f.tagConditions]
      updated[index] = {
        ...updated[index],
        [field]: value,
        // Reset value when key changes
        ...(field === 'tag_key' ? { tag_value: '' } : {}),
      }
      return { ...f, tagConditions: updated }
    })
  }

  const handleAddConditionRow = () => {
    setForm((f) => ({
      ...f,
      tagConditions: [...f.tagConditions, { tag_key: '', tag_value: '' }],
    }))
  }

  const handleRemoveConditionRow = (index: number) => {
    setForm((f) => ({
      ...f,
      tagConditions: f.tagConditions.filter((_, i) => i !== index),
    }))
  }

  const handleSave = async () => {
    try {
      setDialogError(null)
      const data = {
        effect: form.effect,
        module: form.resourceType,
        actions: form.actions.map((a) => ({ action: a })),
        resources: form.resources,
        tag_conditions: form.tagConditions.filter((tc) => tc.tag_key && tc.tag_value),
      }
      if (isEditMode) {
        await updateStatement.mutateAsync({ roleId, policyId: editingPolicy!.id, data })
      } else {
        await createStatement.mutateAsync({ roleId, data })
      }
      onClose()
    } catch (err) {
      setDialogError(err)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={() => {
        onClose()
        setDialogError(null)
      }}
      maxWidth="sm"
      fullWidth
    >
      <DialogTitle>
        {isEditMode
          ? t('permissions.roles.editPolicyStatement')
          : t('permissions.roles.addPolicyStatement')}
      </DialogTitle>
      <DialogContent>
        {dialogError != null && (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        )}
        <Stack spacing={2} sx={{ mt: 1 }}>
          {/* Resource Type */}
          <FreeSoloResourceTypeSelect
            value={form.resourceType}
            onChange={handleResourceTypeChange}
          />

          {/* Effect */}
          <FormControl required>
            <InputLabel>{t('permissions.roles.effect')}</InputLabel>
            <Select
              value={form.effect}
              label={t('permissions.roles.effect')}
              onChange={(e) =>
                setForm((f) => ({ ...f, effect: e.target.value as PolicyEffect }))
              }
            >
              <MenuItem value={PolicyEffect.Allow}>{t('permissions.roles.effectAllow')}</MenuItem>
              <MenuItem value={PolicyEffect.Deny}>{t('permissions.roles.effectDeny')}</MenuItem>
            </Select>
          </FormControl>

          {/* Actions */}
          <FreeSoloActionSelect
            value={form.actions}
            onChange={(newActions) => setForm((f) => ({ ...f, actions: newActions }))}
            disabled={!form.resourceType}
          />

          {/* Resource IDs */}
          <Box>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              {t('permissions.roles.placeholderFeature')}
            </Typography>
            <Typography variant="subtitle2" gutterBottom>
              {t('permissions.roles.resourceIds')}
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              {t('permissions.roles.resourceIdsHelp')}
            </Typography>
            <Stack spacing={1}>
              {form.resources.map((res, idx) => (
                <ResourceRowEditor
                  key={idx}
                  row={res}
                  index={idx}
                  resourceType={form.resourceType}
                  onChange={(i, value) => {
                    setForm((f) => {
                      const updated = [...f.resources]
                      updated[i] = { resource_type: f.resourceType, resource_id: value }
                      return { ...f, resources: updated }
                    })
                  }}
                  onRemove={(i) => {
                    setForm((f) => ({ ...f, resources: f.resources.filter((_, ridx) => ridx !== i) }))
                  }}
                />
              ))}
            </Stack>
            <Button
              size="small"
              startIcon={<AddIcon />}
              onClick={() => {
                if (!form.resourceType) return
                setForm((f) => ({
                  ...f,
                  resources: [...f.resources, { resource_type: f.resourceType, resource_id: null }],
                }))
              }}
              disabled={!form.resourceType}
              sx={{ mt: 0.5 }}
            >
              {t('permissions.roles.addResourceId')}
            </Button>
          </Box>

          {/* Tag Conditions */}
          <Box>
            <Typography variant="subtitle2" gutterBottom>
              {t('permissions.roles.tagConditions')}
            </Typography>
            <Stack spacing={1}>
              {form.tagConditions.map((row, i) => (
                <TagConditionRowEditor
                  key={i}
                  row={row}
                  index={i}
                  onChange={handleConditionChange}
                  onRemove={handleRemoveConditionRow}
                />
              ))}
            </Stack>
            <Button
              size="small"
              startIcon={<AddIcon />}
              onClick={handleAddConditionRow}
              sx={{ mt: 0.5 }}
            >
              {t('permissions.roles.addTagCondition')}
            </Button>
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button
          onClick={() => {
            onClose()
            setDialogError(null)
          }}
        >
          {t('app.cancel')}
        </Button>
        <Button
          onClick={handleSave}
          variant="contained"
          disabled={!form.resourceType || form.actions.length === 0 || createStatement.isPending || updateStatement.isPending}
        >
          {isEditMode ? t('app.save') : t('permissions.roles.saveStatement')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
