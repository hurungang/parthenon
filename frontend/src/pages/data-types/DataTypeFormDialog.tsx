import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  MenuItem,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { useCreateDataType, useUpdateDataType } from '../../hooks/useDataTypes'
import type { AgentDataType, AgentDataTypeField, DataTypeFieldType } from '../../types'

interface DataTypeFormDialogProps {
  open: boolean
  editDataType: AgentDataType | null
  onClose: () => void
  onSaved: () => Promise<void>
}

const FIELD_TYPE_OPTIONS: DataTypeFieldType[] = ['string', 'number', 'boolean', 'date', 'enum']

function emptyField(): AgentDataTypeField {
  return { name: '', type: 'string', enum_values: null, required: false, default: undefined }
}

/**
 * Create / edit dialog for Agent Data Types.
 * Supports a dynamic field editor with 5 field types (string, number, boolean, date, enum).
 *
 * Follows the Dialog Error Handling Standard:
 * 1. dialogError state for API error display
 * 2. try-catch around async operations
 * 3. Error cleared on open/close
 * 4. Error displayed in DialogContent FIRST
 */
export function DataTypeFormDialog({
  open,
  editDataType,
  onClose,
  onSaved,
}: DataTypeFormDialogProps) {
  const { t } = useTranslation()
  const createMutation = useCreateDataType()
  const updateMutation = useUpdateDataType()
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [saving, setSaving] = useState(false)

  // Form state
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')
  const [fields, setFields] = useState<AgentDataTypeField[]>([emptyField()])

  const isEditing = !!editDataType

  // Populate form when opening
  useEffect(() => {
    if (open) {
      if (editDataType) {
        setName(editDataType.name)
        setSlug(editDataType.slug)
        setDescription(editDataType.description ?? '')
        setFields(
          editDataType.fields.length > 0
            ? editDataType.fields.map((f) => ({ ...f }))
            : [emptyField()],
        )
      } else {
        setName('')
        setSlug('')
        setDescription('')
        setFields([emptyField()])
      }
      setDialogError(null)
      setSaving(false)
    }
  }, [open, editDataType])

  const handleAddField = () => {
    setFields((prev) => [...prev, emptyField()])
  }

  const handleRemoveField = (index: number) => {
    setFields((prev) => prev.filter((_, i) => i !== index))
  }

  const handleFieldChange = (index: number, key: keyof AgentDataTypeField, value: unknown) => {
    setFields((prev) => {
      const next = prev.map((f, i) => (i === index ? { ...f, [key]: value } as AgentDataTypeField : f))
      return next
    })
  }

  // Auto-generate slug from name on create
  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing && !slug) {
      setSlug(
        value
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-+|-+$/g, ''),
      )
    }
  }

  const isValid = name.trim().length > 0 && slug.trim().length > 0 && fields.length > 0

  const handleSave = async () => {
    if (!isValid) return
    try {
      setDialogError(null)
      setSaving(true)
      const payload = {
        name: name.trim(),
        slug: slug.trim(),
        description: description.trim() || null,
        fields: fields.filter((f) => f.name.trim().length > 0),
      }

      if (editDataType) {
        await updateMutation.mutateAsync({ id: editDataType.id, payload })
      } else {
        await createMutation.mutateAsync(payload)
      }

      await onSaved()
      onClose()
    } catch (err) {
      setDialogError(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={() => { onClose(); setDialogError(null) }}
      maxWidth="md"
      fullWidth
    >
      <DialogTitle>
        {isEditing ? t('admin.dataTypes.edit') : t('admin.dataTypes.create')}
      </DialogTitle>

      <DialogContent dividers>
        {/* Dialog Error Handling Standard: error displayed FIRST */}
        {dialogError !== null && (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        )}

        <Box display="flex" flexDirection="column" gap={2} pt={1}>
          {/* Name & Slug */}
          <TextField
            label={t('admin.dataTypes.name')}
            value={name}
            onChange={(e) => handleNameChange(e.target.value)}
            fullWidth
            required
          />
          <TextField
            label={t('admin.dataTypes.slug')}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            fullWidth
            required
            helperText={t('admin.dataTypes.slugHelper')}
          />
          <TextField
            label={t('admin.dataTypes.description')}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            fullWidth
            multiline
            rows={2}
          />

          {/* Field Editor */}
          <Box>
            <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography variant="subtitle2">{t('admin.dataTypes.fields')}</Typography>
              <Button
                size="small"
                startIcon={<AddIcon />}
                onClick={handleAddField}
              >
                {t('admin.dataTypes.addField')}
              </Button>
            </Box>

            {fields.length === 0 && (
              <Typography variant="body2" color="text.secondary">
                {t('admin.dataTypes.atLeastOneField')}
              </Typography>
            )}

            {fields.map((field, index) => (
              <Box
                key={index}
                sx={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 1,
                  mb: 1.5,
                  p: 1.5,
                  border: 1,
                  borderColor: 'divider',
                  borderRadius: 1,
                  flexWrap: 'wrap',
                }}
              >
                {/* Field name */}
                <TextField
                  label={t('admin.dataTypes.fieldName')}
                  value={field.name}
                  onChange={(e) => handleFieldChange(index, 'name', e.target.value)}
                  size="small"
                  sx={{ minWidth: 150, flex: 1 }}
                />

                {/* Field type selector */}
                <TextField
                  label={t('admin.dataTypes.fieldType')}
                  value={field.type}
                  onChange={(e) => {
                    const newType = e.target.value as DataTypeFieldType
                    handleFieldChange(index, 'type', newType)
                    // Clear enum_values when switching away from enum
                    if (newType !== 'enum') {
                      handleFieldChange(index, 'enum_values', null)
                    }
                  }}
                  select
                  size="small"
                  sx={{ minWidth: 120 }}
                >
                  {FIELD_TYPE_OPTIONS.map((opt) => (
                    <MenuItem key={opt} value={opt}>
                      {opt}
                    </MenuItem>
                  ))}
                </TextField>

                {/* Field description */}
                <TextField
                  label={t('admin.dataTypes.fieldDescription')}
                  value={field.description ?? ''}
                  onChange={(e) => handleFieldChange(index, 'description', e.target.value)}
                  size="small"
                  placeholder={t('admin.dataTypes.fieldDescriptionHint')}
                  sx={{ minWidth: 200, flex: 2 }}
                />

                {/* Enum values (conditional) */}
                {field.type === 'enum' && (
                  <TextField
                    label={t('admin.dataTypes.enumValues')}
                    value={(field.enum_values ?? []).join(', ')}
                    onChange={(e) =>
                      handleFieldChange(
                        index,
                        'enum_values',
                        e.target.value
                          .split(',')
                          .map((v) => v.trim())
                          .filter(Boolean),
                      )
                    }
                    size="small"
                    placeholder="val1, val2, val3"
                    sx={{ minWidth: 180, flex: 1 }}
                  />
                )}

                {/* Required toggle */}
                <FormControlLabel
                  control={
                    <Switch
                      size="small"
                      checked={field.required ?? false}
                      onChange={(e) => handleFieldChange(index, 'required', e.target.checked)}
                    />
                  }
                  label={t('admin.dataTypes.required')}
                  sx={{ mr: 0 }}
                />

                {/* Remove button */}
                <Tooltip title={t('admin.dataTypes.removeField')}>
                  <span>
                    <IconButton
                      size="small"
                      color="error"
                      onClick={() => handleRemoveField(index)}
                      disabled={fields.length <= 1}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
              </Box>
            ))}
          </Box>
        </Box>
      </DialogContent>

      <DialogActions>
        <Button onClick={() => { onClose(); setDialogError(null) }}>
          {t('app.cancel')}
        </Button>
        <Button
          variant="contained"
          onClick={handleSave}
          disabled={!isValid || saving}
        >
          {saving ? t('app.saving') : t('app.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
